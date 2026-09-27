"""计算列（Calculated Data Columns）核心计算，对齐 Windographer 17.11-17.18。

每种函数接收 DataFrame 和参数，返回 pd.Series（新列的值）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def col_accumulation(df: pd.DataFrame, col: str,
                     reset_each_year: bool = False) -> pd.Series:
    """Accumulation：逐行累加。可按年重置。"""
    s = pd.to_numeric(df[col], errors='coerce').fillna(0)
    if reset_each_year:
        result = s.groupby(s.index.year).cumsum()
    else:
        result = s.cumsum()
    result.name = f'{col} Accumulation'
    return result


def col_moving_average(df: pd.DataFrame, col: str,
                       window: int = 6, center: bool = True) -> pd.Series:
    """Moving Average：滚动窗口均值。"""
    s = pd.to_numeric(df[col], errors='coerce')
    result = s.rolling(window=window, center=center, min_periods=1).mean()
    result.name = f'{col} Mov Avg {window}'
    return result


def col_date_time(df: pd.DataFrame, component: str) -> pd.Series:
    """Date or Time：提取时间分量。

    component ∈ 'Year','Month','Day','Hour','Minute','Day of Year',
                'Day of Week','Hour of Day','Julian Day'
    """
    idx = df.index
    mapping = {
        'Year': idx.year, 'Month': idx.month, 'Day': idx.day,
        'Hour': idx.hour, 'Minute': idx.minute,
        'Day of Year': idx.dayofyear, 'Day of Week': idx.dayofweek,
    }
    if component == 'Julian Day':
        vals = idx.dayofyear + (idx.hour * 3600 + idx.minute * 60 +
                                idx.second) / 86400.0
        result = pd.Series(vals, index=idx)
    elif component in mapping:
        result = pd.Series(mapping[component], index=idx)
    else:
        raise ValueError(f'Unknown component: {component}')
    result.name = component
    return result


def col_piecewise_linear(df: pd.DataFrame, col: str,
                         breakpoints: list[tuple[float, float]]
                         ) -> pd.Series:
    """Piecewise Linear：分段线性函数。

    breakpoints: [(x0, y0), (x1, y1), ...] 升序 x。
    超出范围用端点值延伸。"""
    s = pd.to_numeric(df[col], errors='coerce')
    xs = np.array([bp[0] for bp in breakpoints])
    ys = np.array([bp[1] for bp in breakpoints])
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    result = pd.Series(np.interp(s.to_numpy(dtype=float), xs, ys),
                       index=df.index)
    result.name = f'{col} Piecewise'
    return result


def col_polynomial(df: pd.DataFrame, col: str,
                   coefficients: list[float]) -> pd.Series:
    """Polynomial：多项式变换 y = Σ c_i · x^i。

    coefficients: [c0, c1, c2, ...] 即 y = c0 + c1·x + c2·x² + ..."""
    s = pd.to_numeric(df[col], errors='coerce')
    result = pd.Series(np.zeros(len(s)), index=df.index)
    for i, c in enumerate(coefficients):
        result += c * s ** i
    result.name = f'{col} Poly'
    return result


def col_rotor_equivalent(df: pd.DataFrame,
                         speed_heights: list[tuple[str, float]],
                         hub_height: float, rotor_diameter: float) -> pd.Series:
    """Rotor Equivalent Wind Speed (REWS)：等效轮毂高度风速。

    speed_heights: [(列名, 高度 m), ...] 至少 2 个高度。
    REWS = (Σ v_i³ · Δh_i / D)^(1/3) / 常规平均，简化为加权三次均值。
    """
    if len(speed_heights) < 1:
        raise ValueError('Need at least 1 speed column')
    ordered = sorted(speed_heights, key=lambda t: t[1])
    total = 0.0
    weight_sum = 0.0
    result = None
    for i, (col, h) in enumerate(ordered):
        s = pd.to_numeric(df[col], errors='coerce')
        # 层厚：相邻高度中点
        if i == 0:
            lo = max(0.0, h - (ordered[1][1] - h) / 2) if len(ordered) > 1 else 0
        else:
            lo = (ordered[i - 1][1] + h) / 2
        if i == len(ordered) - 1:
            hi = h + (h - ordered[i - 1][1]) / 2 if len(ordered) > 1 else h
        else:
            hi = (h + ordered[i + 1][1]) / 2
        dh = max(hi - lo, 0.1)
        cube = s.clip(lower=0) ** 3 * dh
        total = total + cube if isinstance(total, pd.Series) else cube
        weight_sum += dh
    rews = (total / weight_sum) ** (1.0 / 3.0)
    rews.name = 'REWS'
    return rews


def col_solar_variables(df: pd.DataFrame, latitude: float,
                        col: str | None = None) -> pd.DataFrame:
    """Solar Variables：太阳高度角 / 方位角 / 大气外辐照度。

    返回 DataFrame 包含 solar_elevation / solar_azimuth / TOA_irradiance 列。
    简化算法（不含大气折射精确修正）。"""
    idx = df.index
    doy = idx.dayofyear.to_numpy(dtype=float)
    hour = idx.hour.to_numpy(dtype=float) + idx.minute.to_numpy() / 60.0
    lat = np.radians(latitude)
    # 太阳赤纬（Cooper 公式）
    decl = 23.45 * np.sin(np.radians(360 * (284 + doy) / 365))  # 度
    decl_rad = np.radians(decl)
    # 时角
    hour_angle = np.radians((hour - 12) * 15)
    # 太阳高度角
    sin_elev = (np.sin(lat) * np.sin(decl_rad) +
                np.cos(lat) * np.cos(decl_rad) * np.cos(hour_angle))
    elevation = np.degrees(np.arcsin(np.clip(sin_elev, -1, 1)))
    # 太阳方位角
    cos_az = ((np.sin(decl_rad) - np.sin(lat) * np.sin(np.radians(elevation))) /
              (np.cos(lat) * np.cos(np.radians(elevation)).clip(1e-9)))
    az_rad = np.arccos(np.clip(cos_az, -1, 1))
    azimuth = np.where(hour_angle > 0, 360 - np.degrees(az_rad),
                       np.degrees(az_rad))
    # 大气外辐照度 (W/m²)
    solar_constant = 1367.0
    toa = solar_constant * (1 + 0.033 * np.cos(np.radians(360 * doy / 365)))
    toa_irr = np.where(elevation > 0, toa * np.sin(np.radians(elevation.clip(0))), 0)

    result = pd.DataFrame({
        'Solar Elevation (°)': elevation,
        'Solar Azimuth (°)': azimuth,
        'TOA Irradiance (W/m2)': toa_irr,
    }, index=idx)
    return result


# ---------------------------------------------------------------------------
# 计算列类型注册表
# ---------------------------------------------------------------------------
CALC_TYPES = [
    {'key': 'copy', 'label': 'Copy Column', 'needs_a': True, 'needs_b': False},
    {'key': 'avg_2', 'label': 'Average of Two Speeds', 'needs_a': True,
     'needs_b': True},
    {'key': 'vector_avg', 'label': 'Vector Average Speed', 'needs_a': True,
     'needs_b': True},
    {'key': 'expression', 'label': 'Custom Expression', 'needs_a': True,
     'needs_b': True},
    {'key': 'accumulation', 'label': 'Accumulation', 'needs_a': True,
     'needs_b': False},
    {'key': 'moving_avg', 'label': 'Moving Average', 'needs_a': True,
     'needs_b': False},
    {'key': 'date_time', 'label': 'Date or Time Component', 'needs_a': False,
     'needs_b': False},
    {'key': 'piecewise', 'label': 'Piecewise Linear Function',
     'needs_a': True, 'needs_b': False},
    {'key': 'polynomial', 'label': 'Polynomial Function', 'needs_a': True,
     'needs_b': False},
    {'key': 'rews', 'label': 'Rotor Equivalent Wind Speed',
     'needs_a': True, 'needs_b': True},
    {'key': 'solar', 'label': 'Solar Variables', 'needs_a': False,
     'needs_b': False},
]


def compute_calculated(df: pd.DataFrame, calc_type: str, col_a: str = '',
                       col_b: str = '', name: str = '', **params) -> pd.Series:
    """统一计算列入口。"""
    dispatch = {
        'copy': lambda: pd.to_numeric(df[col_a], errors='coerce'),
        'avg_2': lambda: (pd.to_numeric(df[col_a], errors='coerce') +
                          pd.to_numeric(df[col_b], errors='coerce')) / 2,
        'vector_avg': lambda: np.sqrt(
            pd.to_numeric(df[col_a], errors='coerce') ** 2 +
            pd.to_numeric(df[col_b], errors='coerce') ** 2),
        'expression': lambda: pd.eval(params.get('expression', 'A'),
                                      engine='python',
                                      local_dict={
                                          'A': pd.to_numeric(df[col_a],
                                                             errors='coerce'),
                                          'B': pd.to_numeric(df[col_b],
                                                             errors='coerce')}),
        'accumulation': lambda: col_accumulation(
            df, col_a, params.get('reset_each_year', False)),
        'moving_avg': lambda: col_moving_average(
            df, col_a, params.get('window', 6)),
        'date_time': lambda: col_date_time(df, params.get('component', 'Hour')),
        'piecewise': lambda: col_piecewise_linear(
            df, col_a, params.get('breakpoints', [(0, 0), (1, 1)])),
        'polynomial': lambda: col_polynomial(
            df, col_a, params.get('coefficients', [0, 1])),
        'rews': lambda: col_rotor_equivalent(
            df, params.get('speed_heights', []),
            params.get('hub_height', 100), params.get('diameter', 90)),
        'solar': lambda: col_solar_variables(
            df, params.get('latitude', 30.0)).iloc[:, 0],
    }
    fn = dispatch.get(calc_type)
    if fn is None:
        raise ValueError(f'Unknown calc type: {calc_type}')
    result = fn()
    if not isinstance(result, pd.Series):
        result = pd.Series(result, index=df.index)
    result.index = df.index
    if name:
        result.name = name
    return result
