"""导入引擎：异构测风数据识别与标准化。

设计目标（用户要求）：导入的数据格式、名称各异，需要标准化。
  · NRG SymphoniePRO 文本导出 —— 走精确签名解析（站点号/位置/经纬度/
    逐通道高度与 Avg·SD·Min·Max·Gust/风向/温压湿）。
  · 其它格式（CSV / 雷达 / 其它厂商文本）—— 走通用解析：自动探测分隔符、
    定位时间戳列、按列名与文件名推断设备类型与通道语义（风速/风向/温/压/湿）。

无论哪种来源，标准化输出统一为：
  · df        时序 DataFrame（datetime 索引 + 规范通道名）
  · channels  通道注册（名称/类型/标高/单位）
  · stats     每通道统计（均值/偏差/最大/最小/有效率）
  · meta      站点级元信息（设备类型/站点号/位置/时间范围/完整率）

零新增依赖：仅用标准库 + pandas/numpy。
"""

from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# 通道类型常量（与 dataset.py 保持一致）
KIND_SPEED = 'speed'
KIND_DIR = 'dir'
KIND_SPEED_SD = 'speed_sd'
KIND_TEMP = 'temp'
KIND_PRES = 'pres'
KIND_RH = 'rh'
KIND_WZ = 'wz'
KIND_OTHER = 'other'

# 设备类型推断关键词
_RADAR_KW = ['molas', 'lidar', '雷达', 'sodar', 'windcube', 'zephir',
             'leosphere', 'windfinder', 'radar']
_MAST_KW = ['symphonie', 'nrg', 'anem', '测风塔', 'mast', 'meas', '塔',
            'pro']

# ----------------------------------------------------------------------
# 统一规范通道命名（所有导入路径共用，确保杂乱后缀归一）
# ----------------------------------------------------------------------
# 规范名结构（用户示例格式，空格分隔）：`<Base> <高度>m [<方位>] <统计>`
#   Base      : Speed / Dir / Temp / Pres / RH / Wz / SNR / Avail
#   统计      : Avg / SD / Min / Max / Gust
#   例：`Speed 10m Avg` `Speed 10m SD` `Speed 150m NE Min` `Temp Avg`
#
# 统计词 → 规范统计段（覆盖中英文 / 缩写 / 大小写，杂乱写法统一归一）
_STAT_SUFFIX = {
    # 均值
    'avg': ' Avg', 'average': ' Avg', 'mean': ' Avg', 'means': ' Avg',
    '平均值': ' Avg', '平均': ' Avg', 'aver': ' Avg', 'val': ' Avg',
    'value': ' Avg', 'data': ' Avg', '': ' Avg',
    # 标准差
    'sd': ' SD', 'std': ' SD', 'stdev': ' SD', 'sigma': ' SD',
    'σ': ' SD', 'stddev': ' SD', '偏差': ' SD', '标准差': ' SD',
    # 最小
    'min': ' Min', 'minimum': ' Min', 'minim': ' Min',
    '最小值': ' Min', '最小': ' Min',
    # 最大
    'max': ' Max', 'maximum': ' Max', '最大值': ' Max', '最大': ' Max',
    # 阵风
    'gust': ' Gust', 'gusts': ' Gust', '阵风': ' Gust',
}
# 类型关键词 → 规范 Base（中英文/缩写）
_KIND_BASE = {
    'speed': 'Speed', 'spd': 'Speed', 'ws': 'Speed', 'wind': 'Speed',
    '风速': 'Speed', 'anem': 'Speed',
    'dir': 'Dir', 'wd': 'Dir', '风向': 'Dir', 'winddir': 'Dir',
    'vane': 'Dir',
    'temp': 'Temp', '气温': 'Temp', '温度': 'Temp', 't_': 'Temp',
    'pres': 'Pres', 'baro': 'Pres', '气压': 'Pres', 'p_': 'Pres',
    'press': 'Pres',
    'rh': 'RH', 'hum': 'RH', '湿度': 'RH',
    'wz': 'Wz', 'vert': 'Wz', '垂直': 'Wz',
    'snr': 'SNR', '信噪': 'SNR',
    'avail': 'Avail', '可用': 'Avail', '可靠性': 'Avail',
}
# 方位词（中英文皆可识别，统一规范为大写）
_ORIENT = {'N': 'N', 'North': 'N', '北': 'N',
           'S': 'S', 'South': 'S', '南': 'S',
           'E': 'E', 'East': 'E', '东': 'E',
           'W': 'W', 'West': 'W', '西': 'W',
           'NE': 'NE', 'Northeast': 'NE', '东北': 'NE',
           'NW': 'NW', 'Northwest': 'NW', '西北': 'NW',
           'SE': 'SE', 'Southeast': 'SE', '东南': 'SE',
           'SW': 'SW', 'Southwest': 'SW', '西南': 'SW'}


def _norm_stat_suffix(tok: str) -> str:
    """将统计词（任意大小写/中英文）归一到规范统计段
    ' Avg'/' SD'/' Min'/' Max'/' Gust'（带前导空格，直拼即可）。"""
    t = (tok or '').strip().lower().strip('[]()（）')
    return _STAT_SUFFIX.get(t, ' Avg')


# 通道 Subtype（角色）规范取值，必须与 Configure Dataset 对话框下拉一致：
#   ['Avg', 'SD', 'Min', 'Max', 'Gust', '']
# 历史上各解析器返回的是**原始 token**（'std'/'max'/'' 等），对话框用
# findText 匹配不到就回落到第 0 项 'Avg'，导致「列名明明写了 Std/Max/Min
# 却全被识别成 Avg」。统一走 _norm_role 归一化。
_ROLE_CANON = {
    'avg': 'Avg', 'average': 'Avg', 'mean': 'Avg', 'aver': 'Avg',
    '平均值': 'Avg', '平均': 'Avg', 'val': 'Avg', 'value': 'Avg',
    'data': 'Avg', '': 'Avg',
    'sd': 'SD', 'std': 'SD', 'stdev': 'SD', 'sigma': 'SD',
    'σ': 'SD', 'stddev': 'SD', '偏差': 'SD', '标准差': 'SD',
    'min': 'Min', 'minimum': 'Min', 'minim': 'Min',
    '最小值': 'Min', '最小': 'Min',
    'max': 'Max', 'maximum': 'Max', '最大值': 'Max', '最大': 'Max',
    'gust': 'Gust', 'gusts': 'Gust', 'gustdir': 'Gust',
    '阵风': 'Gust', '阵风方向': 'Gust',
}


def _norm_role(tok: str) -> str:
    """把任意写法的统计词归一到规范 Subtype：Avg/SD/Min/Max/Gust。

    识别不到时返回 'Avg'（默认视为平均值通道），绝不返回空串或原始 token。
    """
    t = (tok or '').strip().lower().strip('[]()（）')
    if t in _ROLE_CANON:
        return _ROLE_CANON[t]
    # 子串兜底：'stddev_10min' / 'max_gust' 等
    for k, v in _ROLE_CANON.items():
        if k and k in t:
            return v
    return 'Avg'


def _norm_kind_base(tok: str) -> str | None:
    """将类型词归一到规范 Base；识别不到返回 None。"""
    t = (tok or '').strip().lower().rstrip('s')
    if t in _KIND_BASE:
        return _KIND_BASE[t]
    # 子串兜底
    for k, v in _KIND_BASE.items():
        if k and k in t:
            return v
    return None


# 标准化命名词典：类型用全大写完整单词（用户要求 Dir→DIRECTION、
# Temp→TEMPERATURE、Pres→PRESSURE），统计段同样大写（AVG/SD/MIN/MAX/GUST）
CANON_TYPE_WORDS = {
    'Speed': 'SPEED', 'Dir': 'DIRECTION', 'Temp': 'TEMPERATURE',
    'Pres': 'PRESSURE', 'RH': 'RH', 'Wz': 'Wz', 'SNR': 'SNR',
    'Avail': 'AVAIL', 'Ch': 'Ch', 'TI': 'TI',
}
CANON_STAT_WORDS = {'Avg': 'AVG', 'SD': 'SD', 'Min': 'MIN', 'Max': 'MAX',
                    'Gust': 'GUST', 'GustDir': 'GUSTDIR'}


def build_canon_name(base: str, height, orient: str = '',
                     stat_suffix: str = '', letter: str = '') -> str:
    """构造标准化通道名（空格风格）：
    `SPEED 10m AVG` / `SPEED 150m NE MIN` / `TEMPERATURE AVG`（无高度省略段）。

    letter : 同类型同高度多支传感器时的区分后缀 A/B/C…（置于名称末尾；
             仅一支时不传，默认不加）。
    """
    base = CANON_TYPE_WORDS.get(base, base.upper() if base else base)
    parts = [base]
    if height is not None:
        parts.append(f'{height:g}m')
    if orient:
        parts.append(orient)
    if stat_suffix:
        # stat_suffix 约定带前导空格（' Avg'）或直接传 'Avg'
        st = stat_suffix.strip()
        parts.append(CANON_STAT_WORDS.get(st, st.upper()))
    if letter:
        parts.append(letter.strip().upper())
    return ' '.join(parts)

# SymphoniePRO 列名解析：Ch1_Anem_10.00m_E_Avg_m/s
_SYMPH_RE = re.compile(
    r'Ch\d+_(?P<type>Anem|Vane|Analog)_(?P<height>\d+\.?\d*)m'
    r'(?:_(?P<orient>[NSEW]))?_(?P<stat>Avg|SD|Min|Max|Gust|GustDir)'
    r'(?:_(?P<units>m/s|Deg|kPa|C|%RH))?'
)

