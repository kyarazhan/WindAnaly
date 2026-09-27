"""table_stats 聚合回归测试（Tables 标签页计算层）。"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.table_stats import (bin_statistics, by_month_stats,
                                      by_year_stats, directional_stats,
                                      mean_air_density, month_hour_matrix,
                                      power_law_exponent, time_step_minutes,
                                      weibull_monthly, year_month_matrix)


def _make_df() -> pd.DataFrame:
    """60 天、每小时一行：风速 = 2 + 月号 + 时号，便于断言聚合值。"""
    idx = pd.date_range('2024-01-01', periods=60 * 24, freq='h')
    v = 2.0 + idx.month.to_numpy() + idx.hour.to_numpy() * 0.1
    return pd.DataFrame({'v': v, 'dir': (np.arange(len(idx)) * 11) % 360,
                         'bin': np.arange(len(idx)) % 5}, index=idx)


def test_by_month_stats():
    df = _make_df()
    r = by_month_stats(df, 'v')
    # 1 月只有 31 天（h=0..23 × 31），2 月 29 天
    assert r.loc[1, 'count'] == 31 * 24
    assert r.loc[2, 'count'] == 29 * 24
    assert r.loc[3, 'count'] == 0
    # 1 月均值：2 + 1 + 0.1 * mean(0..23) = 3 + 1.15
    assert abs(r.loc[1, 'mean'] - 4.15) < 1e-9


def test_month_hour_matrix():
    df = _make_df()
    m = month_hour_matrix(df, 'v', 'count')
    assert m.shape == (12, 24)
    assert m.loc[1, 0] == 31 and m.loc[2, 0] == 29 and m.loc[3, 0] == 0
    mm = month_hour_matrix(df, 'v', 'mean')
    # 1 月 0 时的均值 = 2 + 1 + 0 = 3
    assert abs(mm.loc[1, 0] - 3.0) < 1e-9
    assert np.isnan(mm.loc[3, 0])


def test_margins_with_all():
    df = _make_df()                      # 60 天 = 1 月 31 天 + 2 月 29 天
    mm = month_hour_matrix(df, 'v', 'mean', with_all=True)
    assert list(mm.columns) == list(range(24)) + ['All']
    assert list(mm.index) + [] == list(range(1, 13)) + ['All'] or \
        list(mm.index) == list(range(1, 13)) + ['All']
    # All 列（各月全时段均值）与角值（总体均值）
    assert abs(mm.loc[1, 'All'] - 4.15) < 1e-9
    overall = df['v'].mean()
    assert abs(mm.loc['All', 'All'] - overall) < 1e-9
    # All 行（各小时跨月均值）：0 时 = 2 + mean(月) + 0 = 2 + 89/60
    assert abs(mm.loc['All', 0] - (2.0 + 89.0 / 60.0)) < 1e-9
    # count 的 All 角值 = 总样本数
    mc = month_hour_matrix(df, 'v', 'count', with_all=True)
    assert mc.loc['All', 'All'] == len(df)
    assert mc.loc[1, 'All'] == 31 * 24
    # 单值系列 std 边际：min/max 表 All = 全量 min/max
    mn = month_hour_matrix(df, 'v', 'min', with_all=True)
    assert abs(mn.loc['All', 'All'] - df['v'].min()) < 1e-9


def test_by_month_with_all():
    df = _make_df()
    r = by_month_stats(df, 'v', with_all=True)
    assert list(r.index) == list(range(1, 13)) + ['All']
    assert r.loc['All', 'count'] == len(df)
    assert abs(r.loc['All', 'mean'] - df['v'].mean()) < 1e-9


def test_year_month_matrix():
    df = _make_df()
    m = year_month_matrix(df, 'v', 'count')
    assert list(m.index) == [2024]
    assert list(m.columns) == list(range(1, 13))
    assert m.loc[2024, 1] == 31 * 24


def test_bin_statistics():
    rng = np.random.default_rng(2)
    idx = pd.date_range('2024-01-01', periods=1000, freq='10min')
    df = pd.DataFrame({'v': rng.random(1000) * 10,
                       'b': rng.integers(0, 4, 1000)}, index=idx)
    r = bin_statistics(df, 'v', 'b', bin_width=1.0, bin_start=0.0)
    assert r is not None
    assert r['count'].sum() == 1000
    # 分箱依据是 b 列（0..3）→ 有数据的箱恰好 4 个
    assert r['count'].count() == 4
    # 每箱均值落在 v 的整体量程内
    assert r['mean'].min() >= df['v'].min() - 1e-9
    assert r['mean'].max() <= df['v'].max() + 1e-9


def test_directional_stats():
    df = _make_df()
    r = directional_stats(df, 'v', 'dir', sectors=12)
    assert r is not None
    assert len(r) == 12
    assert abs(r['freq'].sum() - 100.0) < 1e-6
    assert r['count'].sum() == len(df)


def test_weibull_monthly_and_helpers():
    df = _make_df()
    w = weibull_monthly(df, 'v')
    assert 1 in w.index and 3 in w.index
    assert np.isnan(w.loc[3, 'k'])                 # 3 月无数据
    assert w.loc[1, 'count'] == 31 * 24
    assert abs(w.loc[1, 'mean'] - 4.15) < 1e-9
    # 空气密度：15℃, 1013.25 hPa → ≈1.225
    idx = pd.date_range('2024-01-01', periods=4, freq='h')
    env = pd.DataFrame({'t': [15.0] * 4, 'p': [1013.25] * 4}, index=idx)
    rho = mean_air_density(env, 't', 'p')
    assert rho is not None and abs(rho - 1.225) < 0.01
    assert mean_air_density(env, None, None) is None
    assert time_step_minutes(env) == 60.0


def test_power_law_exponent():
    idx = pd.date_range('2024-01-01', periods=10, freq='10min')
    heights = [10, 50, 100]
    speeds = {h: 5.0 * (h / 10) ** 0.2 for h in heights}
    df = pd.DataFrame({f'Speed {h}m Avg': [v] * 10
                       for h, v in speeds.items()}, index=idx)
    columns = {f'Speed {h}m Avg': ('speed', float(h)) for h in heights}
    alpha = power_law_exponent(df, columns)
    assert alpha is not None and abs(alpha - 0.2) < 1e-9
    # 单一高度 → None
    one = {k: v for k, v in columns.items() if '10m' in k}
    assert power_law_exponent(df, one) is None
