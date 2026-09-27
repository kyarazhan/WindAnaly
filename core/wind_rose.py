"""风玫瑰图数据计算。

支持 Windographer 风格的多维度风玫瑰：
- Display: occurrences/frequency/mean/max/std_dev/total_energy/scatter_plot
- Versus: direction / direction_and_month / direction_and_hour / direction_and_bin
- Sectors: 可配置扇区数
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


DISPLAY_TYPES = {
    'occurrences': 'occurrences',
    'frequency': 'frequency',
    'mean': 'mean',
    'min': 'min',
    'max': 'max',
    'std_dev': 'std_dev',
    'total_energy': 'total_energy',
    'scatter_plot': 'scatter_plot',
}

VERSUS_TYPES = {
    'direction': 'direction',
    'direction_and_month': 'direction_and_month',
    'direction_and_hour': 'direction_and_hour',
    'direction_and_bin': 'direction_and_bin',
}


@dataclass
class RoseResult:
    """风玫瑰计算结果。"""
    sectors: int
    center_deg: np.ndarray          # 扇区中心角度，形状 (sectors,)
    values: np.ndarray              # 主值矩阵，形状 (sectors, n_series)
    labels: list[str]               # 系列标签
    calm: float                     # 静风比例 (%)
    display: str                    # 当前 display 类型
    versus: str                     # 当前 versus 类型
    unit: str = '%'                 # 数值单位
    secondary: np.ndarray | None = None  # 第二维度标签（如月份/小时）


def _bin_direction(d: pd.Series, sectors: int,
                   bin_width: float | None = None,
                   bin_start: float | None = None,
                   half_first_bin: bool = False) -> tuple[pd.Series, np.ndarray]:
    """把风向分扇区，返回与 d 等长的 bin index Series（无效值为 NaN）和 center_deg。

    Parameters
    ----------
    bin_width : 每扇区宽度（°），None 时按 360/sectors 自动。
    bin_start : 第一扇区起始角度（°），None 时从 0° 开始。
    half_first_bin : 第一扇区是否宽度减半（Windographer 选项）。
    """
    if bin_width is None or bin_width <= 0:
        bin_width = 360.0 / sectors
    if bin_start is None:
        bin_start = 0.0
    bin_start = bin_start % 360.0

    vals = d.astype(float).values
    n = len(vals)

    # 有效风向：0 <= v < 360 且非缺测
    valid = d.notna().values & (vals >= 0) & (vals < 360)

    # 先把所有角度平移到以 bin_start 为原点的坐标系
    shifted = (vals - bin_start) % 360.0
    # 第一扇区半宽
    first_width = bin_width / 2.0 if half_first_bin else bin_width

    raw = np.full(n, np.nan)
    # 第一扇区：占据 [bin_start, bin_start + first_width)
    in_first = valid & (shifted < first_width)
    raw[in_first] = 0
    # 其余扇区
    rest = valid & ~in_first
    rest_idx = np.floor((shifted[rest] - first_width) / bin_width).astype(float) + 1
    # 超出的归到最后一扇区
    rest_idx = np.clip(rest_idx, 1, sectors - 1)
    raw[rest] = rest_idx

    bin_idx = pd.Series(raw, index=d.index)
    # 扇区中心：第一扇区中心 = bin_start + first_width/2；其余按 bin_width 递进
    center_deg = np.empty(sectors)
    center_deg[0] = (bin_start + first_width / 2.0) % 360.0
    for i in range(1, sectors):
        center_deg[i] = (center_deg[i - 1] + bin_width) % 360.0
    return bin_idx, center_deg


def _calm_ratio(df: pd.DataFrame, dir_col: str, speed_col: str | None) -> float:
    """静风比例（%）：有风速通道时按 speed<0.5，否则按 dir==0 或缺测。"""
    d = df[dir_col]
    n = len(d)
    if n == 0:
        return 0.0
    if speed_col and speed_col in df.columns:
        s = df[speed_col].astype(float)
        calm = (s < 0.5).sum()
    else:
        calm = d.isna().sum() + ((d == 0) | (d == 360)).sum()
    return float(calm / n * 100)


def compute_rose(
    df: pd.DataFrame,
    dir_col: str,
    sectors: int = 16,
    display: Literal['occurrences', 'frequency', 'mean', 'min', 'max',
                     'std_dev', 'total_energy', 'scatter_plot'] = 'frequency',
    versus: Literal['direction', 'direction_and_month',
                    'direction_and_hour', 'direction_and_bin'] = 'direction',
    data_col: str | None = None,
    speed_col: str | None = None,
    bin_col: str | None = None,
    filter_mask: pd.Series | np.ndarray | None = None,
    bin_width: float | None = None,
    bin_start: float | None = None,
    half_first_bin: bool = False,
) -> RoseResult | None:
    """计算风玫瑰数据。

    Parameters
    ----------
    df : 完整数据框（含时间索引）
    dir_col : 风向通道名
    sectors : 扇区数
    display : 显示类型
    versus : 对比维度
    data_col : display=mean/max/std_dev 时用的数据列；display=total_energy 时默认用 speed_col
    speed_col : 风速列，用于静风判断和 total_energy
    bin_col : versus=direction_and_bin 时用的分箱列
    filter_mask : 可选布尔过滤
    bin_width : 每扇区宽度（°），None 自动
    bin_start : 第一扇区起始角度（°），None 从 0° 开始
    half_first_bin : 第一扇区是否宽度减半
    """
    if dir_col not in df.columns:
        return None

    if filter_mask is not None:
        sub = df[filter_mask].copy()
    else:
        sub = df.copy()

    if len(sub) == 0:
        return None

    bin_idx, center_deg = _bin_direction(
        sub[dir_col], sectors,
        bin_width=bin_width, bin_start=bin_start,
        half_first_bin=half_first_bin,
    )
    calm = _calm_ratio(sub, dir_col, speed_col)

    # 对比维度 → 系列标签
    if versus == 'direction':
        series_key = pd.Series(0, index=sub.index)
        labels = [dir_col]
    elif versus == 'direction_and_month':
        series_key = pd.Series(pd.to_datetime(sub.index).month, index=sub.index)
        labels = [f'{m}月' for m in range(1, 13)]
    elif versus == 'direction_and_hour':
        series_key = pd.Series(pd.to_datetime(sub.index).hour, index=sub.index)
        labels = [f'{h}:00' for h in range(24)]
    elif versus == 'direction_and_bin':
        if bin_col and bin_col in sub.columns:
            series_key = pd.qcut(sub[bin_col].astype(float), q=4,
                                 labels=['Q1', 'Q2', 'Q3', 'Q4'],
                                 duplicates='drop')
            labels = [str(x) for x in series_key.cat.categories]
        else:
            series_key = pd.Series(0, index=sub.index)
            labels = [dir_col]
    else:
        series_key = pd.Series(0, index=sub.index)
        labels = [dir_col]

    groups = sorted(series_key.unique())
    n_series = len(groups)
    # versus=direction 时 series_key 全为 0，labels 应使用风向通道名
    if versus == 'direction':
        labels = [dir_col]
    else:
        labels = [str(g) for g in groups]

    values = np.zeros((sectors, n_series), dtype=float)

    if display in ('occurrences', 'frequency'):
        unit = '%' if display == 'frequency' else ''
        for j, g in enumerate(groups):
            mask = (series_key == g).values
            valid = mask & bin_idx.notna().values
            idx = bin_idx[valid].astype(int).values
            hist = np.bincount(idx, minlength=sectors).astype(float)
            if display == 'frequency':
                total = hist.sum()
                hist = hist / total * 100 if total > 0 else hist
            values[:, j] = hist
    elif display in ('mean', 'min', 'max', 'std_dev', 'total_energy'):
        if data_col is None:
            if display == 'total_energy':
                data_col = speed_col
            if data_col is None:
                return None
        if data_col not in sub.columns:
            return None
        y = sub[data_col].astype(float).values
        unit = sub[data_col].attrs.get('unit', '') or ''
        for j, g in enumerate(groups):
            mask = (series_key == g).values
            valid = mask & bin_idx.notna().values
            idx = bin_idx[valid].astype(int).values
            yv = y[valid]
            for s in range(sectors):
                sel = yv[idx == s]
                if len(sel) == 0:
                    values[s, j] = np.nan
                    continue
                if display == 'mean':
                    values[s, j] = np.nanmean(sel)
                elif display == 'min':
                    values[s, j] = np.nanmin(sel)
                elif display == 'max':
                    values[s, j] = np.nanmax(sel)
                elif display == 'std_dev':
                    values[s, j] = np.nanstd(sel)
                elif display == 'total_energy':
                    # ∝ v³，归一化到百分比
                    cube = np.nansum(sel ** 3)
                    values[s, j] = cube
            if display == 'total_energy':
                total = np.nansum(values[:, j])
                if total > 0:
                    values[:, j] = values[:, j] / total * 100
    elif display == 'scatter_plot':
        # scatter plot：在极坐标上画点（方向 vs 风速/数据列）
        if data_col is None:
            data_col = speed_col
        if data_col is None or data_col not in sub.columns:
            return None
        unit = sub[data_col].attrs.get('unit', '') or ''
        # 返回原始点，绘制层按散点处理
        values = np.column_stack([
            sub[dir_col].astype(float).values,
            sub[data_col].astype(float).values,
        ])
        return RoseResult(
            sectors=sectors, center_deg=center_deg,
            values=values, labels=labels, calm=calm,
            display=display, versus=versus, unit=unit,
        )
    else:
        return None

    return RoseResult(
        sectors=sectors, center_deg=center_deg,
        values=values, labels=labels, calm=calm,
        display=display, versus=versus, unit=unit,
    )