# 通用列名语义关键词
_SPEED_RE = re.compile(r'(?:spd|ws|wind|风速|avgs?|speed)', re.I)
_DIR_RE = re.compile(r'(?:dir|wd|风向|winddir)', re.I)
_TEMP_RE = re.compile(r'(?:temp|t_|气温|温度|\bt\b)', re.I)
_PRES_RE = re.compile(r'(?:pres|baro|气压|p_|press)', re.I)
_RH_RE = re.compile(r'(?:rh|hum|湿度)', re.I)
_HEIGHT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:m|米)', re.I)

# 表头行识别关键词（时间戳 + 常见通道类型）
_TIME_KW = re.compile(r'(?:time|date|timestamp|日期|时间|年月日|datetime)', re.I)
_CHANNEL_KW = re.compile(
    r'(?:spd|speed|ws|wind|风速|dir|wd|风向|winddir|vane|anem|'
    r'temp|temperature|气温|温度|pres|pressure|baro|气压|'
    r'rh|hum|湿度|height|elevation|sdev|sd|std|min|max|avg|gust)', re.I)

# 经纬度/海拔正则（支持 = / : / 空格分隔，中英文）
_LAT_RE = re.compile(
    r'(?:^|\b|[:=\s])'
    r'(?:latitude|lat|纬度)[:=\s]*'
    r'([NSns][\s]*)?(\d+(?:\.\d+)?)', re.I)
_LON_RE = re.compile(
    r'(?:^|\b|[:=\s])'
    r'(?:longitude|lon|long|经度)[:=\s]*'
    r'([EWew][\s]*)?(\d+(?:\.\d+)?)', re.I)
_ELEV_RE = re.compile(
    r'(?:^|\b|[:=\s])'
    r'(?:elevation|elev|海拔|altitude|站高)[:=\s]*'
    r'(\d+(?:\.\d+)?)\s*(?:m|米)?', re.I)


@dataclass
class ParsedData:
    """一次导入解析后的归一化结果。"""
    path: str
    fmt: str = ''                  # 识别到的原始格式（SymphoniePRO / 通用）
    device_type: str = '未知'
    station_no: str = ''
    location: str = ''
    lat: float | None = None
    lon: float | None = None
    elevation: float | None = None
    t_start: str = ''
    t_end: str = ''
    dt_min: float = 10.0
    n_rows: int = 0
    n_expected: int = 0
    completeness: float = 0.0
    data_availability: float = 0.0      # 雷达特有：数据有效率
    df: pd.DataFrame = field(default_factory=pd.DataFrame)
    channels: list = field(default_factory=list)   # [dict]
    stats: list = field(default_factory=list)      # [dict]
    # 原始列名 → 规范名 映射（标准化对话框展示对照；Symphonie/WRA 等格式
    # 解析时记录，供“执行标准化”展示 原始名→规范名）
    col_origins: dict = field(default_factory=dict)


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------
# 行业常见导入格式（扩展名 + 内容标记识别）：
#   .rwd  Windographer 数据文件（文本，含 [Header] 等段）
#   .rld  NRG SymphoniePRO 原始二进制数据（无法直接文本解析）
#   .ndf  NRG 数据文件（二进制）
#   .asc / .sta / .row  通用 ASCII 时序
#   Triton（Second Wind 声雷达）/ WindPortal / Kintech  按内容标记识别
_FMT_MARKERS = (
    ('Triton 声雷达', ('Triton', 'Second Wind')),
    ('WindPortal', ('WindPortal',)),
    ('Kintech', ('Kintech', 'KINTECH')),
)

# ---------------------------------------------------------------------------
# 专用解析器注册表（S3 插件化入口）
# ---------------------------------------------------------------------------
# 条目 = {'name': 展示名, 'match': (path, sniff_head)->bool, 'parser': (path)}
# 注册顺序即兜底探测优先级（注册调用在模块尾部，解析函数定义之后）。
# 新增格式：实现 _parse_xxx(path) -> ParsedData + 一个 match 谓词，
# 在文件尾部「解析器注册区」加一行 register_parser(...) 即可。
_PARSERS: list[dict] = []


def register_parser(name: str, match):
    """装饰器/直调两用：把专用解析器登记进 _PARSERS（保持注册顺序）。"""
    def deco(fn):
        _PARSERS.append({'name': name, 'match': match, 'parser': fn})
        return fn
    return deco


def detect_special_format(path: str, header_text: str = '') -> str:
    """返回识别到的专用格式名；未识别返回 ''。"""
    low = path.lower()
    if low.endswith('.rwd'):
        return 'Windographer 数据文件'
    if low.endswith('.rld'):
        return 'NRG SymphoniePRO RLD'
    if low.endswith('.ndf'):
        return 'NRG NDF'
    for name, marks in _FMT_MARKERS:
        if any(m in header_text for m in marks):
            return name
    if low.endswith('.asc'):
        return 'ASCII (.asc)'
    if low.endswith('.sta'):
        return 'ASCII (.sta)'
    if low.endswith('.row'):
        return 'ASCII (.row)'
    return ''


def parse_file(path: str) -> ParsedData:
    """通用入口：按文件扩展名与内容自动识别并解析单个数据文件。

    策略：
      1. Excel 走 _parse_excel；
      2. NRG 二进制 .rld/.ndf 直接给出友好提示（需先用官方软件导出文本）；
      3. 其余统一走 _parse_universal（自动编码、自动定位表头、按列名语义识别通道）；
      4. 若通用解析结果明显不佳（无风速/风向通道且列数过少），按 _PARSERS
         注册顺序探测专用解析器（S3 插件化：新增格式只需写解析函数并在
         模块尾部的注册区加一行，不再改动本函数）。
    """
    low = path.lower()
    if low.endswith('.xlsx') or low.endswith('.xls'):
        parsed = _parse_excel(path)
    elif low.endswith('.rld') or low.endswith('.ndf'):
        raise ValueError(
            '检测到 NRG 二进制格式文件（.rld/.ndf），暂不支持直接导入。\n'
            '请先用 SymphoniePRO / NRG 官方软件将其导出为 TXT/CSV 后重试。\n'
            'Detected NRG binary file (.rld/.ndf). Please export it to '
            'TXT/CSV with the NRG software first.')
    else:
        sniff_head = ''
        try:
            sniff_head = ''.join(_read_lines_robust(path, max_lines=200))
        except Exception:
            pass
        fmt = detect_special_format(path, sniff_head)

        # Windographer .rwd 为带段头的文本文件，直接走专用解析器
        if low.endswith('.rwd'):
            parsed = _parse_windographer(path)
            parsed.fmt = fmt
        else:
            # 默认统一通用识别
            parsed = _parse_universal(path)

            # 通用识别失败/太弱时，按注册表顺序探测专用解析器作为后备
            recognized = [c for c in parsed.channels
                          if c.get('kind') in (KIND_SPEED, KIND_DIR, KIND_TEMP,
                                               KIND_PRES, KIND_RH)]
            if len(recognized) < 2 and len(parsed.channels) < 3:
                for entry in _PARSERS:
                    if entry['match'](path, sniff_head):
                        parsed = entry['parser'](path)
                        break

        # 记录识别到的专用格式；Triton 等雷达格式补充设备类型
        if fmt:
            parsed.fmt = fmt or parsed.fmt
            if 'Triton' in fmt and parsed.device_type in ('未知', ''):
                parsed.device_type = '声雷达'

    # 统一收尾：用数值统计复核/补全类别与子类型，再重算统计
    _refine_by_stats(parsed.df, parsed.channels)
    parsed.stats = _compute_stats(parsed.df, parsed.channels)
    return parsed


def _extract_geo_meta(lines: list[str]) -> tuple[float | None, float | None, float | None]:
    """从文件前部任意行提取经纬度、海拔。不依赖固定行号/标记。"""
    lat = lon = elevation = None
    for ln in lines[:500]:
        s = ln.strip()
        if not s or s.startswith('#'):
            continue
        # 纬度
        if lat is None:
            m = _LAT_RE.search(s)
            if m:
                val = _fnum(m.group(2))
                if val is not None:
                    sign = -1.0 if (m.group(1) or '').strip().upper() == 'S' else 1.0
                    lat = sign * val
        # 经度
        if lon is None:
            m = _LON_RE.search(s)
            if m:
                val = _fnum(m.group(2))
                if val is not None:
                    sign = -1.0 if (m.group(1) or '').strip().upper() == 'W' else 1.0
                    lon = sign * val
        # 海拔
        if elevation is None:
            m = _ELEV_RE.search(s)
            if m:
                elevation = _fnum(m.group(1))
        if lat is not None and lon is not None and elevation is not None:
            break
    return lat, lon, elevation


def _find_header_row(lines: list[str], max_scan: int = 100) -> int:
    """自动定位表头行：优先选择字段数多、含时间戳关键词、含通道关键词的行。

    不依赖固定行号，适用于 Windographer/Symphonie/通用 CSV 等各种导出。
    """
    best_idx = 0
    best_score = -1.0
    for i, ln in enumerate(lines[:max_scan]):
        s = ln.strip()
        if not s or s.startswith('#'):
            continue
        # 用 pandas 尝试分词估算字段数
        toks = [t.strip() for t in re.split(r'[\t,;|]', s) if t.strip()]
        n = len(toks)
        if n < 2:
            continue
        # 字段数突变加权（表头通常比元数据行字段多很多）
        prev_n = len([t.strip() for t in re.split(r'[\t,;|]', lines[i-1]) if t.strip()]) if i > 0 else 0
        jump = max(0, n - prev_n)
        # 含时间戳/通道关键词
        has_time = bool(_TIME_KW.search(s))
        has_chan = bool(_CHANNEL_KW.search(s))
        # 含纯数字的数据行惩罚（表头应含字母）
        alpha_ratio = sum(1 for c in s if c.isalpha()) / max(len(s), 1)
        numeric_only = all(re.match(r'^-?\d+(\.\d+)?$', t) for t in toks)
        if numeric_only:
            continue
        score = n + jump * 2 + (5 if has_time else 0) + (3 if has_chan else 0)
        score *= alpha_ratio
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


