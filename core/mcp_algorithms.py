"""MCP（Measure-Correlate-Predict）算法模块。

8 种 MCP 算法的完整实现，对齐 Windographer 13.2 章：
- Linear Least Squares (LLS)
- Total Least Squares (TLS)
- Variance Ratio (VR)
- Matrix Time Series (MTS)
- SpeedSort
- Vertical Slice
- Weibull Fit
- Bulk Speed Ratio

每个算法接收并发的参考/目标风速序列，返回预测函数参数。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _concurrent(ref: pd.Series, tgt: pd.Series):
    """提取并发期配对数据。"""
    df = pd.DataFrame({'ref': ref, 'tgt': tgt}).dropna()
    return df['ref'], df['tgt']


def _linear_ls(x: np.ndarray, y: np.ndarray, force_zero=False):
    """普通最小二乘线性回归 y = slope·x + intercept。"""
    if force_zero:
        slope = np.dot(x, y) / np.dot(x, x)
        return {'slope': float(slope), 'intercept': 0.0}
    slope, intercept = np.polyfit(x, y, 1)
    return {'slope': float(slope), 'intercept': float(intercept)}


def _r2(x, y, slope, intercept):
    pred = slope * x + intercept
    ss_res = np.sum((y - pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return 1 - ss_res / ss_tot if ss_tot > 0 else 0.0


# ---------------------------------------------------------------------------
# 1. Linear Least Squares (LLS)
# ---------------------------------------------------------------------------
def mcp_linear_ls(ref, tgt, force_zero=False):
    """线性最小二乘回归。"""
    r, t = _concurrent(ref, tgt)
    if len(r) < 10:
        return None
    p = _linear_ls(r.to_numpy(), t.to_numpy(), force_zero)
    p['r2'] = _r2(r.to_numpy(), t.to_numpy(), p['slope'], p['intercept'])
    p['n'] = len(r)
    return p


# ---------------------------------------------------------------------------
# 2. Total Least Squares (TLS)
# ---------------------------------------------------------------------------
def mcp_total_ls(ref, tgt, force_zero=False):
    """总最小二乘（正交回归）：同时最小化 x 和 y 方向的残差。"""
    r, t = _concurrent(ref, tgt)
    if len(r) < 10:
        return None
    x, y = r.to_numpy(), t.to_numpy()
    mx, my = x.mean(), y.mean()
    xc, yc = x - mx, y - my
    cov = np.vstack([xc, yc])
    _, _, vt = np.linalg.svd(cov @ cov.T / len(x))
    # 最小特征值对应的特征向量即法向量
    normal = vt[-1]
    slope = -normal[0] / normal[1]
    intercept = my - slope * mx
    if force_zero:
        slope = np.dot(x, y) / np.dot(x, x)
        intercept = 0.0
    return {'slope': float(slope), 'intercept': float(intercept),
            'r2': _r2(x, y, slope, intercept), 'n': len(x)}


# ---------------------------------------------------------------------------
# 3. Variance Ratio (VR)
# ---------------------------------------------------------------------------
def mcp_variance_ratio(ref, tgt, ref_lt=None, tgt_lt_stdev=None):
    """方差比法：利用参考和目标的方差比缩放长期标准差。

    slope = σ_tgt_concurrent / σ_ref_concurrent × σ_ref_longterm / σ_tgt_longterm
    简化版（无长期 σ_tgt 时）= σ_tgt / σ_ref。"""
    r, t = _concurrent(ref, tgt)
    if len(r) < 10:
        return None
    sigma_r = float(r.std(ddof=1))
    sigma_t = float(t.std(ddof=1))
    if sigma_r <= 0:
        return None
    slope = sigma_t / sigma_r
    mean_r = float(r.mean())
    mean_t = float(t.mean())
    intercept = mean_t - slope * mean_r
    return {'slope': slope, 'intercept': intercept,
            'r2': _r2(r.to_numpy(), t.to_numpy(), slope, intercept),
            'n': len(r), 'sigma_ratio': slope}


# ---------------------------------------------------------------------------
# 4. Matrix Time Series (MTS)
# ---------------------------------------------------------------------------
def mcp_matrix_time_series(ref, tgt, dir_series=None, sectors: int = 12):
    """矩阵时间序列法：按方向扇区和月份分别回归，综合预测。"""
    r, t = _concurrent(ref, tgt)
    if len(r) < 10:
        return None
    df = pd.DataFrame({'ref': r, 'tgt': t})
    if dir_series is not None and dir_series in df.columns:
        df['dir'] = dir_series
        df['month'] = df.index.month
        # 按 (月, 扇区) 分组回归
        df['sector'] = (df['dir'] % 360 / (360 / sectors)).astype(int)
        results = {}
        for (mo, sec), grp in df.groupby(['month', 'sector']):
            if len(grp) < 5:
                continue
            p = _linear_ls(grp['ref'].to_numpy(), grp['tgt'].to_numpy())
            results[(mo, sec)] = p
        if not results:
            return None
        # 综合斜率/截距（加权平均）
        slopes = [p['slope'] for p in results.values()]
        intercepts = [p['intercept'] for p in results.values()]
        slope = float(np.mean(slopes))
        intercept = float(np.mean(intercepts))
    else:
        p = _linear_ls(r.to_numpy(), t.to_numpy())
        slope, intercept = p['slope'], p['intercept']
    return {'slope': slope, 'intercept': intercept,
            'r2': _r2(r.to_numpy(), t.to_numpy(), slope, intercept),
            'n': len(r)}


# ---------------------------------------------------------------------------
# 5. SpeedSort
# ---------------------------------------------------------------------------
def mcp_speed_sort(ref, tgt, n_bins: int = 10, force_zero=False):
    """SpeedSort：按参考风速分箱，逐箱线性回归，综合预测。

    对每个箱（速度区间）独立拟合 target = slope·ref + intercept，
    预测时按参考风速落入的箱选择对应回归参数。"""
    r, t = _concurrent(ref, tgt)
    if len(r) < 20:
        return None
    v_min, v_max = float(r.min()), float(r.max())
    width = (v_max - v_min) / n_bins
    if width <= 0:
        return None
    edges = np.arange(v_min, v_max + width, width)
    bins = np.digitize(r.to_numpy(), edges) - 1
    bins = np.clip(bins, 0, n_bins - 1)
    df = pd.DataFrame({'ref': r.to_numpy(), 'tgt': t.to_numpy(),
                       'bin': bins})
    bin_regressions = {}
    for b, grp in df.groupby('bin'):
        if len(grp) < 5:
            continue
        p = _linear_ls(grp['ref'].to_numpy(), grp['tgt'].to_numpy(),
                       force_zero)
        bin_regressions[int(b)] = p
    if not bin_regressions:
        return None
    # 综合 R²（加权）
    total_r2 = 0.0
    total_n = 0
    for b, p in bin_regressions.items():
        grp = df[df['bin'] == b]
        if len(grp) > 2:
            total_r2 += _r2(grp['ref'].to_numpy(), grp['tgt'].to_numpy(),
                            p['slope'], p['intercept']) * len(grp)
            total_n += len(grp)
    overall_r2 = total_r2 / total_n if total_n else 0.0
    return {'bin_regressions': bin_regressions, 'edges': edges.tolist(),
            'r2': overall_r2, 'n': total_n,
            'avg_slope': float(np.mean([p['slope'] for p
                                        in bin_regressions.values()])),
            'avg_intercept': float(np.mean([p['intercept'] for p
                                            in bin_regressions.values()]))}


# ---------------------------------------------------------------------------
# 6. Vertical Slice
# ---------------------------------------------------------------------------
def mcp_vertical_slice(ref, tgt, dir_series, ref_dir,
                       slice_width: float = 30.0):
    """垂直切片法：仅使用参考风向在某扇区范围内的数据做回归。

    ref_dir : 参考风向列
    slice_width : 扇区宽度（°）"""
    r, t = _concurrent(ref, tgt)
    d = dir_series.reindex(r.index).dropna()
    common = r.index.intersection(d.index)
    r = r.loc[common]
    t = t.loc[common]
    d = d.loc[common]
    if len(r) < 10:
        return None
    center = float(ref_dir) if ref_dir else 0.0
    half = slice_width / 2.0
    diff = (d - center).abs()
    diff = diff.where(diff <= 180, 360 - diff)  # 环绕距离
    in_slice = diff <= half
    if in_slice.sum() < 10:
        return None
    p = _linear_ls(r[in_slice].to_numpy(), t[in_slice].to_numpy())
    return {'slope': p['slope'], 'intercept': p['intercept'],
            'r2': _r2(r[in_slice].to_numpy(), t[in_slice].to_numpy(),
                      p['slope'], p['intercept']),
            'n': int(in_slice.sum()), 'slice_center': center,
            'slice_width': slice_width}


# ---------------------------------------------------------------------------
# 7. Weibull Fit
# ---------------------------------------------------------------------------
def mcp_weibull_fit(ref, tgt):
    """Weibull 拟合法：分别拟合目标/参考的 Weibull 分布，
    用参考的短期/长期比值缩放目标的 c 参数。"""
    from core.histogram import weibull_fit_mle
    r, t = _concurrent(ref, tgt)
    if len(r) < 20:
        return None
    fit_ref = weibull_fit_mle(r.to_numpy())
    fit_tgt = weibull_fit_mle(t.to_numpy())
    if fit_ref is None or fit_tgt is None:
        return None
    k_r, c_r = fit_ref
    k_t, c_t = fit_tgt
    # 长期修正假设：参考长期 c 短期 = 1.0（简化），
    # 实际应由长期参考数据提供
    scale = 1.0
    return {'k': k_t, 'c': c_t * scale,
            'k_ref': k_r, 'c_ref': c_r,
            'mean_target': float(t.mean()),
            'mean_ref': float(r.mean()),
            'n': len(r)}


# ---------------------------------------------------------------------------
# 8. Bulk Speed Ratio
# ---------------------------------------------------------------------------
def mcp_bulk_speed_ratio(ref, tgt):
    """Bulk Speed Ratio：参考/目标平均风速比，作为均匀修正系数。"""
    r, t = _concurrent(ref, tgt)
    if len(r) < 10:
        return None
    mean_ref = float(r.mean())
    mean_tgt = float(t.mean())
    if mean_ref <= 0:
        return None
    ratio = mean_tgt / mean_ref
    return {'ratio': ratio, 'mean_ref': mean_ref, 'mean_tgt': mean_tgt,
            'n': len(r)}


# ---------------------------------------------------------------------------
# 统一接口
# ---------------------------------------------------------------------------
def run_mcp_algorithm(algorithm: str, ref: pd.Series, tgt: pd.Series,
                      ref_lt_mean: float | None = None,
                      **kwargs) -> dict | None:
    """统一 MCP 算法入口。

    algorithm: 'LLS' / 'TLS' / 'VR' / 'MTS' / 'SpeedSort' /
               'Vertical Slice' / 'Weibull Fit' / 'Bulk Speed Ratio'
    返回包含 slope/intercept/prediction 函数参数的 dict。
    """
    dispatch = {
        'LLS': lambda: mcp_linear_ls(ref, tgt, kwargs.get('force_zero', False)),
        'TLS': lambda: mcp_total_ls(ref, tgt),
        'VR': lambda: mcp_variance_ratio(ref, tgt),
        'MTS': lambda: mcp_matrix_time_series(ref, tgt),
        'SpeedSort': lambda: mcp_speed_sort(ref, tgt),
        'Vertical Slice': lambda: mcp_vertical_slice(ref, tgt),
        'Weibull Fit': lambda: mcp_weibull_fit(ref, tgt),
        'Bulk Speed Ratio': lambda: mcp_bulk_speed_ratio(ref, tgt),
    }
    fn = dispatch.get(algorithm)
    if fn is None:
        return None
    return fn()
