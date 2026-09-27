"""compute_histogram / Weibull MLE 回归测试（Histogram 标签页计算层）。"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.histogram import (compute_histogram, weibull_fit_mle,
                                    weibull_pdf)


def _make_df() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    n = 4000
    idx = pd.date_range('2024-01-01', periods=n, freq='h')
    # Weibull(k=2, c=8) 抽样：x = c * (-ln U)^(1/k)
    u = rng.random(n)
    v = 8.0 * (-np.log(u)) ** 0.5
    return pd.DataFrame({'v': v, 'w': v * 0.5}, index=idx)


def test_weibull_fit_mle_recovers_parameters():
    rng = np.random.default_rng(3)
    n = 20000
    u = rng.random(n)
    x = 6.5 * (-np.log(u)) ** (1 / 1.76)
    fit = weibull_fit_mle(x)
    assert fit is not None
    k, c = fit
    assert abs(k - 1.76) < 0.1
    assert abs(c - 6.5) < 0.2
    # 小样本/退化 → None
    assert weibull_fit_mle([1.0, 2.0]) is None
    assert weibull_fit_mle([0.0] * 10) is None


def test_edges_auto_and_explicit():
    df = _make_df()
    r = compute_histogram(df, 'v')
    assert r is not None
    width_auto = float(np.median(np.diff(r.edges)))
    assert width_auto >= 0.1
    assert r.edges[0] <= df['v'].min()                       # 覆盖最小值
    assert r.edges[-1] >= df['v'].max()                      # 覆盖最大值
    # 显式 width/start
    r2 = compute_histogram(df, 'v', bin_width=0.5, bin_start=0.0)
    assert np.allclose(np.diff(r2.edges), 0.5)
    assert r2.edges[0] == 0.0
    assert np.allclose(r2.freq[:, 0].sum(), 100.0)           # 频率归一化


def test_half_first_bin():
    rng = np.random.default_rng(5)
    idx = pd.date_range('2024-01-01', periods=100, freq='h')
    df = pd.DataFrame({'v': rng.uniform(0.01, 9.99, 100)}, index=idx)
    r = compute_histogram(df, 'v', bin_width=1.0, bin_start=0.0,
                          half_first=True)
    assert r.edges[1] - r.edges[0] == 0.5                    # 首箱半宽
    widths = np.diff(r.edges)
    assert np.allclose(widths[1:], 1.0)
    assert r.occ[:, 0].sum() == 100                          # 全部样本入箱


def test_versus_month_and_two():
    df = _make_df()          # 4000 小时 ≈ 166 天，跨多月
    r = compute_histogram(df, 'v', versus='month', bin_width=1.0,
                          bin_start=0.0)
    assert len(r.labels) >= 2
    assert all(lab.startswith('v M') for lab in r.labels)
    assert r.weibull is None                                 # 非 one 模式不拟合
    # two data columns
    r2 = compute_histogram(df, 'v', col2='w', versus='two',
                           bin_width=1.0, bin_start=0.0)
    assert r2 is not None and r2.labels == ['v', 'w']
    assert r2.occ.shape[1] == 2


def test_filter_mask_and_extra():
    df = _make_df()
    mask = pd.Series(df['v'].to_numpy() < 8.0, index=df.index)
    r = compute_histogram(df, 'v', filter_mask=mask, bin_width=1.0,
                          bin_start=0.0)
    assert r.occ[:, 0].sum() == int(mask.sum())
    # extra 计算列（TI 类）可参与统计
    extra = {'v TI': df['w'] / df['v'] * 100}
    r2 = compute_histogram(df, 'v TI', extra=extra, bin_width=1.0,
                           bin_start=0.0)
    assert r2 is not None and r2.labels == ['v TI']
    assert np.allclose(r2.freq[:, 0].sum(), 100.0, atol=1e-6)


def test_weibull_pdf_shape():
    x = np.array([1.0, 4.0, 8.0, 16.0])
    pdf = weibull_pdf(x, 2.0, 8.0)
    assert pdf[2] > pdf[0] and pdf[3] < pdf[1]               # 单峰在 c 附近