def _parse_universal(path: str) -> ParsedData:
    """通用解析：自动编码、自动定位表头、自动提取元数据、按列名语义识别通道。"""
    lines = _read_lines_robust(path)
    lat, lon, elevation = _extract_geo_meta(lines)
    header_idx = _find_header_row(lines)

    delim = _sniff_delimiter(path) or '\t'
    df = read_csv_robust(path, sep=delim, skiprows=header_idx,
                         dtype=str, keep_default_na=False,
                         skip_blank_lines=True, on_bad_lines='skip')

    # 丢弃空列
    keep = [c for c in df.columns
            if c and str(c).strip() and df[c].notna().any()]
    if keep:
        df = df[keep]
    df = df.replace('', np.nan)

    tcol = _find_time_col(df)
    if tcol is None:
        # 未识别到时间列，尝试第一列
        tcol = df.columns[0]
    df[tcol] = _pd_to_datetime(df[tcol], errors='coerce')
    df = df.dropna(subset=[tcol])
    df = df.set_index(tcol).sort_index()
    df.index.name = 't'

    channels = []
    rename_map = {}
    for col in df.columns:
        if col == df.index.name:
            continue
        raw = str(col).strip()
        # 优先 Symphonie 风格正则（Ch*_Anem/Vane/Analog_...）
        m = _SYMPH_RE.match(raw)
        if m:
            type_map = {'Anem': 'Speed', 'Vane': 'Dir', 'Analog': None}
            base = type_map[m.group('type')]
            h = float(m.group('height'))
            orient = m.group('orient') or ''
            stat = _norm_role(m.group('stat'))
            units = (m.group('units') or '').strip()
            if not units:
                units = _extract_unit(raw)
            if base is None:
                base, units = _infer_analog_type(units, raw)
            suffix = f' {stat}'
            canon = build_canon_name(base or 'Ch', h, orient, suffix)
            kind = {'Speed': KIND_SPEED, 'Dir': KIND_DIR, 'Temp': KIND_TEMP,
                    'Pres': KIND_PRES, 'RH': KIND_RH, 'Wz': KIND_WZ}.get(base, KIND_OTHER)
        else:
            canon, kind, h, units, role = _canon_generic(raw)
            stat = role or 'Avg'
        rename_map[col] = canon
        channels.append({'name': canon, 'kind': kind, 'height': h,
                         'units': units, 'role': stat, 'orig': raw})

    df = df.rename(columns=rename_map)

    # 处理 rename 后列名重复的情况（不同原始列映射到同一规范名）
    seen = {}
    new_cols = []
    for c in df.columns:
        base = c
        cnt = seen.get(base, 0)
        seen[base] = cnt + 1
        new_cols.append(base if cnt == 0 else f'{base}_{cnt + 1}')
    df.columns = new_cols

    # 同步更新通道注册表（channels 与 rename_map 同顺序，按位置对应）
    final_channels = []
    for idx, (old_col, ch) in enumerate(zip(rename_map.keys(), channels)):
        ch['name'] = new_cols[idx]
        final_channels.append(ch)

    for col in df.columns:
        if col != df.index.name:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    device = detect_device_type(os.path.basename(path),
                                header_text=''.join(lines[:header_idx]))
    meta = _finalize(path, df, device_type=device, lat=lat, lon=lon)
    meta.fmt = '通用识别'
    meta.elevation = elevation
    meta.channels = final_channels
    meta.stats = _compute_stats(df, final_channels)
    meta.col_origins = {old: new_cols[i] for i, old in enumerate(rename_map.keys())}
    return meta


def detect_device_type(filename: str, header_text: str = '') -> str:
    low = filename.lower()
    hlow = header_text.lower()
    if any(k in low or k in hlow for k in _RADAR_KW):
        return '雷达'
    if 'symphonie' in hlow or 'nrg systems' in hlow:
        return '测风塔'
    if any(k in low for k in _MAST_KW):
        return '测风塔'
    return '未知'


# ----------------------------------------------------------------------
# SymphoniePRO 精确解析
# ----------------------------------------------------------------------
def _parse_symphonie(path: str) -> ParsedData:
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    station_no = location = ''
    lat = lon = None
    for ln in lines[:400]:
        s = ln.strip()
        if s.startswith('Site Number:'):
            station_no = s.split(':', 1)[1].strip()
        elif s.startswith('Location:'):
            location = s.split(':', 1)[1].strip()
        elif s.startswith('Site Description:') and not location:
            location = s.split(':', 1)[1].strip()
        elif s.startswith('Latitude:'):
            lat = _fnum(s.split(':', 1)[1].strip())
        elif s.startswith('Longitude:'):
            lon = _fnum(s.split(':', 1)[1].strip())

    # 定位数据表头
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.startswith('Timestamp'):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError('SymphoniePRO 文件未找到 Timestamp 数据表头')

    header = lines[header_idx].rstrip('\n').split('\t')
    cols = header[1:]
    colspec = [_parse_symph_col(c) for c in cols]
    rename = [c['canonical'] for c in colspec]

    ts, rows = [], []
    for ln in lines[header_idx + 1:]:
        parts = ln.rstrip('\n').split('\t')
        if len(parts) < len(header):
            continue
        ts.append(parts[0])
        rows.append([_fnum(p) for p in parts[1:len(header)]])

    df = pd.DataFrame(rows, columns=rename)
    df.insert(0, 'Timestamp', _pd_to_datetime(ts, errors='coerce'))
    df = df.set_index('Timestamp').sort_index()
    df = df[~df.index.isna()]
    df.index.name = 't'

    meta = _finalize(path, df, device_type='测风塔',
                     station_no=station_no, location=location,
                     lat=lat, lon=lon)
    meta.fmt = 'SymphoniePRO'
    meta.channels = _channels_from_colspec(colspec)
    meta.stats = _compute_stats(df, meta.channels)
    meta.col_origins = {c['canonical']: c for c in colspec}
    # 原始列名 → 规范名（键=原始名）
    meta.col_origins = {}
    for raw, spec in zip(cols, colspec):
        meta.col_origins[raw] = spec['canonical']
    return meta


def _parse_symph_col(col: str) -> dict:
    raw = col.strip()
    m = _SYMPH_RE.search(col)
    if not m:
        return {'canonical': raw, 'kind': KIND_OTHER, 'height': None,
                'units': '', 'stat': '', 'orig': raw}
    g = m.groupdict()
    typ, h, o, stat, units = (g['type'], g['height'], g['orient'] or '',
                              g['stat'], g['units'] or '')
    h = float(h)
    o = o if o else ''
    suffix = f'_{o}' if o else ''
    if typ == 'Anem':
        kind = KIND_SPEED
        units = units or 'm/s'
        canon = build_canon_name('Speed', h, o, _norm_stat_suffix(stat))
    elif typ == 'Vane':
        kind = KIND_DIR
        units = units or 'Deg'
        canon = build_canon_name('Dir', h, o, _norm_stat_suffix(stat))
    else:  # Analog
        units = units or ''
        if units == 'kPa':
            kind, canon = KIND_PRES, 'Pres'
        elif units == 'C':
            kind, canon = KIND_TEMP, 'Temp'
        elif units == '%RH':
            kind, canon = KIND_RH, 'RH'
        else:
            kind, canon = KIND_OTHER, build_canon_name(
                'Analog', h, '', _norm_stat_suffix(stat))
        suffix2 = _norm_stat_suffix(stat)
        if suffix2 and not canon.endswith(suffix2.strip()):
            canon = build_canon_name(canon, None, '', suffix2)
    return {'canonical': canon, 'kind': kind, 'height': h, 'units': units,
            'stat': stat, 'orig': raw}


def _channels_from_colspec(colspec: list) -> list:
    out = []
    for c in colspec:
        out.append({'name': c['canonical'], 'kind': c['kind'],
                    'height': c['height'], 'units': c['units'],
                    'role': _norm_role(c.get('stat', '')),
                    'orig': c.get('orig', c['canonical'])})
    return out


# ----------------------------------------------------------------------
# Molas 雷达精确解析（B300/Z300 等 WindSpeedTenMinute 文本导出）
# ----------------------------------------------------------------------
# 列头：年月日 / 时间戳 / 经度 / 纬度 / 内温 / 外温 / 气压 / 湿度 /
#       雨刮器计数 / 样本数，之后每个高度层 10 列：
#   水平风速 / 偏差 / 最小 / 最大 / 水平风向 / z方向风速 / z方向偏差 /
#   信噪比 / 信噪比最小 / 数据可靠性(%)
_MOLAS_SUB = {
    0: ('Speed', KIND_SPEED, 'm/s', 'Avg'),
    1: ('Speed', KIND_SPEED_SD, 'm/s', 'SD'),
    2: ('Speed', KIND_SPEED, 'm/s', 'Min'),
    3: ('Speed', KIND_SPEED, 'm/s', 'Max'),
    4: ('Dir', KIND_DIR, 'Deg', 'Avg'),
    5: ('Wz', KIND_WZ, 'm/s', 'Avg'),
    6: ('Wz', KIND_WZ, 'm/s', 'SD'),
    7: ('SNR', KIND_OTHER, 'dB', 'Avg'),
    8: ('SNR', KIND_OTHER, 'dB', 'Min'),
    9: ('Avail', KIND_OTHER, '%', 'Avg'),
}
_DMS_RE = re.compile(
    r'^([NSEW])\s*(\d+)\s*°\s*(\d+)\s*[′\']\s*([\d.]+)\s*[″\"]?$', re.UNICODE)


