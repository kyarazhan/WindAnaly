"""compute_rose 回归测试（Wind Rose 标签页计算层）。"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.wind_rose import compute_rose


def _make_df(n_days: int = 30) -> pd.DataFrame:
    """风向按扇区轮转 + 风速随行号递增，便于断言各扇区统计。"""
    rng = np.random.default_rng(9)
    n = n_days * 24
    idx = pd.date_range('2024-01-01', periods=n, freq='h')
    dirs = (np.arange(n) * (360.0 / 16)) % 360.0     # 均匀铺满 16 扇区
    speeds = 1.0 + (np.arange(n) % 20)               # 1~20 m/s 循环
    df = pd.DataFrame({'dir': dirs, 'spd': speeds,
                       'noise': rng.random(n)}, index=idx)
    return df


def test_frequency_direction_uniform():
    df = _make_df()
    r = compute_rose(df, 'dir', sectors=16, display='frequency',
                     versus='direction', speed_col='spd')
    assert r is not None
    assert r.labels == ['dir'] and r.unit == '%'
    # 风向均匀铺满 16 扇区 → 各扇区频率相等（=100/16）
    assert np.allclose(r.values[:, 0], 100.0 / 16, atol=0.5)
    assert 0 <= r.calm <= 1e-9 or r.calm >= 0


def test_occurrences_counts():
    df = _make_df(n_days=1)                      # 24 行，各扇区 1~2 个
    r = compute_rose(df, 'dir', sectors=16, display='occurrences',
                     versus='direction')
    assert r is not None and r.unit == ''
    assert r.values[:, 0].sum() == len(df)


def test_min_display_uses_data_col():
    df = _make_df(n_days=2)
    r = compute_rose(df, 'dir', sectors=16, display='min',
                     versus='direction', data_col='spd')
    assert r is not None
    # 每扇区的 min 应在整体 spd 范围内
    vals = r.values[:, 0]
    finite = vals[np.isfinite(vals)]
    assert finite.min() >= df['spd'].min() - 1e-9
    assert finite.max() <= df['spd'].max() + 1e-9


def test_bin_start_and_half_first():
    df = _make_df()
    r = compute_rose(df, 'dir', sectors=4, display='occurrences',
                     versus='direction', bin_width=90.0, bin_start=45.0,
                     half_first_bin=True)
    assert r is not None
    # 第一扇区中心 = bin_start + half_width/2
    assert abs(r.center_deg[0] - (45.0 + 22.5)) % 360 < 1e-6
    # 其余按整宽推进
    assert np.allclose(np.diff(r.center_deg) % 360.0, 90.0, atol=1e-6)


def test_versus_month_and_hour_labels():
    df = _make_df(n_days=90)                     # 跨 1~3 月
    r = compute_rose(df, 'dir', sectors=8, display='frequency',
                     versus='direction_and_month')
    assert r is not None
    assert r.labels == ['1', '2', '3']
    # 每系列频率各自归一化到 100%
    assert np.allclose(r.values.sum(axis=0), 100.0, atol=0.5)
    r2 = compute_rose(df, 'dir', sectors=8, display='occurrences',
                      versus='direction_and_hour')
    assert r2 is not None and len(r2.labels) == 24


def test_scatter_plot_returns_points():
    df = _make_df(n_days=2)
    r = compute_rose(df, 'dir', display='scatter_plot', versus='direction',
                     data_col='spd')
    assert r is not None
    assert r.values.shape[1] == 2                # (N, 2)：风向 + 数值
    assert r.values.shape[0] == len(df)
