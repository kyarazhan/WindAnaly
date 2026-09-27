"""数据文件装载纯函数：厂商格式常量、文件过滤器、目录扫描、多文件合并。
从 app.py 拆出（S2）；无 Qt 依赖，供 LoaderMixin 与测试复用。
"""
import os

import numpy as np
import pandas as pd
# ---------------------------------------------------------------------------
# 各厂商后缀 → 说明
_EXT_WIND = ('.windog', '.rwd', '.ndf', '.txt', '.csv', '.xls', '.xlsx',
             '.rld', '.nsd', '.zph', '.sta', '.wnd', '.dat', '.tsv')
_EXT_WINDOGRAPHER = ('.windog',)
_EXT_SYMPHONIE = ('.rwd', '.nsd')
_EXT_SYMPHONIE_PRO = ('.rld',)
_EXT_NOMAD2 = ('.ndf',)
_EXT_ZEPHIR = ('.csv', '.zph')
_EXT_WINDCUBE = ('.sta',)
_EXT_KINTECH = ('.wnd',)
_EXT_TEXT = ('.txt', '.tsv', '.dat')
_EXT_EXCEL = ('.xls', '.xlsx')
_EXT_CSV = ('.csv',)

# 递归扫描目录时接受的全部后缀（覆盖上面所有厂商格式）
_SCAN_EXTS = tuple(sorted(set(
    _EXT_WIND + _EXT_SYMPHONIE + _EXT_SYMPHONIE_PRO + _EXT_NOMAD2
    + _EXT_ZEPHIR + _EXT_WINDCUBE + _EXT_KINTECH + _EXT_TEXT
    + _EXT_EXCEL + _EXT_CSV + _EXT_WINDOGRAPHER)))


def _ext_filter(name: str, exts) -> str:
    """构造 '说明 (*.a *.b)' 形式的 Qt 文件过滤器。"""
    return f'{name} ({" ".join("*" + e for e in exts)})'


# 项目文件优先，其后按原版顺序列出各厂商格式
FILE_OPEN_FILTER = ';;'.join([
    'WindAnaly 项目 (*.windanaly *.windrefine)',
    _ext_filter('Wind Data Files', _EXT_WIND),
    _ext_filter('Windographer Files', _EXT_WINDOGRAPHER),
    _ext_filter('Symphonie Data Logger Files', _EXT_SYMPHONIE),
    _ext_filter('SymphoniePRO Files', _EXT_SYMPHONIE_PRO),
    _ext_filter('Nomad2 Data Files', _EXT_NOMAD2),
    _ext_filter('ZephIR Data Files', _EXT_ZEPHIR),
    _ext_filter('Windcube Statistics Files', _EXT_WINDCUBE),
    _ext_filter('Kintech Engineering Data Files', _EXT_KINTECH),
    _ext_filter('Text Files', _EXT_TEXT),
    _ext_filter('CSV Files', _EXT_CSV),
    _ext_filter('Excel Files', _EXT_EXCEL),
    'All Files (*.*)',
])


def merge_frames(base_df: pd.DataFrame | None, new_df: pd.DataFrame) -> pd.DataFrame:
    """时间轴拼接 + 同名列覆盖，用于「增加」语义。

    - 已存在的时间戳：用新数据按列覆盖（NaN 不覆盖，避免把有效值抹掉）；
    - 新出现的时间戳：整行追加；
    - 新出现的通道列：在旧数据上补 NaN 后填充。
    结果按时间排序。
    """
    if base_df is None or base_df.empty:
        return new_df.sort_index()
    df = base_df.copy()
    if new_df is None or new_df.empty:
        return df.sort_index()
    # 新增列先以 NaN 补齐，保持列对齐
    for c in new_df.columns:
        if c not in df.columns:
            df[c] = np.nan
    # 同索引位置用新值覆盖（update 只写非 NA，逐列对齐）
    df.update(new_df)
    # 追加旧数据里没有的时间戳
    extra = new_df.index.difference(df.index)
    if len(extra):
        df = pd.concat([df, new_df.loc[extra]], axis=0)
    return df.sort_index()


def scan_data_files(folder: str, recursive: bool = True) -> list[str]:
    """递归收集目录下所有支持的数据文件（含 n 级子目录）。"""
    out: list[str] = []
    if not folder or not os.path.isdir(folder):
        return out
    if recursive:
        for root, _dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(_SCAN_EXTS):
                    out.append(os.path.join(root, f))
    else:
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if os.path.isfile(p) and f.lower().endswith(_SCAN_EXTS):
                out.append(p)
    return sorted(out)