def _read_lines(path: str) -> list:
    """逐行鲁棒解码：先试 UTF-8，失败回退 GBK，再回退 latin-1。

    Molas 导出的实际样本是混合编码——顶部元数据为 UTF-8（ASCII），
    列头与数据行含中文/度分秒符号，为 GBK。逐行解码可兼容这种混杂。
    """
    out = []
    with open(path, 'rb') as f:
        for raw in f:
            try:
                out.append(raw.decode('utf-8'))
            except UnicodeDecodeError:
                try:
                    out.append(raw.decode('gbk'))
                except UnicodeDecodeError:
                    out.append(raw.decode('latin-1'))
    return out


def _parse_molas(path: str) -> ParsedData:
    lines = _read_lines(path)

    device_id = ''
    for ln in lines[:12]:
        s = ln.strip()
        if s.startswith('ID System'):
            device_id = s.split('=', 1)[1].strip()

    # 定位列头：含「年月日」且含「水平风速」的行
    header_idx = None
    for i, ln in enumerate(lines):
        if '年月日' in ln and '水平风速' in ln:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError('Molas 文件未找到数据列头（年月日 / 水平风速）')

    header = lines[header_idx].rstrip('\n').split('\t')
    altitudes = _molas_altitudes(lines, header)
    if not altitudes:
        raise ValueError('Molas 文件未能解析出高度层（Altitudes 行缺失）')

    # 构造列规范（索引 2 起为数值列；0=日期 1=时间 用于拼时间戳）
    rename_spec = [_molas_col(j, header, altitudes) for j in range(2, len(header))]
    rename = [s['canonical'] for s in rename_spec]

    ts, rows = [], []
    for ln in lines[header_idx + 1:]:
        line = ln.rstrip('\n')
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < len(header):
            parts = parts + [''] * (len(header) - len(parts))
        if len(parts) < len(header):
            continue
        date, time = parts[0].strip(), parts[1].strip()
        t = _pd_to_datetime(f'{date} {time}', errors='coerce')
        if pd.isna(t):
            continue
        ts.append(t)
        vals = []
        for k, spec in enumerate(rename_spec):
            raw = parts[k + 2]
            vals.append(_parse_dms(raw) if spec['is_dms'] else _fnum(raw))
        rows.append(vals)

    if not rows:
        raise ValueError('Molas 文件未解析出任何数据行')

    df = pd.DataFrame(rows, columns=rename)
    df.insert(0, 'Timestamp', _pd_to_datetime(ts, errors='coerce'))
    df = df.set_index('Timestamp').sort_index()
    df = df[~df.index.isna()]
    df.index.name = 't'

    # 站点级元信息
    lat = float(df['Lat'].median()) if 'Lat' in df.columns else None
    lon = float(df['Lon'].median()) if 'Lon' in df.columns else None
    # 雷达有效率：各层 数据可靠性(%) 的均值（新规范名 `Avail <h>m Avg`）
    avail_cols = [c for c in rename if c.startswith('Avail')]
    data_av = 0.0
    if avail_cols:
        av = df[avail_cols].apply(pd.to_numeric, errors='coerce').mean()
        data_av = float(av.mean()) if pd.notna(av.mean()) else 0.0

    meta = _finalize(path, df, device_type='雷达',
                     station_no='', location='', lat=lat, lon=lon)
    meta.fmt = 'Molas雷达'
    meta.data_availability = round(data_av, 2)
    meta.channels = [{'name': s['canonical'], 'kind': s['kind'],
                      'height': s['height'], 'units': s['units'],
                      'role': s['role'],
                      'orig': header[k + 2] if k + 2 < len(header) else s['canonical']}
                     for k, s in enumerate(rename_spec)]
    meta.stats = _compute_stats(df, meta.channels)
    # 原始列名（中文列头）→ 规范名
    meta.col_origins = {}
    for k, spec in enumerate(rename_spec):
        raw = header[k + 2] if k + 2 < len(header) else ''
        meta.col_origins[raw] = spec['canonical']
    if device_id:
        meta.location = device_id  # 默认建议位置（用户可在导入时改）
    return meta


def _molas_altitudes(lines, header):
    """优先从 Altitudes (m)= 行解析；失败则回退到列头高度。"""
    for ln in lines[:12]:
        s = ln.strip()
        if s.startswith('Altitudes (m)'):
            parts = s.split('=', 1)[1].split()
            try:
                alts = [float(x) for x in parts]
                if alts:
                    return alts
            except Exception:
                pass
    alts = []
    for j in range(10, len(header), 10):
        m = re.search(r'(\d+(?:\.\d+)?)\s*m水平风速', header[j])
        if m:
            alts.append(float(m.group(1)))
    return alts


def _molas_col(idx, header, altitudes):
    if idx == 2:
        return {'canonical': 'Lon', 'kind': KIND_OTHER, 'height': None,
                'units': '°', 'role': '', 'is_dms': True}
    if idx == 3:
        return {'canonical': 'Lat', 'kind': KIND_OTHER, 'height': None,
                'units': '°', 'role': '', 'is_dms': True}
    if idx == 4:
        return {'canonical': 'TempIn', 'kind': KIND_TEMP, 'height': None,
                'units': '℃', 'role': 'Avg', 'is_dms': False}
    if idx == 5:
        return {'canonical': 'TempOut', 'kind': KIND_TEMP, 'height': None,
                'units': '℃', 'role': 'Avg', 'is_dms': False}
    if idx == 6:
        return {'canonical': 'Pres', 'kind': KIND_PRES, 'height': None,
                'units': 'hPa', 'role': 'Avg', 'is_dms': False}
    if idx == 7:
        return {'canonical': 'RH', 'kind': KIND_RH, 'height': None,
                'units': '%', 'role': 'Avg', 'is_dms': False}
    if idx == 8:
        return {'canonical': 'Wipers', 'kind': KIND_OTHER, 'height': None,
                'units': '', 'role': '', 'is_dms': False}
    if idx == 9:
        return {'canonical': 'Samples', 'kind': KIND_OTHER, 'height': None,
                'units': '', 'role': '', 'is_dms': False}
    # 高度层分组（每 10 列一组）
    group = idx - 10
    alt_i = group // 10
    sub = group % 10
    h = altitudes[alt_i] if alt_i < len(altitudes) else float('nan')
    base, kind, units, role = _MOLAS_SUB[sub]
    # 统一规范名：均值→''，其它按 _norm_stat_suffix
    suffix = _norm_stat_suffix(role) if role else ''
    canon = build_canon_name(base, h, '', suffix)
    return {'canonical': canon, 'kind': kind, 'height': h,
            'units': units, 'role': role, 'is_dms': False}


def _parse_dms(s):
    if s is None:
        return float('nan')
    m = _DMS_RE.match(str(s).strip())
    if not m:
        return float('nan')
    hemi = m.group(1)
    val = int(m.group(2)) + int(m.group(3)) / 60.0 + float(m.group(4)) / 3600.0
    if hemi in ('S', 'W'):
        val = -val
    return round(val, 6)


# ----------------------------------------------------------------------
# WRA 标准化格式解析（其它软件导出的可交换格式）
# ----------------------------------------------------------------------
# 列名形如 `SPEED 150m NE AVG [m/s]` → 字段 = 类型 / 高度m / [方位] / 统计 / [单位]
#   类型：SPEED / DIRECTION / TEMPERATURE / PRESSURE / (RH 等)
#   方位：NE / SE / ...（可空，表示全向）
#   统计：AVG / SD / MIN / MAX / GUST（及其它杂乱写法，见 _norm_* 映射）
# 前 3 行是站点头：Latitude = / Longitude = / Elevation =
_WRA_COL_RE = re.compile(
    r'^(?P<typ>SPEED|DIRECTION|TEMPERATURE|PRESSURE|RH|HUMIDITY|WIND|'
    r'ANEM|VANE|WIND[S]?PEED|SD|MIN|MAX|AVG|GUST)\s+'
    r'(?P<h>\d+(?:\.\d+)?)m(?:\s+(?P<orient>NE|SE|NW|SW|N|E|S|W))?\s+'
    r'(?P<stat>AVG|SD|MIN|MAX|GUST|MEAN|STD|σ|平均值|最小|最大|阵风)'
    r'\s*\[(?P<units>[^\]]*)\]', re.I)
# 备用：无单位方括号的写法 `SPEED 150m NE AVG`
_WRA_COL_RE2 = re.compile(
    r'^(?P<typ>SPEED|DIRECTION|TEMPERATURE|PRESSURE|RH|HUMIDITY|WIND|'
    r'ANEM|VANE|WIND[S]?PEED)\s+'
    r'(?P<h>\d+(?:\.\d+)?)m(?:\s+(?P<orient>NE|SE|NW|SW|N|E|S|W))?\s+'
    r'(?P<stat>AVG|SD|MIN|MAX|GUST|MEAN|STD|σ|平均值|最小|最大|阵风)', re.I)


