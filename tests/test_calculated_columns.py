"""计算列核心回归测试（Calculated Data Columns）。"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.calculated_columns import (
    col_accumulation, col_moving_average, col_date_time,
    col_piecewise_linear, col_polynomial, col_rotor_equivalent,
    col_solar_variables, compute_calculated,
)


def _make_df():
    idx = pd.date_range('2024-01-01', periods=48, freq='h')
    return pd.DataFrame({'v': np.arange(48, dtype=float)}, index=idx)


def test_accumulation():
    df = _make_df()
    r = col_accumulation(df, 'v')
    assert abs(r.iloc[-1] - sum(range(48))) < 1e-6
    r2 = col_accumulation(df, 'v', reset_each_year=True)
    assert r2.iloc[0] == 0.0


def test_moving_average():
    df = _make_df()
    r = col_moving_average(df, 'v', window=6, center=False)
    # trailing 窗口：iloc[10] = mean(v[5:11]) = mean(5..10) = 7.5
    assert abs(r.iloc[10] - np.mean(range(5, 11))) < 1e-6
    assert pd.notna(r.iloc[0])           # min_periods=1


def test_date_time():
    df = _make_df()
    y = col_date_time(df, 'Year')
    assert (y == 2024).all()
    h = col_date_time(df, 'Hour')
    assert h.iloc[0] == 0 and h.iloc[13] == 13


def test_piecewise_linear():
    df = _make_df()
    bp = [(0, 0), (10, 100), (50, 0)]
    s = pd.to_numeric(df['v'], errors='coerce')
    r = col_piecewise_linear(df, 'v', bp)
    assert r.iloc[5] == 50.0             # v=5 → 线性插值 50
    assert r.iloc[0] == 0.0


def test_polynomial():
    df = _make_df()
    r = col_polynomial(df, 'v', [0, 2, 1])   # y = 2x + x²
    assert abs(r.iloc[3] - (2 * 3 + 9)) < 1e-6


def test_rotor_equivalent():
    idx = pd.date_range('2024-01-01', periods=4, freq='10min')
    df = pd.DataFrame({'v_40': [4.0] * 4, 'v_60': [6.0] * 4}, index=idx)
    r = col_rotor_equivalent(df, [('v_40', 40.0), ('v_60', 60.0)], 50, 90)
    # REWS = 三次均方根 ≈ ((4³ + 6³)/2)^(1/3) ≈ 5.13
    assert 4.5 < r.iloc[0] < 6.5


def test_solar_variables():
    idx = pd.date_range('2024-06-21', periods=24, freq='h')
    df = pd.DataFrame(index=idx)
    r = col_solar_variables(df, 40.0)
    assert 'Solar Elevation (°)' in r.columns
    # 夏至正午北纬 40° 太阳高度角 > 60°
    noon_elev = r.iloc[12]['Solar Elevation (°)']
    assert noon_elev > 60


def test_compute_calculated_dispatch():
    df = _make_df()
    r = compute_calculated(df, 'moving_avg', col_a='v', window=3, name='MA3')
    assert r.name == 'MA3'
    assert len(r) == 48
