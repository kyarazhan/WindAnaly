"""极端风分析核心计算（对齐 Windographer 11.13 章算法）。

三种 50 年一遇极值风速算法：
- Periodic Maxima（Harris 1996 线性化 Gumbel 拟合，拟合 v²）
- Method of Independent Storms（阈值风暴 + 独立性合并，Harris 1999 拟合）
- EWTS II（Exact / Gumbel / Davenport 三变体，仅需均值与 Weibull k）

另含 Gumbel 线性化拟合与 EWTS II 公式，供工具对话框复用。
公式来源：Windographer 4.0.28 帮助文档 11.13.1-11.13.3 / 17.6-17.8。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Gumbel 线性化拟合（Harris 风格）
# ---------------------------------------------------------------------------
def gumbel_fit_linearized(peaks, events_per_year: float,
                          fit_squared: bool = True) -> dict | None:
    """对极值样本做线性化 Gumbel 拟合。

    peaks : 极值样本序列
    events_per_year : 每年周期数/风暴数 r（用于年化概率 p_ann = p_event^r）
    fit_squared : Harris 1996 建议对 v² 拟合（Periodic Maxima 用）；
                  Harris 1999（风暴法）用原值。

    返回 dict(a, b, v50, peaks, p_event, p_ann, y, n)；
    样本 < 5 个返回 None。拟合关系：target = a + b·y，
    y = -ln(-ln(F_ann))，v_T = (a + b·y_T)^(1/2 或 1)。"""
    v = np.asarray(peaks, dtype=float)
    v = v[np.isfinite(v) & (v > 0)]
    n = v.size
    if n < 5:
        return None
    v_sorted = np.sort(v)
    ranks = np.arange(1, n + 1)
    p_event = (ranks - 0.44) / (n + 0.12)        # Gringorten 绘图位置
    r = max(float(events_per_year), 1e-6)
    p_ann = np.clip(p_event ** r, 1e-12, 1 - 1e-12)
    y = -np.log(-np.log(p_ann))
    target = v_sorted ** 2 if fit_squared else v_sorted
    b, a = np.polyfit(y, target, 1)
    if b <= 0:
        return None

    def v_for_period(return_years: float) -> float:
        y_t = -np.log(-np.log(1.0 - 1.0 / return_years))
        val = a + b * y_t
        return math.sqrt(val) if fit_squared else val

    return {'a': float(a), 'b': float(b), 'v50': v_for_period(50.0),
            'n': int(n), 'peaks': v_sorted, 'p_event': p_event,
            'p_ann': p_ann, 'y': y, 'fit_squared': fit_squared}


def periodic_maxima_peaks(series: pd.Series, period: str = 'year',
                          min_recovery: float | None = None,
                          steps_per_period: float | None = None):
    """按固定周期提取极值样本。

    period : 'year' / 'month'
    min_recovery : 剔除完整率低于该值（0~1）的周期；None 不过滤。
      完整率 = 组内非缺测数 / 组内理论步数（steps_per_period 或组内最大计数）。

    返回 (peaks: ndarray, recovery: dict{周期: 完整率})。"""
    s = pd.to_numeric(series, errors='coerce').dropna()
    if s.empty:
        return np.array([]), {}
    keys = s.index.year if period == 'year' else s.index.month
    groups = s.groupby(keys)
    peaks = groups.max()
    recovery = {}
    if min_recovery is not None:
        expected = steps_per_period
        for key, g in groups:
            rate = (g.notna().sum() / expected) if expected \
                else g.notna().sum() / max(groups.count().max(), 1)
            recovery[key] = float(rate)
        keep = [k for k, v in recovery.items() if v >= min_recovery]
        peaks = peaks.loc[keep]
    return peaks.to_numpy(dtype=float), recovery


def storm_peaks(series: pd.Series, threshold: float,
                independence_hours: float = 48.0):
    """独立风暴法：阈值以上事件取峰值，间隔小于 independence_hours 的事件合并。

    返回 (peaks: ndarray, storms_per_year: float)。"""
    s = pd.to_numeric(series, errors='coerce').dropna()
    s = s[s >= threshold]
    if s.empty:
        return np.array([]), 0.0
    # 连续超阈值段分组（允许子阈值单步不中断：以下一时间步为准）
    times = s.index
    groups = []
    start = 0
    for i in range(1, len(times)):
        gap_hours = (times[i] - times[i - 1]).total_seconds() / 3600.0
        if gap_hours > 1.0:                  # 出现子阈值时段 → 事件边界
            groups.append((start, i))
            start = i
    groups.append((start, len(times)))

    # 独立性合并：事件间隔 < independence_hours 则合并
    merged = []
    for g0, g1 in groups:
        if merged and (times[g0] - times[merged[-1][1] - 1]).total_seconds() \
                / 3600.0 < independence_hours:
            merged[-1] = (merged[-1][0], g1)
        else:
            merged.append((g0, g1))

    peaks = np.array([s.values[g0:g1].max() for g0, g1 in merged],
                     dtype=float)
    years = max((times[-1] - times[0]).total_seconds() / (365.25 * 86400.0),
                1e-6)
    return peaks, len(peaks) / years


def ewts_ii(v_ave: float, k: float, tr: float = 50.0,
            n: float = 23037.0) -> dict:
    """EWTS II 三变体 50 年极值（公式转录自手册 11.13.3 的公式图片）。

    n : 每年独立事件数（10 min 步长 + 1 年极值 = 23037）
    返回 {'exact', 'gumbel', 'davenport'}（均 × v_ave 前的比值另行可得）"""
    g = math.gamma(1.0 + 1.0 / k)
    ln_n = math.log(n)
    ln_term = math.log(1.0 - 1.0 / tr)

    # Exact：精确年极值分布反演
    exact_ratio = (-math.log(1.0 - math.exp(ln_term / n))) ** (1.0 / k) / g

    # Gumbel 近似
    gumbel_ratio = (ln_n ** (1.0 / k)) / (k * g) * \
        (k * ln_n - math.log(-math.log(1.0 - 1.0 / tr)))

    # Davenport 近似
    c1 = 1.0 + (k - 1.0) / (k * ln_n)
    c2 = 1.0 + math.log(k * g * ln_n ** ((k - 1.0) / k)) / \
        (k * ln_n - (k - 1.0))
    davenport_ratio = (ln_n ** ((k - 1.0) / k)) / (c1 * k * g) * \
        (c1 * c2 * k * ln_n - math.log(-math.log(1.0 - 1.0 / tr)))

    return {'exact': v_ave * exact_ratio,
            'gumbel': v_ave * gumbel_ratio,
            'davenport': v_ave * davenport_ratio,
            'ratios': {'exact': exact_ratio, 'gumbel': gumbel_ratio,
                       'davenport': davenport_ratio}}


def weibull_k_moment(v) -> float | None:
    """矩估计 Weibull k（EWTS II 输入用；σ/μ 比经验式）。"""
    a = np.asarray(v, dtype=float)
    a = a[np.isfinite(a) & (a > 0)]
    if a.size < 10:
        return None
    cv = a.std(ddof=1) / a.mean()
    if cv <= 0:
        return None
    return float(cv ** (-1.086))