# ----------------------------------------------------------------------
# 鲁棒读取（编码回退：utf-8 → cp1252 → latin-1 永不失败）
# ----------------------------------------------------------------------
def _read_lines_robust(path: str, max_lines: int | None = None) -> list:
    """读取文件行（max_lines 限量），自动回退编码。latin-1 对每个字节
    1:1 解码，永不抛错。"""
    import itertools
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc) as f:
                if max_lines is None:
                    return f.readlines()
                return list(itertools.islice(f, max_lines))
        except UnicodeDecodeError:
            continue
    with open(path, 'r', encoding='latin-1') as f:
        if max_lines is None:
            return f.readlines()
        return list(itertools.islice(f, max_lines))


def _as_num(s: pd.Series) -> pd.Series:
    """按需转数值：已是数值 dtype 的列原样返回（S3 性能：避免整列反复
    to_numeric，大数据集上占导入耗时的 ~20%）。"""
    if pd.api.types.is_numeric_dtype(s.dtype):
        return s
    return pd.to_numeric(s, errors='coerce')


def read_csv_robust(path: str, **kw):
    """pd.read_csv 带编码回退；encoding 缺省时依次尝试 utf-8/cp1252/latin-1。"""
    last = None
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except UnicodeDecodeError as e:
            last = e
    return pd.read_csv(path, encoding='latin-1', **kw)


def _looks_datetime(tok) -> bool:
    """首字段是否可解析为时间（用于定位表头行）。"""
    if tok is None:
        return False
    t = str(tok).strip()
    if not t:
        return False
    try:
        ts = _pd_to_datetime(t, errors='coerce')
    except Exception:
        return False
    return ts is not None and not pd.isna(ts)


def _parse_coord(s: str):
    """解析 `Latitude = N 26.498700` / `Longitude = E 108.051169` 等，
    处理 N/S/E/W 半球符号；DMS 写法回退到 _parse_dms。"""
    rhs = s.split('=', 1)[1].strip()
    parts = rhs.split()
    sign = 1.0
    if parts and parts[0].upper() in ('S', 'W'):
        sign = -1.0
    elif parts and parts[0].upper() in ('N', 'E'):
        sign = 1.0
    last = parts[-1] if parts else ''
    val = _fnum(last)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return _parse_dms(rhs)
    return sign * val


# Windographer 导出风格（下划线 + boom 字母）：WindSpeed140mB_Avg [m/s]
_WRA_COL_RE3 = re.compile(
    r'^(?P<typ>WindSpeed|WindDirect|WindDirection|WindDir|Temperature|Temp|'
    r'Pressure|BarometricPressure|BP|RelHumidity|RH|AirDensity|Density|'
    r'GustSpeed|CompassDirection|WindComponent|WindChill|'
    r'CrossWind|HeadWind)\s*'
    r'(?P<h>\d+(?:\.\d+)?)m(?P<boom>[A-Za-z])?\s*'
    r'_?(?P<stat>Avg|Min|Max|Std|VectorAvg|VectorMean|VecAvg|VecMean|'
    r'Gust|Mean)\b'
    r'(?:\s*\[[^\]]*\])*\s*$', re.I)

# 下划线/boom 风格 类型词 → 规范 Base
_WG_TYPE_MAP = {
    'windspeed': 'Speed', 'winddirect': 'Dir', 'winddirection': 'Dir',
    'winddir': 'Dir', 'temperature': 'Temp', 'temp': 'Temp',
    'pressure': 'Pres', 'barometricpressure': 'Pres', 'bp': 'Pres',
    'relhumidity': 'RH', 'rh': 'RH', 'airdensity': 'Density',
    'density': 'Density', 'gustspeed': 'Speed', 'compassdirection': 'Dir',
    'windcomponent': 'Speed', 'windchill': 'Temp',
    'crosswind': 'Speed', 'headwind': 'Speed',
}
# 下划线/boom 风格 统计词 → 规范统计段
_WG_STAT_MAP = {
    'avg': ' Avg', 'mean': ' Avg', 'min': ' Min', 'max': ' Max',
    'std': ' SD', 'vectoravg': ' VecAvg', 'vectormean': ' VecAvg',
    'vecavg': ' VecAvg', 'vecmean': ' VecAvg', 'gust': ' Gust',
}


def _parse_wra_colname(raw: str):
    """将 WRA 列名解析为 (base, height, orient, stat_raw, suffix, units)。

    先尝试空格风格（_WRA_COL_RE / _WRA_COL_RE2），再尝试 Windographer
    下划线/boom 风格（_WRA_COL_RE3）。匹配不上返回 None。"""
    m = _WRA_COL_RE.match(raw) or _WRA_COL_RE2.match(raw)
    if m:
        g = m.groupdict()
        typ = (g.get('typ') or '').upper()
        h = float(g['h']) if g.get('h') else None
        orient = _ORIENT.get((g.get('orient') or '').upper(), '')
        stat_raw = (g.get('stat') or '').upper()
        suffix = _norm_stat_suffix(stat_raw)
        units = (g.get('units') or '').strip()
        base = _norm_kind_base(typ) or 'Ch'
        return base, h, orient, stat_raw, suffix, units
    m3 = _WRA_COL_RE3.match(raw)
    if m3:
        g = m3.groupdict()
        typ = (g.get('typ') or '').lower()
        base = _WG_TYPE_MAP.get(typ)
        if base is None:
            base = _norm_kind_base(typ) or 'Ch'
        h = float(g['h']) if g.get('h') else None
        orient = ''   # boom 字母（传感器标识，如 140mB）不计入罗盘方位
        stat_raw = (g.get('stat') or '').lower()
        suffix = _WG_STAT_MAP.get(stat_raw, _norm_stat_suffix(stat_raw))
        return base, h, orient, stat_raw.upper(), suffix, ''
    return None


def _parse_wra_standard(path: str) -> ParsedData:
    lines = _read_lines_robust(path)
    delim = _sniff_delimiter(path) or '\t'

    # 定位表头行：首个含分隔符、且其下一行首字段可解析为时间的行
    header_idx = None
    for i, ln in enumerate(lines):
        if delim and delim in ln:
            nxt = lines[i + 1] if i + 1 < len(lines) else ''
            first = nxt.split(delim)[0].strip()
            if _looks_datetime(first):
                header_idx = i
                break
    if header_idx is None:
        for i, ln in enumerate(lines):
            if re.search(r'(?i)date\s*/?\s*time', ln):
                header_idx = i
                break
    if header_idx is None:
        header_idx = 3  # 兜底：旧式 3 行头

    # 元数据扫描（覆盖全部头部行，兼容任意行数的站点头）
    lat = lon = elevation = None
    for ln in lines[:header_idx]:
        s = ln.strip().rstrip('\t')
        up = s.upper()
        if up.startswith('LATITUDE'):
            lat = _parse_coord(s)
        elif up.startswith('LONGITUDE'):
            lon = _parse_coord(s)
        elif up.startswith('ELEVATION'):
            m = re.search(r'([\d.]+)', s)
            elevation = float(m.group(1)) if m else None

    # 表头列名：去掉 Windographer 常见的尾随空字段，避免 表头/数据 列数不一致
    col_names = lines[header_idx].rstrip('\n').split(delim)
    while col_names and col_names[-1].strip() == '':
        col_names.pop()
    if not col_names:
        col_names = None

    try:
        df = read_csv_robust(path, sep=delim, skiprows=header_idx + 1,
                             names=col_names, dtype=str,
                             keep_default_na=False, skip_blank_lines=True)
    except Exception:
        df = read_csv_robust(path, sep=delim, skiprows=header_idx + 1,
                             names=col_names, dtype=str,
                             keep_default_na=False, skip_blank_lines=True,
                             on_bad_lines='skip')

    # 丢弃空名 / 全空列
    keep = [c for c in df.columns
            if c and str(c).strip() and df[c].notna().any()]
    if keep:
        df = df[keep]
    df = df.replace('', np.nan)

    # 第一列通常为时间
    tcol = df.columns[0]
    df[tcol] = _pd_to_datetime(df[tcol], errors='coerce')
    df = df.dropna(subset=[tcol])
    df = df.set_index(tcol).sort_index()
    df.index.name = 't'

    channels = []
    rename_map = {}
    for col in df.columns:
        raw = str(col).strip()
        parsed = _parse_wra_colname(raw)
        if parsed is None:
            rename_map[col] = raw
            channels.append({'name': raw, 'kind': KIND_OTHER,
                             'height': None, 'units': '', 'role': '',
                             'orig': raw})
            continue
        base, h, orient, stat_raw, suffix, units = parsed
        canon = build_canon_name(base, h, orient, suffix)
        kind = {'Speed': KIND_SPEED, 'Dir': KIND_DIR, 'Temp': KIND_TEMP,
                'Pres': KIND_PRES, 'RH': KIND_RH, 'Wz': KIND_WZ,
                'Density': KIND_OTHER}.get(base, KIND_OTHER)
        rename_map[col] = canon
        channels.append({'name': canon, 'kind': kind, 'height': h,
                         'units': units, 'role': stat_raw if suffix.strip() else '',
                         'orig': raw})

    df = df.rename(columns=rename_map)
    # 数值化（与通用解析一致，便于统计与可用性计算）
    for col in df.columns:
        if col != df.index.name:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    device = detect_device_type(os.path.basename(path))

    meta = _finalize(path, df, device_type=device, lat=lat, lon=lon)
    meta.fmt = 'WRA标准化'
    meta.elevation = elevation
    if elevation is not None:
        meta.location = meta.location or ''
    meta.channels = channels
    meta.stats = _compute_stats(df, channels)
    meta.col_origins = dict(rename_map)   # 原始列名 → 规范名
    return meta


