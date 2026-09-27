"""软件设置：JSON 持久化（data/settings.json）+ 自启动注册表。

所有设置集中管理，便于菜单「设置」统一读写，亦供主窗口恢复几何尺寸。
零新增依赖：标准库 json / os；自启动写 HKCU Run（无需管理员）。
"""

import json
import os
import sys

from core.paths import app_dir

_BASE = app_dir()
_PATH = os.path.join(_BASE, 'data', 'settings.json')

# WindAnaly 快捷工具栏默认布局（app_analysis._refresh_toolbar 引用；
# 旧默认 ['new_window', 'open', 'append', 'save'] 会自动迁移到该布局）
QUICK_TOOLBAR_DEFAULT = [
    'new', 'open', 'append', 'save',
    'sep',
    'data_coverage', 'doc_history', 'configure_dataset', 'vertical_extrap',
    'calibration',
    'sep',
    'flag_manual', 'flag_scatter', 'flag_rule', 'flag_tower_shadow',
    'flag_inspect',
    'sep',
    'data_recovery', 'turbulence', 'wind_shear_analysis', 'wind_speed_dist',
    'tower_distortion', 'inflow_angle', 'turbine_output',
    'short_time_interval',
    'about',
]

_DEFAULTS = {
    'autostart': False,          # 开机自启动
    'auto_update_check': True,   # 启动后后台静默检查更新
    'remember_window_size': True,  # 记住并恢复窗口尺寸
    'geometry': '',              # base64 字节串，由 QByteArray.toByteArray()
    'default_import_mode': 'internal',  # 导入默认存储模式 internal/external
    'font_size': 9,              # 界面字体大小（pt）
    'ledger_col_widths': {},     # 台账列宽记忆（列名→宽度）
    # 快捷工具栏默认按钮（2026-09-03 扩充：关联全部常用动作）
    'analy_toolbar': list(QUICK_TOOLBAR_DEFAULT),
    'analy_recent_files': [],  # 最近文件/项目记录（最多 3 条）
    # 「视图 → 首页展示」勾选的 Tab（报告默认不展示）
    'analy_tabs_visible': [
        'Summary', 'Time Series', 'Wind Rose', 'Diurnal', 'Histogram',
        'Scatter Plot', 'Data Table',
    ],
    # 界面语言：'zh' 中文，'en' 英文
    'language': 'zh',
    # 英文底座 -> 中文翻译
    'translations': {},
    # 英文底座 -> 英文修正（可在展示英文时使用）
    'english_corrections': {},
    # 展示英文时是否优先使用 english_corrections
    'use_english_correction': False,
    # ------------------------------------------------------------------
    # 风玫瑰（首页）默认样式模板 —— 仅作「软件默认」，不随项目变化。
    # 项目内实际生效值存在 Project.plot_settings['wind_rose']；
    # 项目无配置时以此深拷贝为初值。修改入口在玫瑰图 Properties 对话框的
    # 「Save as Default」，而不是设置菜单（设置菜单只保留 Language 单一入口）。
    # ------------------------------------------------------------------
    'wind_rose_defaults': {
        # Axes
        'title': '风向玫瑰图',             # 图标题
        'radial_label': '',              # 径向轴标签
        'sectors': 16,                   # 默认扇区数
        'fix_min_max': False,            # 固定径向最小/最大值
        'radial_min': 0.0,               # 固定最小值
        'radial_max': 100.0,             # 固定最大值
        'label_angular': True,           # 显示角度轴标签
        'inner_circle_pct': 0.0,         # 内圆（静风）半径占外圈百分比
        'fill_factor': 0.85,             # 玫瑰占绘图区比例(0~1)
        'show_legend': True,             # 显示图例
        # Fonts
        'title_font': 11,
        'label_font': 9,
        'legend_font': 8,
        # Channels：列表，索引对应系列顺序；缺失字段用 CHANNEL_STYLE_DEFAULTS
        'channel_styles': [],
    },
}

# 单个通道的样式缺省（风玫瑰 Channels 页逐通道覆盖）
CHANNEL_STYLE_DEFAULTS = {
    'visible': True,          # 是否绘制该通道
    'color': '',              # 空串=自动取调色板
    'border': False,          # 画轮廓线
    'rose_style': 'filled_line',  # filled_line / filled / line / bar
    'line_width': 2,          # 线宽
    'line_style': 'solid',    # solid / dash / dot / dash_dot
    'marker': 'none',         # none / circle / square / diamond / triangle / cross / x
    'marker_size': 5,         # 标记尺寸
    'fill_alpha': 45,         # 填充透明度
    'label': '',              # 图例文字，空=用通道名
    # Display settings（Windographer Channels 页底部，逐通道）
    'show_in_legend': True,   # 是否出现在图例
    'show_values': False,     # 在扇区上标注数值
    'show_error_bars': False, # 画线时显示误差棒
}


