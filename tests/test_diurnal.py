"""compute_diurnal 核心回归测试（Diurnal Profile 标签页的计算层）。"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.diurnal import compute_diurnal


def _make_df() -> pd.DataFrame:
    """两天数据：每小时一个可预期的均值模式（夜小昼大）。"""
    idx = pd.date_range('2024-01-01', periods=48, freq='h')
    hours = np.tile(np.arange(24), 2)
    a = 5.0 + hours            # 列 a：0 时 5.0，23 时 28.0
    b = 1.0 + hours * 0.5      # 列 b：0 时 1.0，23 时 12.5
    return pd.DataFrame({'a': a, 'b': b}, index=idx)


def test_single_profile_means_and_steps():
    df = _make_df()
    r = compute_diurnal(df, ['a'])
    assert r is not None and not r.by_month
    assert r.labels == ['a']
    assert r.means.shape == (24, 1) and r.steps.shape == (24, 1)
    # 每小时恰好 2 个样本，均值 = 小时值本身
    assert (r.steps[:, 0] == 2).all()
    assert np.allclose(r.means[:, 0], np.arange(24) + 5.0)


def test_nan_skipped_per_column():
    idx = pd.date_range('2024-01-01', periods=48, freq='h')
    a = np.tile(np.arange(24), 2).astype(float)
    a[0] = np.nan                       # 0 时一个缺测 → 只剩 1 个样本
    df = pd.DataFrame({'a': a}, index=idx)
    r = compute_diurnal(df, ['a'])
    assert r.steps[0, 0] == 1
    assert r.means[0, 0] == 0.0         # 剩下的那个样本值为 0
    assert r.steps[5, 0] == 2


def test_use_common_steps():
    idx = pd.date_range('2024-01-01', periods=48, freq='h')
    a = np.tile(np.arange(24), 2).astype(float)
    b = np.tile(np.arange(24), 2).astype(float) + 100.0
    a[3] = np.nan                       # 两天 3 时 a 均缺测 → 共同模式剔除
    a[27] = np.nan
    df = pd.DataFrame({'a': a, 'b': b}, index=idx)
    r = compute_diurnal(df, ['a', 'b'], use_common=True)
    assert r.steps[3, 0] == 0 and r.steps[3, 1] == 0
    assert np.isnan(r.means[3, 0]) and np.isnan(r.means[3, 1])
    assert (np.delete(r.steps[:, 0], 3) == 2).all()   # 其余小时样本数一致
    assert (np.delete(r.steps[:, 1], 3) == 2).all()
    # 不用共同模式时：b 的 3 时仍有 2 个样本
    r2 = compute_diurnal(df, ['a', 'b'], use_common=False)
    assert r2.steps[3, 1] == 2


def test_by_month_labels():
    n_days = 90                          # 2024-01-01 起 90 天 = 1/2/3 月（闰年）
    idx = pd.date_range('2024-01-01', periods=n_days * 24, freq='h')
    hours = np.tile(np.arange(24), n_days)
    df = pd.DataFrame({'a': hours.astype(float)}, index=idx)
    r = compute_diurnal(df, ['a'], by_month=True)
    assert r.by_month and r.month_of == [1, 2, 3]
    assert r.labels == ['a M1', 'a M2', 'a M3']
    assert r.means.shape == (24, 3)
    # 每月整天数个完整循环 → 每小时均值 = 小时值
    assert np.allclose(r.means[:, 0], np.arange(24))
    assert np.allclose(r.means[:, 2], np.arange(24))


def test_filter_mask():
    df = _make_df()
    mask = pd.Series([True] * 24 + [False] * 24, index=df.index)  # 只留第 1 天
    r = compute_diurnal(df, ['a', 'b'], filter_mask=mask)
    assert (r.steps[:, 0] == 1).all()
    assert np.allclose(r.means[:, 1], 1.0 + np.arange(24) * 0.5)


def test_invalid_inputs():
    df = _make_df()
    assert compute_diurnal(df, []) is None
    assert compute_diurnal(df, ['missing']) is None
    assert compute_diurnal(df, ['a'], filter_mask=pd.Series(
        False, index=df.index)) is None
