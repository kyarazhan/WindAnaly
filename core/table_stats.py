"""Tables 标签页的统计聚合（纯计算，无 UI）。

全部函数接收 Series/DataFrame 并返回 DataFrame/ndarray，由
tables_widget 按表型取用并格式化。统计口径：
- Occurrences = 非缺测样本数（count）；
- Mean/Min/Max/Std. Dev. 基于非缺测值，std 为样本标准差（ddof=1）；
- 缺组返回 NaN。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _stats(s: pd.Series) -> dict:
    """单组四项统计：count/mean/min/max/std（全缺测时为 NaN）。"""
    s = pd.to_numeric(s, errors='coerce').dropna()
    if s.empty:
        return {'count': 0, 'mean': np.nan, 'min': np.nan,
                'max': np.nan, 'std': np.nan}
    return {'count': int(s.size), 'mean': float(s.mean()),
            'min': float(s.min()), 'max': float(s.max()),
            'std': float(s.std(ddof=1)) if s.size > 1 else np.nan}


def _numeric(df: pd.DataFrame, col: str, mask=None) -> pd.Series:
    s = pd.to_numeric(df[col], errors='coerce')
    if mask is not None:
        s = s[pd.Series(mask, index=df.index).fillna(False).astype(bool)]
    return s


def by_month_stats(df: pd.DataFrame, col: str,
                   mask=None, with_all: bool = False) -> pd.DataFrame:
    """按月统计：索引 1..12（with_all 时追加 'All' 行），列 count/mean/min/max/std。"""
    s = _numeric(df, col, mask)
    g = s.groupby(s.index.month)
    out = g.agg(count='count', mean='mean', min='min', max='max',
                std=lambda x: x.std(ddof=1) if len(x) > 1 else np.nan)
    out = out.reindex(range(1, 13))
    out['count'] = out['count'].fillna(0)
    if with_all:
        st = _stats(s)
        all_row = pd.DataFrame({'count': [st['count']],
                                'mean': [st['mean']], 'min': [st['min']],
                                'max': [st['max']], 'std': [st['std']]},
                               index=['All'])
        out = pd.concat([out, all_row])
        out['count'] = out['count'].fillna(0)
    return out


def by_year_stats(df: pd.DataFrame, col: str,
                  mask=None, with_all: bool = False) -> pd.DataFrame:
    """按年统计：索引为年份升序（with_all 时追加 'All' 行）。"""
    s = _numeric(df, col, mask)
    g = s.groupby(s.index.year)
    out = g.agg(count='count', mean='mean', min='min', max='max',
                std=lambda x: x.std(ddof=1) if len(x) > 1 else np.nan)
    out['count'] = out['count'].fillna(0)
    if with_all:
        st = _stats(s)
        all_row = pd.DataFrame({'count': [st['count']],
                                'mean': [st['mean']], 'min': [st['min']],
                                'max': [st['max']], 'std': [st['std']]},
                               index=['All'])
        out = pd.concat([out, all_row])
        out['count'] = out['count'].fillna(0)
    return out


def _margins(s: pd.Series, row_key, col_key, agg: str):
    """All 行/列/角值：在全量数据上按 agg 语义计算（非单元格二次聚合）。

    返回 (row_all, col_all, corner)，索引/列对齐调用方矩阵。"""
    if agg == 'count':
        row_all = s.groupby(row_key).count()
        col_all = s.groupby(col_key).count()
        corner = float(len(s))
    elif agg == 'std':
        row_all = s.groupby(row_key).std(ddof=1)
        col_all = s.groupby(col_key).std(ddof=1)
        corner = s.std(ddof=1)
    else:
        fn = {'mean': 'mean', 'min': 'min', 'max': 'max'}[agg]
        row_all = s.groupby(row_key).agg(fn)
        col_all = s.groupby(col_key).agg(fn)
        corner = getattr(s, fn)()
    return row_all, col_all, corner


def month_hour_matrix(df: pd.DataFrame, col: str, agg: str = 'count',
                      mask=None, with_all: bool = False) -> pd.DataFrame:
    """月 × 时矩阵：行 1..12 月，列 0..23 时。

    agg ∈ 'count' / 'mean' / 'min' / 'max' / 'std'；
    with_all=True 时末行/末列为 All 汇总（原版样式）。"""
    s = _numeric(df, col, mask)
    months = list(range(1, 13))
    hours = list(range(24))
    if s.empty:
        return pd.DataFrame(np.nan, index=months, columns=hours)
    if agg == 'count':
        piv = pd.crosstab(s.index.month, s.index.hour) \
            .reindex(index=months, columns=hours, fill_value=0)
    else:
        fn = {'mean': 'mean', 'min': 'min', 'max': 'max'}.get(agg)
        if fn:
            piv = s.to_frame(name='v').pivot_table(
                index=s.index.month, columns=s.index.hour, values='v',
                aggfunc=fn)
        else:  # std
            piv = s.to_frame(name='v').pivot_table(
                index=s.index.month, columns=s.index.hour, values='v',
                aggfunc=lambda x: x.std(ddof=1) if len(x) > 1 else np.nan)
    piv = piv.reindex(index=months, columns=hours)
    if with_all:
        row_all, col_all, corner = _margins(s, s.index.month, s.index.hour,
                                            agg)
        piv['All'] = row_all.reindex(piv.index)
        piv.loc['All'] = col_all.reindex(piv.columns)
        piv.loc['All', 'All'] = corner
        if agg == 'count':
            piv = piv.fillna(0)
    return piv


def year_month_matrix(df: pd.DataFrame, col: str, agg: str = 'count',
                      mask=None, with_all: bool = False) -> pd.DataFrame:
    """年 × 月矩阵：行为数据中出现的年份升序，列 1..12 月；
    with_all=True 时末行/末列为 All 汇总。"""
    s = _numeric(df, col, mask)
    months = list(range(1, 13))
    if s.empty:
        return pd.DataFrame(np.nan, index=[], columns=months)
    if agg == 'count':
        piv = pd.crosstab(s.index.year, s.index.month)
    else:
        fn = {'mean': 'mean', 'min': 'min', 'max': 'max'}.get(agg)
        if fn:
            piv = s.to_frame(name='v').pivot_table(
                index=s.index.year, columns=s.index.month, values='v',
                aggfunc=fn)
        else:
            piv = s.to_frame(name='v').pivot_table(
                index=s.index.year, columns=s.index.month, values='v',
                aggfunc=lambda x: x.std(ddof=1) if len(x) > 1 else np.nan)
    years = sorted(set(s.index.year))
    piv = piv.reindex(index=years, columns=months)
    if with_all:
        row_all, col_all, corner = _margins(s, s.index.year, s.index.month,
                                            agg)
        piv['All'] = row_all.reindex(piv.index)
        piv.loc['All'] = col_all.reindex(piv.columns)
        piv.loc['All', 'All'] = corner
        if agg == 'count':
            piv = piv.fillna(0)
    return piv


def bin_edges(values: np.ndarray, bin_width: float | None = None,
              bin_start: float | None = None,
              half_first: bool = False) -> tuple[np.ndarray, float]:
    """与 Histogram 相同的分箱规则：显式 Width/Start at，否则自动 1/2/5。"""
    vmax = float(values.max())
    if bin_width is not None and bin_width > 0:
        width = float(bin_width)
        start = float(bin_start) if bin_start is not None \
            else np.floor(float(values.min()) / width) * width
    else:
        raw = max((vmax - float(values.min())) / 40.0, 1e-6)
        exp10 = 10 ** np.floor(np.log10(raw))
        frac = raw / exp10
        width = float(exp10 * (1 if frac <= 1 else 2 if frac <= 2
                               else 5 if frac <= 5 else 10))
        width = max(width, 0.1)
        start = float(np.floor(float(values.min()) / width) * width)
        if bin_start is not None:
            start = float(bin_start)
    w1 = width / 2.0 if half_first else width
    edges = [start, start + w1]
    while edges[-1] < vmax:
        edges.append(edges[-1] + width)
    if edges[-1] <= vmax:
        edges.append(edges[-1] + width)
    return np.asarray(edges, dtype=float), width


def bin_statistics(df: pd.DataFrame, col: str, bin_col: str,
                   bin_width: float | None = None,
                   bin_start: float | None = None,
                   half_first: bool = False,
                   mask=None) -> pd.DataFrame | None:
    """按 Bin column 分箱，统计 Data column 的 Occurrences/Mean/Min/Max/Std。

    返回索引 = (lower, upper) 的 DataFrame。"""
    if bin_col not in df.columns or col not in df.columns:
        return None
    b = pd.to_numeric(df[bin_col], errors='coerce')
    v = pd.to_numeric(df[col], errors='coerce')
    frame = pd.DataFrame({'b': b, 'v': v}).dropna()
    if mask is not None:
        m = pd.Series(mask, index=df.index).fillna(False).astype(bool)
        frame = frame[m.reindex(frame.index).fillna(False)]
    if frame.empty:
        return None
    edges, _ = bin_edges(frame['b'].to_numpy(), bin_width, bin_start,
                         half_first)
    # 出界值并入首/末箱
    binned = np.clip(np.digitize(frame['b'].to_numpy(), edges) - 1,
                     0, len(edges) - 2)
    frame = frame.assign(_bin=binned)
    out = frame.groupby('_bin')['v'].agg(
        count='count', mean='mean', min='min', max='max',
        std=lambda x: x.std(ddof=1) if len(x) > 1 else np.nan)
    out = out.reindex(range(len(edges) - 1))
    out.index = pd.MultiIndex.from_arrays(
        [edges[:-1], edges[1:]], names=['lower', 'upper'])
    return out


def directional_stats(df: pd.DataFrame, col: str, dir_col: str,
                      sectors: int = 12, mask=None) -> pd.DataFrame | None:
    """按风向扇区统计：索引 = 扇区序号(1 基)，列 count/freq%/mean/min/max/std。"""
    if dir_col not in df.columns or col not in df.columns:
        return None
    d = pd.to_numeric(df[dir_col], errors='coerce')
    v = pd.to_numeric(df[col], errors='coerce')
    frame = pd.DataFrame({'d': d, 'v': v}).dropna()
    if mask is not None:
        m = pd.Series(mask, index=df.index).fillna(False).astype(bool)
        frame = frame[m.reindex(frame.index).fillna(False)]
    if frame.empty:
        return None
    width = 360.0 / sectors
    k = ((frame['d'] - frame['d'].min() * 0) % 360.0) / width
    frame = frame.assign(_sec=np.floor(k).astype(int) % sectors)
    out = frame.groupby('_sec')['v'].agg(
        count='count', mean='mean', min='min', max='max',
        std=lambda x: x.std(ddof=1) if len(x) > 1 else np.nan)
    out = out.reindex(range(sectors))
    total = out['count'].sum()
    out['freq'] = out['count'] / total * 100.0 if total else np.nan
    out.index = range(1, sectors + 1)
    return out


def weibull_monthly(df: pd.DataFrame, col: str,
                    mask=None) -> pd.DataFrame | None:
    """按月 Weibull 统计：count/mean/k/c（调用 histogram.weibull_fit_mle）。"""
    from core.histogram import weibull_fit_mle
    if col not in df.columns:
        return None
    s = _numeric(df, col, mask)
    rows = {}
    for m in sorted({int(x) for x in s.index.month}):
        sm = s[s.index.month == m].dropna()
        st = _stats(sm)
        fit = weibull_fit_mle(sm.to_numpy())
        rows[m] = {'count': st['count'], 'mean': st['mean'],
                   'k': fit[0] if fit else np.nan,
                   'c': fit[1] if fit else np.nan}
    out = pd.DataFrame.from_dict(rows, orient='index').reindex(range(1, 13))
    out['count'] = out['count'].fillna(0)
    return out


def power_law_exponent(df: pd.DataFrame, columns: dict) -> float | None:
    """按唯一高度聚合风速均值后做 ln(v)-ln(z) 拟合，返回切变指数 alpha。

    columns: {列名: (kind, height)}；少于 2 个有效高度 → None。"""
    from collections import defaultdict
    agg = defaultdict(list)
    for name, (kind, height) in columns.items():
        if kind != 'speed' or not height or height <= 0 \
                or name not in df.columns:
            continue
        v = pd.to_numeric(df[name], errors='coerce').mean()
        if np.isfinite(v) and v > 0:
            agg[float(height)].append(float(v))
    if len(agg) < 2:
        return None
    heights = np.array(sorted(agg.keys()), dtype=float)
    vals = np.array([float(np.mean(agg[h])) for h in heights])
    slope, _ = np.polyfit(np.log(heights), np.log(vals), 1)
    return float(slope)


def mean_air_density(df: pd.DataFrame, temp_col: str | None,
                     pres_col: str | None) -> float | None:
    """平均空气密度 (kg/m³)：ρ = p/(R·T)，缺通道返回 None。"""
    _R_AIR = 287.05
    if (not temp_col or not pres_col
            or temp_col not in df.columns or pres_col not in df.columns):
        return None
    t = pd.to_numeric(df[temp_col], errors='coerce')
    p = pd.to_numeric(df[pres_col], errors='coerce')
    rho = (p * 100.0) / (_R_AIR * (t + 273.15))
    rho = rho.where((rho > 0.3) & (rho < 2.0))
    if rho.dropna().empty:
        return None
    return float(rho.mean())


def time_step_minutes(df: pd.DataFrame) -> float | None:
    """时间步长（分钟）：取索引差值的众数。"""
    if len(df.index) < 2:
        return None
    try:
        diffs = pd.Series(np.diff(np.asarray(df.index).astype('datetime64[s]')
                                  .astype('int64')) / 60.0)
        return float(diffs.mode().iloc[0])
    except (TypeError, ValueError):
        return None
