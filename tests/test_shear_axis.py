"""风切变计算（SummaryTab._compute_shear）回归测试。"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.dataset import KIND_SPEED, Channel, Dataset
from ui.modules.analysis_tabs import SummaryTab


def _make_ds(heights_speeds: dict) -> Dataset:
    """heights_speeds: {高度: 该高度平均风速}，各列取常数值。"""
    ds = Dataset('m')
    n = 5
    ds.df = pd.DataFrame(
        {f'Speed {h}m Avg': [v] * n for h, v in heights_speeds.items()},
        index=pd.date_range('2024-01-01', periods=n, freq='10min'))
    for h in heights_speeds:
        ds.add_channel(Channel(name=f'Speed {h}m Avg', kind=KIND_SPEED,
                               height=float(h), units='m/s', role='Avg'))
    return ds


def test_alpha_power_law_recovery():
    # v(z) = 5 * (z/10)^0.2 → alpha = 0.2
    heights = [10, 30, 60, 100]
    speeds = {h: 5.0 * (h / 10.0) ** 0.2 for h in heights}
    shear = SummaryTab._compute_shear(_make_ds(speeds))
    assert shear is not None
    assert abs(shear['alpha'] - 0.2) < 1e-9
    assert shear['r2'] > 0.999
    assert shear['n_heights'] == 4
    # 外推：v_tgt = v_ref * (z_tgt/z_ref)^alpha
    assert abs(shear['v_ref'] - 5.0) < 1e-9
    assert abs(shear['v_tgt'] - 5.0 * (100 / 10) ** 0.2) < 1e-9


def test_height_aggregation_across_booms():
    # 同一高度两支传感器取均值后再拟合
    ds = _make_ds({10: 5.0, 30: 5.0 * 3 ** 0.2})
    ds.add_channel(Channel(name='Speed 10m B Avg', kind=KIND_SPEED,
                           height=10, units='m/s', role='Avg'))
    ds.df['Speed 10m B Avg'] = 7.0          # 10m 两支均值 = 6.0
    shear = SummaryTab._compute_shear(ds)
    assert shear is not None
    profile = dict(shear['profile'])
    assert abs(profile[10.0] - 6.0) < 1e-9   # 高度内取均值


def test_insufficient_heights_returns_none():
    assert SummaryTab._compute_shear(None) is None
    assert SummaryTab._compute_shear(_make_ds({10: 5.0})) is None
