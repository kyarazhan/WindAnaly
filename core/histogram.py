"""频率分布（Histogram）数据计算。

对齐 Windographer「Histogram」：
- Display：frequency（百分比，含 Best-fit Weibull 叠加曲线）/ occurrences（频次）；
- Versus：one data column / data column and month / data column and hour
  of day / two data columns；
- 分箱：Width / Start at / Make first bin half this width；未指定时自动
  选 1/2/5×10^k 的箱宽覆盖数据范围；
- 数据列可为 df 实列或 extra 计算列（如 `<列> TI`/`<列> WPD`）。

纯计算，无 UI；filter_mask 由调用方（标记/日期/扇区过滤）构造后传入。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_AUTO_TARGET_BINS = 40      # 自动箱宽：把量程分成约 40 箱


@dataclass
class HistogramResult:
    """频率分布计算结果。"""
    labels: list[str]           # 系列标签（one 模式即列名）
    edges: np.ndarray           # (n+1,) 分箱边界
    occ: np.ndarray             # (n, n_series) Occurrences
    freq: np.ndarray            # (n, n_series) Frequency (%)
    unit: str = ''              # 数据列单位（如 m/s）
    weibull: dict | None = None  # {'k','c'}；仅 versus='one' 时拟合
    x_label: str = ''           # 图 x 轴标签（列名 + 单位）


def weibull_fit_mle(x) -> tuple[float, float] | None:
    """两参数 Weibull 极大似然估计（Newton 迭代，矩估计作初值）。

    返回 (k, c)；样本不足（<5）或退化时返回 None。"""
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a) & (a > 0)]
    n = a.size
    if n < 5:
        return None
    mean = a.mean()
    std = a.std(ddof=1)
    if std <= 0:
        return None
    k = (mean / std) ** (-1.086)            # 矩估计初值（经验式）
    k = min(max(k, 0.05), 20.0)
    logx = np.log(a)
    lbar = logx.mean()
    for _ in range(60):
        xk = a ** k
        m1 = xk.mean()
        m2 = (xk * logx).mean()
        m3 = (xk * logx * logx).mean()
        # f(k) = 1/k + mean(ln x) - m(x^k ln x)/m(x^k)
        f = 1.0 / k + lbar - m2 / m1
        # f'(k) = -1/k^2 - [m(x^k ln^2 x) m(x^k) - m(x^k ln x)^2] / m(x^k)^2
        fp = -1.0 / k ** 2 - (m3 * m1 - m2 * m2) / (m1 * m1)
        step = f / fp
        k_new = k - step
        if not np.isfinite(k_new) or k_new <= 0:
            break
        k_new = min(max(k_new, 0.05), 20.0)
        if abs(k_new - k) < 1e-10:
            k = k_new
            break
        k = k_new
    else:
        pass
    if not np.isfinite(k) or k <= 0:
        return None
    c = float((np.mean(a ** k)) ** (1.0 / k))
    if not (np.isfinite(k) and np.isfinite(c) and c > 0):
        return None
    return float(k), float(c)


def weibull_pdf(x, k: float, c: float) -> np.ndarray:
    """Weibull 概率密度函数（x≤0 处记 0，避免 k<1 时 0 负幂告警）。"""
    x = np.asarray(x, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        out = (k / c) * (x / c) ** (k - 1) * np.exp(-((x / c) ** k))
    return np.where(x > 0, out, 0.0)


def _auto_edges(vmin: float, vmax: float) -> tuple[float, float]:
    """自动 (width, start)：箱宽取 1/2/5×10^k 使箱数接近 40。"""
    raw = max((vmax - vmin) / _AUTO_TARGET_BINS, 1e-6)
    exp10 = 10 ** math.floor(math.log10(raw))
    frac = raw / exp10
    if frac <= 1:
        width = exp10
    elif frac <= 2:
        width = 2 * exp10
    elif frac <= 5:
        width = 5 * exp10
    else:
        width = 10 * exp10
    width = max(width, 0.1)
    start = math.floor(vmin / width) * width
    return float(width), float(start)


def _make_edges(values: np.ndarray, bin_width: float | None,
                bin_start: float | None, half_first: bool
                ) -> tuple[np.ndarray, float]:
    """构造分箱边界。溢出量程的值并入首/末箱（np.histogram 之后钳位）。"""
    vmax = float(values.max())
    if bin_width is not None and bin_width > 0:
        width = float(bin_width)
        start = float(bin_start) if (bin_start is not None) \
            else math.floor(float(values.min()) / width) * width
    else:
        width, start = _auto_edges(float(values.min()), vmax)
        if bin_start is not None:
            start = float(bin_start)
    w1 = width / 2.0 if half_first else width
    edges = [start, start + w1]
    while edges[-1] < vmax:
        edges.append(edges[-1] + width)
    if edges[-1] <= vmax:                     # vmax 恰在上边界时再补一箱
        edges.append(edges[-1] + width)
    return np.asarray(edges, dtype=float), width


def compute_histogram(df: pd.DataFrame,
                      col: str,
                      col2: str | None = None,
                      versus: str = 'one',
                      display: str = 'frequency',
                      bin_width: float | None = None,
                      bin_start: float | None = None,
                      half_first: bool = False,
                      filter_mask: pd.Series | np.ndarray | None = None,
                      extra: dict[str, pd.Series] | None = None,
                      unit: str = '',
                      x_label: str | None = None) -> HistogramResult | None:
    """计算频率分布。

    Parameters
    ----------
    df : 时序/记录 DataFrame
    col : 主数据列（df 实列或 extra 计算列）
    col2 : versus='two' 时的第二数据列
    versus : 'one' / 'month' / 'hour' / 'two'
    display : 'frequency' / 'occurrences'（决定 freq 是否归一化；
      occ/freq 两个矩阵都会给出，由 UI 按需取用）
    bin_width / bin_start / half_first : 分箱设置；None 时自动
    filter_mask : 与 df 等长的布尔掩码
    extra : 计算列名 → Series（如 `<列> TI`/`<列> WPD`）
    unit / x_label : 展示辅助信息
    """
    if extra:
        work = df.copy()
        for name, s in extra.items():
            work[name] = s
        df = work
    if col not in df.columns:
        return None
    sub = df
    if filter_mask is not None:
        mask = pd.Series(filter_mask, index=df.index).fillna(False).astype(bool)
        sub = df[mask]
        if sub.empty:
            return None

    # 系列划分
    if versus == 'two':
        if not col2 or col2 not in sub.columns:
            return None
        groups = [(f'{col}', sub[col]), (f'{col2}', sub[col2])]
    elif versus == 'month':
        s_all = pd.to_numeric(sub[col], errors='coerce').dropna()
        groups = [(f'{col} M{m}', s_all[s_all.index.month == m])
                  for m in sorted({int(m) for m in s_all.index.month})]
    elif versus == 'hour':
        s_all = pd.to_numeric(sub[col], errors='coerce').dropna()
        groups = [(f'{col} H{h:02d}', s_all[s_all.index.hour == h])
                  for h in sorted({int(h) for h in s_all.index.hour})]
    else:
        groups = [(col, sub[col])]
    if not groups:
        return None

    series = [pd.to_numeric(s, errors='coerce').dropna().to_numpy(dtype=float)
              for _, s in groups]
    pooled = np.concatenate([s for s in series if s.size]) \
        if any(s.size for s in series) else np.array([])
    if pooled.size == 0:
        return None
    edges, _ = _make_edges(pooled, bin_width, bin_start, half_first)

    occ_cols = []
    for s in series:
        if s.size == 0:
            occ_cols.append(np.zeros(len(edges) - 1, dtype=float))
            continue
        counts, _ = np.histogram(s, bins=edges)
        counts = counts.astype(float)
        # np.histogram 末箱右闭合，溢出纠正只针对真正的出界值：
        # < 首边界并入首箱，> 末边界并入末箱
        counts[0] += np.count_nonzero(s < edges[0])
        counts[-1] += np.count_nonzero(s > edges[-1])
        occ_cols.append(counts)
    occ = np.column_stack(occ_cols)
    totals = occ.sum(axis=0, keepdims=True)
    totals[totals == 0] = 1
    freq = occ / totals * 100.0

    weibull = None
    if versus == 'one' and series[0].size:
        fit = weibull_fit_mle(series[0])
        if fit is not None:
            weibull = {'k': fit[0], 'c': fit[1]}

    return HistogramResult(
        labels=[lab for lab, _ in groups],
        edges=edges,
        occ=occ,
        freq=freq,
        unit=unit,
        weibull=weibull,
        x_label=x_label if x_label is not None else
        (f'{col} ({unit})' if unit else col),
    )