def _parse_windographer(path: str) -> ParsedData:
    """Windographer 标准文本导出（Created ... by Windographer 4.x）。

    文件结构：
      1-12 行：元数据（Created / Latitude / Longitude / Elevation / Calm threshold）
      13 行：制表符分隔的表头（Date/Time + Ch*_Anem/Vane/Analog_*）
      14+ 行：数据
    """
    lines = _read_lines_robust(path)
    header_idx = 12   # 第 13 行（0-based 索引 12）为表头
    if header_idx >= len(lines) or not lines[header_idx].strip():
        # 容错：自动定位首个含 'Date/Time' 或 'Timestamp' 的行
        for i, ln in enumerate(lines):
            if 'Date/Time' in ln or 'Timestamp' in ln:
                header_idx = i
                break
        else:
            raise ValueError('Windographer 文件未找到数据表头')

    # 提取元数据
    lat = lon = elevation = None
    calm = 0.0
    for ln in lines[:header_idx]:
        s = ln.strip()
        if s.startswith('Latitude'):
            lat = _parse_coord(s)
        elif s.startswith('Longitude'):
            lon = _parse_coord(s)
        elif s.startswith('Elevation'):
            elevation = _fnum(s.split('=', 1)[1].strip().split()[0])
        elif s.startswith('Calm threshold'):
            calm = _fnum(s.split('=', 1)[1].strip().split()[0]) or 0.0

    delim = _sniff_delimiter(path) or '\t'
    df = read_csv_robust(path, sep=delim, skiprows=header_idx,
                         dtype=str, keep_default_na=False,
                         skip_blank_lines=True, on_bad_lines='skip')

    # 丢弃空名 / 全空列
    keep = [c for c in df.columns
            if c and str(c).strip() and df[c].notna().any()]
    if keep:
        df = df[keep]
    df = df.replace('', np.nan)

    # 第一列为时间
    tcol = df.columns[0]
    df[tcol] = _pd_to_datetime(df[tcol], errors='coerce')
    df = df.dropna(subset=[tcol])
    df = df.set_index(tcol).sort_index()
    df.index.name = 't'

    channels = []
    rename_map = {}
    for col in df.columns:
        raw = str(col).strip()
        # 优先使用 Symphonie 风格正则（Ch*_Anem/Vane/Analog_...）
        m = _SYMPH_RE.match(raw)
        if m:
            type_map = {'Anem': 'Speed', 'Vane': 'Dir', 'Analog': None}
            base = type_map[m.group('type')]
            h = float(m.group('height'))
            orient = m.group('orient') or ''
            stat = _norm_role(m.group('stat'))
            # 单位从列名尾部 [unit] 或正则 unit 组提取
            units = (m.group('units') or '').strip()
            if not units:
                units = _extract_unit(raw)
            # 对 Analog 通道按单位推断类型
            if base is None:
                base, units = _infer_analog_type(units, raw)
            suffix = f' {stat}'
            canon = build_canon_name(base or 'Ch', h, orient, suffix)
            kind = {'Speed': KIND_SPEED, 'Dir': KIND_DIR, 'Temp': KIND_TEMP,
                    'Pres': KIND_PRES, 'RH': KIND_RH, 'Wz': KIND_WZ}.get(base, KIND_OTHER)
            rename_map[col] = canon
            channels.append({'name': canon, 'kind': kind, 'height': h,
                             'units': units, 'role': stat, 'orig': raw})
        else:
            # 兜底：通用语义解析
            canon, kind, h, units, role = _canon_generic(raw)
            rename_map[col] = canon
            channels.append({'name': canon, 'kind': kind, 'height': h,
                             'units': units, 'role': role, 'orig': raw})

    df = df.rename(columns=rename_map)
    for col in df.columns:
        if col != df.index.name:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    device = detect_device_type(os.path.basename(path))
    meta = _finalize(path, df, device_type=device, lat=lat, lon=lon)
    meta.fmt = 'Windographer'
    meta.elevation = elevation
    meta.calm_threshold = calm
    meta.channels = channels
    meta.stats = _compute_stats(df, channels)
    meta.col_origins = dict(rename_map)
    return meta


def _extract_unit(name: str) -> str:
    """从列名尾部的 [unit] 提取单位。"""
    m = re.search(r'\[([^\]]+)\]', name)
    return m.group(1).strip() if m else ''


def _infer_analog_type(units: str, raw: str) -> tuple[str, str]:
    """对 Analog 类通道按单位/列名推断物理类型。"""
    u = units.lower()
    low = raw.lower()
    if u in ('°c', 'c', 'deg c', 'degrees c', 'celsius') or '℃' in units:
        return 'Temp', units or '°C'
    if u in ('hpa', 'kpa', 'pa', 'mbar', 'mb') or 'baro' in low or 'press' in low:
        return 'Pres', units or 'hPa'
    if u in ('%', 'rh') or 'rh' in low or 'hum' in low:
        return 'RH', units or '%'
    return 'Ch', units


def canon_to_wra_name(name: str, kind: str = '', height=None,
                      role: str = '') -> str:
    """将规范通道名（空格风格 `Speed 10m NE Avg`，兼容旧下划线
    `Speed_10_NE`）还原为 WRA 标准化列名（`SPEED 10m NE AVG [m/s]`），
    供标准化导出使用。"""
    n = name.strip()
    orient = ''
    stat = ''
    base = n
    h = None
    # 1) 新空格风格：`Base [<h>m] [<orient>] <Stat>`
    parts = n.split()
    if len(parts) >= 2:
        base = parts[0]
        rest = parts[1:]
        i = 0
        if i < len(rest) and rest[i].endswith('m') and \
                rest[i][:-1].replace('.', '').isdigit():
            h = rest[i][:-1]
            i += 1
        if i < len(rest) and rest[i].upper() in (
                'N', 'E', 'S', 'W', 'NE', 'NW', 'SE', 'SW'):
            orient = rest[i].upper()
            i += 1
        if i < len(rest):
            stat = ' '.join(rest[i:])
    else:
        # 2) 旧下划线风格兜底：`Base_<h>[_<orient>][_<stat>]`
        om = re.match(r'^(.*)_(N|NE|E|SE|S|SW|W|NW)(?:_(.*))?$', n)
        if om:
            n = om.group(1)
            orient = om.group(2)
            stat = om.group(3) or ''
        hm = re.match(
            r'^(Speed|Dir|Temp|Pres|RH|Wz|SNR|Avail)_([\d.]+)(?:_(.*))?$', n)
        if hm:
            base, h = hm.group(1), hm.group(2)
            stat = hm.group(3) or '' if not stat else stat
        else:
            return name
    typ = {'Speed': 'SPEED', 'Dir': 'DIRECTION', 'Temp': 'TEMPERATURE',
           'Pres': 'PRESSURE', 'RH': 'RH', 'Wz': 'Wz', 'SNR': 'SNR',
           'Avail': 'AVAIL', 'SPEED': 'SPEED', 'DIRECTION': 'DIRECTION',
           'TEMPERATURE': 'TEMPERATURE', 'PRESSURE': 'PRESSURE',
           'AVAIL': 'AVAIL'}.get(base, base.upper())
    stat_map = {'': 'AVG', 'Avg': 'AVG', 'SD': 'SD', 'Min': 'MIN',
                'Max': 'MAX', 'Gust': 'GUST', 'AVG': 'AVG', 'MIN': 'MIN',
                'MAX': 'MAX', 'GUST': 'GUST'}
    stat_w = stat_map.get(stat, stat.upper() if stat else 'AVG')
    units_map = {'Speed': 'm/s', 'Dir': '°', 'Temp': '°C', 'Pres': 'kPa',
                 'RH': '%', 'Wz': 'm/s', 'SNR': 'dB', 'Avail': '%',
                 'SPEED': 'm/s', 'DIRECTION': '°', 'TEMPERATURE': '°C',
                 'PRESSURE': 'kPa', 'AVAIL': '%'}
    units = units_map.get(base, '')
    h_str = f'{h}m' if h else ''
    seg = [typ, h_str, orient, stat_w]
    return ' '.join(x for x in seg if x) + (f' [{units}]' if units else '')


# ----------------------------------------------------------------------
# 通用解析（CSV / 雷达 / 其它厂商）
# ----------------------------------------------------------------------
def _pd_to_datetime(arg, **kw):
    """抑制 pd.to_datetime 在未知格式列上抛出的格式推断 UserWarning，
    行为与 pd.to_datetime 一致（errors='coerce' 时仍照常返回 NaT）。"""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return pd.to_datetime(arg, **kw)


def _sniff_delimiter(path: str) -> str:
    counts = {'\t': 0, ',': 0, ';': 0}
    for i, ln in enumerate(_read_lines_robust(path)):
        if i > 200:
            break
        if not ln.strip() or ln.startswith('Created') or ln.startswith('Latitude'):
            continue
        for d in counts:
            counts[d] += ln.count(d)
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else None  # None → pandas 自动（含空白）