# 旧版设置键 → 新键（windrefine_* → analy_*，S1 收敛）。
# 读旧写新、幂等：仅当文件里只有旧键（用户尚未写过新键）时采用旧值，
# 文件里已显式写了新键则新值优先；旧键在下次写设置时从文件清除。
# 注意不能拿 _DEFAULTS 判断「新键是否已设置」——默认值恒存在。
_KEY_MIGRATE = {
    'windrefine_toolbar': 'analy_toolbar',
    'windrefine_tabs_visible': 'analy_tabs_visible',
    'windrefine_recent_files': 'analy_recent_files',
}


def _load() -> dict:
    file_data = {}
    if os.path.exists(_PATH):
        try:
            with open(_PATH, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                file_data = loaded
        except Exception:
            file_data = {}
    data = {**_DEFAULTS, **file_data}
    for old, new in _KEY_MIGRATE.items():
        if old in file_data:
            if new not in file_data:
                data[new] = file_data[old]
            data.pop(old, None)
    return data


def _save(data: dict):
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    with open(_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get(key: str, default=None):
    return _load().get(key, default)


def set(key: str, value):
    data = _load()
    data[key] = value
    _save(data)


def get_all() -> dict:
    return _load()


def update(**kw):
    data = _load()
    data.update(kw)
    _save(data)


# ----------------------------------------------------------------------
# 风玫瑰「软件默认」读写
# ----------------------------------------------------------------------
def get_wind_rose_defaults() -> dict:
    """返回风玫瑰软件默认配置。

    与内置缺省逐键合并，避免旧版 settings.json 缺少后加的键时 KeyError。
    顶层字典做深拷贝，防止调用方就地修改污染 _DEFAULTS。
    """
    import copy
    base = copy.deepcopy(_DEFAULTS.get('wind_rose_defaults', {}))
    stored = get('wind_rose_defaults') or {}
    if not isinstance(stored, dict):
        return base
    base.update(copy.deepcopy(stored))
    # channel_styles 是列表，逐元素补缺省键
    merged_styles = []
    for st in (base.get('channel_styles') or []):
        item = dict(CHANNEL_STYLE_DEFAULTS)
        if isinstance(st, dict):
            item.update(st)
        merged_styles.append(item)
    base['channel_styles'] = merged_styles
    return base


def set_wind_rose_defaults(cfg: dict):
    """把 cfg 写入软件默认（供玫瑰图 Properties「Save as Default」调用）。"""
    import copy
    update(wind_rose_defaults=copy.deepcopy(dict(cfg or {})))


def get_channel_style(cfg: dict, index_or_name) -> dict:
    """取某通道的样式，缺失字段用 CHANNEL_STYLE_DEFAULTS 补齐。

    channel_styles 在新版中为列表（按系列顺序），兼容旧版字典。
    """
    item = dict(CHANNEL_STYLE_DEFAULTS)
    styles = (cfg or {}).get('channel_styles') or {}
    st = None
    if isinstance(styles, dict):
        st = styles.get(index_or_name)
    elif isinstance(styles, list) and isinstance(index_or_name, int):
        if 0 <= index_or_name < len(styles):
            st = styles[index_or_name]
    if isinstance(st, dict):
        item.update(st)
    return item


# ----------------------------------------------------------------------
# 自启动（HKCU\Software\Microsoft\Windows\CurrentVersion\Run）
# ----------------------------------------------------------------------
def _run_command() -> str:
    """拼出自启动命令：打包后指向可执行文件，否则指向 python main.py。"""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    main_py = os.path.join(_BASE, 'windanaly.py')
    exe = sys.executable
    return f'"{exe}" "{main_py}"'


def _reg_key():
    import winreg
    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r'Software\Microsoft\Windows\CurrentVersion\Run',
        access=winreg.KEY_SET_VALUE)


def apply_autostart(enabled: bool) -> bool:
    """写/删 Run 项。返回是否成功（非 Windows 或权限不足时 False）。"""
    try:
        import winreg
        with _reg_key() as key:
            if enabled:
                winreg.SetValueEx(key, 'WindAnaly', 0,
                                  winreg.REG_SZ, _run_command())
            else:
                try:
                    winreg.DeleteValue(key, 'WindAnaly')
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def apply_font_size(app=None):
    """按设置应用全局字体大小（QApplication.setFont）。"""
    try:
        from PySide6.QtGui import QFont
        if app is None:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
        if app is None:
            return
        f = QFont(app.font().family(), int(get('font_size', 9)))
        app.setFont(f)
    except Exception:
        pass


def db_path() -> str:
    """总数据库 windkit.db 的绝对路径。"""
    from core.library import Library
    return Library().db_path


def restore_geometry(window) -> bool:
    """若开启记住尺寸，恢复窗口几何。window 需有 restoreGeometry(QByteArray)。"""
    if not get('remember_window_size'):
        return False
    raw = get('geometry')
    if raw:
        try:
            from PySide6.QtCore import QByteArray
            window.restoreGeometry(QByteArray.fromBase64(
                raw.encode('latin-1')))
            return True
        except Exception:
            pass
    return False


def save_geometry(window):
    if not get('remember_window_size'):
        return
    try:
        update(geometry=window.saveGeometry().toBase64().data().decode(
            'latin-1'))
    except Exception:
        pass