def _find_time_col(df: pd.DataFrame) -> str | None:
    best, best_rate = None, 0.0
    num_re = re.compile(r'^\s*-?\d+(\.\d+)?\s*$')
    for col in df.columns:
        if df[col].dtype.kind == 'O':   # object 字符串列才尝试解析时间
            head = df[col].astype(str).head(8)
            # 纯数字列不可能是时间戳，跳过（省去逐列 to_datetime 试探）
            sample = [t for t in head if str(t).strip() and str(t) != 'nan']
            if sample and all(num_re.match(str(t)) for t in sample):
                continue
            # 嗅探阶段仅解析前 200 行，禁用 to_datetime 的格式推断警告噪声
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                parsed = _pd_to_datetime(df[col].astype(str).head(200),
                                        errors='coerce')
            rate = parsed.notna().mean()
            if rate > best_rate:
                best, best_rate = col, rate
    return best if best_rate > 0.5 else None


def _parse_excel(path: str) -> ParsedData:
    """解析 Excel (.xls/.xlsx)：先读为 DataFrame，再走通用清理/列名语义流程。"""
    # pandas 自动根据扩展名选择 openpyxl / xlrd
    df = pd.read_excel(path, dtype=str, keep_default_na=False)
    df = df.replace('', np.nan)

    # 定位时间列；找不到则默认第一列
    tcol = _find_time_col(df)
    if tcol is None:
        tcol = df.columns[0]

    # 转为时间索引并移除原列
    df[tcol] = _pd_to_datetime(df[tcol], errors='coerce')
    df = df.dropna(subset=[tcol])
    df = df.set_index(tcol).sort_index()
    df.index.name = 't'

    numeric = []
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col].dtype) or \
                df[col].dtype.kind in ('O', 'U', 'S'):
            df[col] = pd.to_numeric(df[col], errors='coerce')
        if pd.api.types.is_numeric_dtype(df[col]):
            numeric.append(col)

    channels = []
    rename_map = {}
    for col in numeric:
        raw = str(col)
        canon, kind, height, units, role = _canon_generic(raw)
        rename_map[col] = canon
        channels.append({'name': canon, 'kind': kind, 'height': height,
                         'units': units, 'role': role, 'orig': raw})
    df = df.rename(columns=rename_map)

    device = detect_device_type(os.path.basename(path))
    meta = _finalize(path, df, device_type=device)
    meta.fmt = 'Excel'
    meta.channels = channels
    meta.stats = _compute_stats(df, channels)
    meta.col_origins = dict(rename_map)
    return meta


def _parse_generic(path: str) -> ParsedData:
    delim = _sniff_delimiter(path)
    df = read_csv_robust(path, sep=delim, skip_blank_lines=True,
                         dtype=str, keep_default_na=False)
    df = df.replace('', np.nan)

    tcol = _find_time_col(df)
    if tcol is not None:
        df[tcol] = _pd_to_datetime(df[tcol], errors='coerce')
        df = df.dropna(subset=[tcol])
        df = df.set_index(tcol).sort_index()
        df.index.name = 't'

    # 数值列（兼容 object 与 pandas 新版 StringDtype）
    numeric = []
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col].dtype) or \
                df[col].dtype.kind in ('O', 'U', 'S'):
            df[col] = pd.to_numeric(df[col], errors='coerce')
        if pd.api.types.is_numeric_dtype(df[col]):
            numeric.append(col)

    channels = []
    rename_map = {}
    for col in numeric:
        raw = str(col)
        canon, kind, height, units, role = _canon_generic(raw)
        rename_map[col] = canon
        channels.append({'name': canon, 'kind': kind, 'height': height,
                         'units': units, 'role': role, 'orig': raw})
    df = df.rename(columns=rename_map)

    device = detect_device_type(os.path.basename(path))
    meta = _finalize(path, df, device_type=device)
    meta.fmt = '通用/CSV'
    meta.channels = channels
    meta.stats = _compute_stats(df, channels)
    meta.col_origins = dict(rename_map)   # 原始列名 → 规范名
    return meta


def _infer_kind(name: str):
    hm = _HEIGHT_RE.search(name)
    height = float(hm.group(1)) if hm else None
    low = name.lower()
    if _DIR_RE.search(name):
        return KIND_DIR, height, 'Deg'
    if _RH_RE.search(name):
        return KIND_RH, height, '%'
    if _PRES_RE.search(name):
        return KIND_PRES, height, 'hPa'
    if _TEMP_RE.search(name):
        return KIND_TEMP, height, '℃'
    if _SPEED_RE.search(name):
        return KIND_SPEED, height, 'm/s'
    return KIND_OTHER, height, ''


def _canon_generic(name: str):
    """通用解析的规范名：从杂乱列名提取 类型/高度/方位/统计 → 统一规范名。

    例：`150m_wind_sd` → Speed_150_SD；`风速最小值_NE_120` → Speed_120_NE_Min
    高度识别兼容 `150m` / `_120` / `120` 多种形式；方位与统计词互不冲突。
    """
    low = name.lower()
    # 1) 类型（带词边界，避免 'wind' 误匹配 'winddir'）
    base = None
    for kw, b in (('风向', 'Dir'), ('winddirection', 'Dir'),
                  ('winddirect', 'Dir'), ('winddir', 'Dir'), ('direction', 'Dir'),
                  ('direct', 'Dir'), ('wd', 'Dir'), ('vane', 'Dir'), ('dir', 'Dir'),
                  ('风速', 'Speed'), ('windspeed', 'Speed'), ('anem', 'Speed'),
                  ('speed', 'Speed'), ('spd', 'Speed'), ('ws', 'Speed'),
                  ('wind', 'Speed'),
                  ('气温', 'Temp'), ('温度', 'Temp'), ('temperature', 'Temp'),
                  ('temp', 'Temp'), ('t_', 'Temp'),
                  ('气压', 'Pres'), ('baro', 'Pres'), ('pressure', 'Pres'),
                  ('bp', 'Pres'), ('pres', 'Pres'), ('p_', 'Pres'), ('press', 'Pres'),
                  ('湿度', 'RH'), ('rh', 'RH'), ('hum', 'RH')):
        pat = re.escape(kw)
        if re.search(rf'(?<![a-z]){pat}(?![a-z])', low):
            base = b
            break
    if base is None:
        base = 'Ch'
    # 1b) 对未知类型，按显式单位 [°C]/[hPa]/[%] 辅助推断
    explicit_unit = _extract_unit(name)
    if base == 'Ch' and explicit_unit:
        u = explicit_unit.lower()
        if u in ('°c', 'c', 'deg c', 'degrees c', 'celsius') or '℃' in explicit_unit:
            base = 'Temp'
        elif u in ('hpa', 'kpa', 'pa', 'mbar', 'mb'):
            base = 'Pres'
        elif u in ('%', 'rh'):
            base = 'RH'
    # 2) 统计词（先于高度，避免数字被误判）
    stat_tok = ''
    _STAT_TOKENS = ['平均值', '平均', '标准差', '偏差', '阵风',
                    '最小值', '最小', '最大值', '最大',
                    'avg', 'average', 'mean', 'aver', 'sd', 'std', 'stdev',
                    'sigma', 'σ', 'min', 'minimum', 'minim', 'max',
                    'maximum', 'gust', 'gusts']
    for tok in _STAT_TOKENS:
        if re.search(rf'(?<![A-Za-z]){re.escape(tok)}(?![A-Za-z])', low):
            stat_tok = tok
            break
    # 3) 方位（独立字母，前后非字母）
    orient = ''
    for o in ('NE', 'NW', 'SE', 'SW', 'N', 'E', 'S', 'W'):
        if re.search(rf'(?<![A-Za-z]){o}(?![A-Za-z])', name):
            orient = o
            break
    # 4) 高度：优先 `数字m/米`，否则取列名中独立的数字 token（排除已识别的
    #    方位/统计词），取最大的一个作为高度
    height = None
    hm = _HEIGHT_RE.search(name)
    if hm:
        height = float(hm.group(1))
    else:
        # 提取所有独立数字段
        cands = re.findall(r'(?<!\d)(\d+(?:\.\d+)?)(?!\d)', name)
        # 排除与方位/统计词紧邻的数字（如 RH_5_min 中的 5 是高度，应保留）
        # 简单策略：取第一个数字当作高度（多数厂商列名高度为显著数字）
        if cands:
            # 若该数字与方位相邻（如 _120_NE 中的 120）→ 取之
            for num in cands:
                if re.search(rf'{re.escape(num)}\s*[_]?\s*(?:NE|NW|SE|SW|N|E|S|W)'
                             rf'|(?:NE|NW|SE|SW|N|E|S|W)\s*[_]?\s*{re.escape(num)}',
                             name, re.I):
                    height = float(num)
                    break
            if height is None and len(cands) == 1:
                height = float(cands[0])
    # 5) 构造
    suffix = _norm_stat_suffix(stat_tok)
    units = explicit_unit or {'Speed': 'm/s', 'Dir': 'Deg', 'Temp': '℃',
                              'Pres': 'hPa', 'RH': '%', 'Wz': 'm/s'}.get(base, '')
    kind = {'Speed': KIND_SPEED, 'Dir': KIND_DIR, 'Temp': KIND_TEMP,
            'Pres': KIND_PRES, 'RH': KIND_RH, 'Wz': KIND_WZ}.get(base, KIND_OTHER)
    canon = build_canon_name(base, height, orient, suffix)
    # 角色必须返回规范值（Avg/SD/Min/Max/Gust），不能返回原始 token
    return canon, kind, height, units, _norm_role(stat_tok)


# ----------------------------------------------------------------------
# 公共：收尾与统计
# ----------------------------------------------------------------------
def _finalize(path, df, device_type='未知', station_no='', location='',
              lat=None, lon=None, elevation=None) -> ParsedData:
    # 确保索引为时间类型（防御 object 退化）
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = _pd_to_datetime(df.index, errors='coerce')
        df = df[~df.index.isna()]
        df.index.name = 't'
    n = len(df)
    t0 = df.index.min()
    t1 = df.index.max()
    dt = _infer_dt(df)
    span_min = 0
    if isinstance(df.index, pd.DatetimeIndex) and t0 is not None and \
            t1 is not None and pd.notna(t0) and pd.notna(t1):
        span_min = (t1 - t0).total_seconds() / 60.0
    n_expected = int(round(span_min / dt)) + 1 if span_min > 0 else n
    completeness = (n / n_expected) if n_expected > 0 else 0.0
    completeness = min(completeness, 1.0)

    # 雷达特有：数据有效率 = 风速通道平均有效率
    data_avail = _overall_availability(df)

    return ParsedData(
        path=path,
        device_type=device_type,
        station_no=station_no,
        location=location,
        lat=lat, lon=lon, elevation=elevation,
        t_start='' if t0 is None or pd.isna(t0) else t0.strftime('%Y-%m-%d'),
        t_end='' if t1 is None or pd.isna(t1) else t1.strftime('%Y-%m-%d'),
        dt_min=dt,
        n_rows=n,
        n_expected=n_expected,
        completeness=round(completeness * 100, 2),
        data_availability=round(data_avail * 100, 2),
        df=df,
    )


def _infer_dt(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 10.0
    diffs = df.index.to_series().diff().dropna()
    if diffs.empty:
        return 10.0
    med = diffs.median()
    # median 可能为 Timedelta 或（退化时）数值
    if hasattr(med, 'total_seconds'):
        secs = med.total_seconds()
    else:
        secs = float(med) / 1e9 if abs(med) > 1e12 else float(med)
    return secs / 60.0 if secs and secs > 0 else 10.0


# ----------------------------------------------------------------------
# 用数值统计复核 / 补全识别结果
# ----------------------------------------------------------------------
# 名称识别有两类漏网：
#   a) 列名完全没有统计标记（Ch1/Ch2/Ch3 之类）→ Subtype 全落默认 Avg；
#   b) 列名不含类型关键词 → 类别落到 other。
# 这两类都能用数据本身的统计特征（均值/最小/最大/单位）补回来。
_STAT_MARKER_RE = re.compile(
    r'(?<![A-Za-z])(avg|average|mean|aver|sd|std|stdev|stddev|sigma|σ|'
    r'min|minimum|minim|max|maximum|gust|gusts|'
    r'平均|平均值|标准差|偏差|最小|最小值|最大|最大值|阵风)(?![A-Za-z])',
    re.I)


def _has_stat_marker(name: str) -> bool:
    """列名里是否自带统计特征词（Avg/SD/Min/Max/Gust 等）。"""
    return bool(_STAT_MARKER_RE.search(str(name or '')))


def _infer_kind_by_values(vmin: float, vmax: float, vmean: float,
                          units: str = '') -> str:
    """按单位 + 数值区间推断通道类别；不确定时返回 ''。

    仅在名称识别不出（other）或与数值明显矛盾时调用，避免误改正确结果。
    """
    u = (units or '').strip().lower()
    # 1) 单位强判定
    if '%' in u or 'rh' in u:
        return KIND_RH
    if 'hpa' in u or 'kpa' in u or 'mbar' in u:
        return KIND_PRES
    if '℃' in u or '°c' in u or u in ('c', 'deg c', 'celsius'):
        return KIND_TEMP
    if '°' in u or 'deg' in u:
        return KIND_DIR
    if 'm/s' in u or u in ('ms', 'mps'):
        return KIND_SPEED
    # 2) 数值区间（风速不可能为负，气压量级远大于其余量）
    if vmin >= 500 and vmax <= 1100:            # hPa
        return KIND_PRES
    if vmin >= 40 and vmax <= 110 and vmean > 55:   # kPa
        return KIND_PRES
    if vmin < -5 and vmax <= 60:                # 负值只可能是气温
        return KIND_TEMP
    if vmin >= 0 and vmax <= 360 and vmax > 180:
        return KIND_DIR
    if vmin >= 0 and vmax <= 100 and vmean > 30:
        return KIND_RH
    if vmin >= 0 and vmax <= 60:
        return KIND_SPEED
    return ''


def _refine_by_stats(df: pd.DataFrame, channels: list):
    """用数值统计复核/补全通道的类别(Type)与子类型(Subtype)。原地修改。"""
    if df is None or df.empty or not channels:
        return channels

    # ---- 1) 类别：other 或与数值明显矛盾时，按区间/单位重判 ----
    for ch in channels:
        col = ch.get('name')
        if col not in df.columns:
            continue
        s = _as_num(df[col]).dropna()
        if s.empty:
            continue
        vmin, vmax, vmean = float(s.min()), float(s.max()), float(s.mean())
        cur = ch.get('kind', KIND_OTHER)
        need = (cur == KIND_OTHER)
        # 明显矛盾：风速却出现 >80 的值 / 湿度出现 >100 / 气温出现 >100
        if not need:
            if cur == KIND_SPEED and vmax > 80:
                need = True
            elif cur == KIND_RH and vmax > 100:
                need = True
            elif cur == KIND_TEMP and vmax > 100:
                need = True
            elif cur == KIND_PRES and vmax > 1200:
                need = True
        if not need:
            continue
        new_kind = _infer_kind_by_values(vmin, vmax, vmean, ch.get('units', ''))
        if new_kind and new_kind != cur:
            ch['kind'] = new_kind

    # ---- 2) 子类型：同组内名称都无统计标记时，按均值排序推断 ----
    groups: dict = {}
    for ch in channels:
        if ch.get('name') not in df.columns:
            continue
        # 名称自带标记的不动，只处理「裸名」通道
        if _has_stat_marker(ch.get('orig', '') or ch.get('name', '')):
            continue
        if _has_stat_marker(ch.get('name', '')):
            continue
        key = (ch.get('kind'), ch.get('height'), _canon_orient(ch.get('name', '')))
        groups.setdefault(key, []).append(ch)

    for members in groups.values():
        if not (2 <= len(members) <= 4):
            continue
        vals = []
        for ch in members:
            s = _as_num(df[ch['name']]).dropna()
            vals.append(float(s.mean()) if len(s) else float('nan'))
        order = sorted(range(len(members)), key=lambda i: vals[i])
        # 单列标准差：均值明显小于同组其它列且非负 → SD
        means = sorted(v for v in vals if v == v)
        if len(means) >= 2 and means[0] >= 0 and means[0] < means[-1] * 0.35:
            sd_i = order[0]
            members[sd_i]['role'] = 'SD'
            order = [i for i in order if i != sd_i]
        if len(order) >= 3:
            members[order[0]]['role'] = 'Min'
            members[order[-1]]['role'] = 'Max'
            for i in order[1:-1]:
                members[i]['role'] = 'Avg'
        elif len(order) == 2:
            members[order[0]]['role'] = 'Min'
            members[order[1]]['role'] = 'Max'
    return channels


def _canon_orient(name: str) -> str:
    """从规范名里取方位段，用于分组。"""
    for tok in str(name or '').split():
        if tok in ('NE', 'NW', 'SE', 'SW', 'N', 'E', 'S', 'W'):
            return tok
    return ''


def _compute_stats(df: pd.DataFrame, channels: list) -> list:
    out = []
    primary = [c for c in channels if c['kind'] in (
        KIND_SPEED, KIND_DIR, KIND_TEMP, KIND_PRES, KIND_RH)
        and c['role'] in ('', 'Avg')]
    if not primary:
        primary = channels
    for c in primary:
        col = c['name']
        if col not in df.columns:
            continue
        s = _as_num(df[col])
        n = len(s)
        valid = int(s.notna().sum())
        avail = valid / n if n else 0.0
        out.append({
            'name': col, 'kind': c['kind'], 'height': c['height'],
            'units': c['units'],
            'mean': round(float(s.mean()), 4) if valid else None,
            'std': round(float(s.std()), 4) if valid > 1 else None,
            'min': round(float(s.min()), 4) if valid else None,
            'max': round(float(s.max()), 4) if valid else None,
            'availability': round(avail * 100, 2),
        })
    return out


def _overall_availability(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    nums = df.select_dtypes(include=[np.number])
    if nums.empty:
        return 0.0
    rates = nums.notna().mean()
    return float(rates.mean())


def _fnum(s: str):
    try:
        return float(s)
    except Exception:
        return float('nan')


# ---------------------------------------------------------------------------
# 解析器注册区（S3：新增专用格式在此登记，注册顺序 = 兜底探测优先级）
# ---------------------------------------------------------------------------
def _match_symphonie(path: str, head: str) -> bool:
    return 'SymphoniePRO' in head or 'NRG Systems' in head


def _match_windographer(path: str, head: str) -> bool:
    return path.lower().endswith('.rwd') or 'Windographer' in head


def _match_molas(path: str, head: str) -> bool:
    return (('ID System=' in head and 'Range Gate' in head)
            or 'Molas' in head)


def _match_wra_standard(path: str, head: str) -> bool:
    return ('Elevation' in head
            and ('SPEED' in head or 'Speed' in head or 'speed' in head))


register_parser('NRG Symphonie', _match_symphonie)(_parse_symphonie)
register_parser('Windographer 文本', _match_windographer)(_parse_windographer)
register_parser('Molas 雷达', _match_molas)(_parse_molas)
register_parser('WRA 标准列名', _match_wra_standard)(_parse_wra_standard)
