"""Dataset 标记系统回归测试。

守护 apply_flag 双重定义覆盖事故（2026-09-02）：遗留桩
`apply_flag(self, rule)` 曾覆盖真实实现，导致 set_flag_range /
set_flag_mask 及 flag_dialogs 各调用点 TypeError。
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.dataset import Dataset


def _make_ds() -> Dataset:
    idx = pd.date_range('2024-01-01', periods=6, freq='10min')
    ds = Dataset('mast')          # 注意：df 不走构造参数
    ds.df = pd.DataFrame({'Speed 10m Avg': [1.0] * 6}, index=idx)
    return ds


def test_apply_flag_with_name_and_mask():
    ds = _make_ds()
    mask = pd.Series([True, False, True, False, False, False],
                     index=ds.df.index)
    ds.apply_flag('Icing', mask)
    assert ds.n_flags() == 2
    assert ds.n_flags('Icing') == 2


def test_set_flag_range():
    ds = _make_ds()
    ds.set_flag_range('2024-01-01 00:00', '2024-01-01 00:20')
    assert ds.n_flags('Invalid') == 3
    assert ds.n_flags() == 3


def test_set_flag_mask_and_remove():
    ds = _make_ds()
    mask = pd.Series([False, True, False, True, True, False],
                     index=ds.df.index)
    ds.set_flag_mask(mask, flag_name='Tower shading')
    assert ds.n_flags('Tower shading') == 3
    ds.remove_flag('Tower shading', mask)
    assert ds.n_flags('Tower shading') == 0
    assert ds.n_flags() == 0


def test_master_flag_or_of_named_masks():
    ds = _make_ds()
    idx = ds.df.index
    ds.apply_flag('Icing', pd.Series([True] + [False] * 5, index=idx))
    ds.apply_flag('Invalid', pd.Series([False, True] + [False] * 4, index=idx))
    assert ds.n_flags() == 2          # 主标记 = 任一命名标记为 True
    assert ds.n_flags('Icing') == 1
    assert ds.n_flags('Invalid') == 1


def test_apply_flag_accepts_ndarray_mask():
    """对话框 _segment_mask 传 index 比较得到的 ndarray，必须可用。"""
    ds = _make_ds()
    mask = (ds.df.index >= pd.Timestamp('2024-01-01 00:10')) & \
           (ds.df.index <= pd.Timestamp('2024-01-01 00:30'))
    ds.apply_flag('Low quality', mask)
    assert ds.n_flags('Low quality') == 3


def test_valid_series_drops_flagged():
    ds = _make_ds()
    ds.set_flag_range('2024-01-01 00:00', '2024-01-01 00:10')  # 含首尾 2 点
    assert ds.n_flags() == 2
    valid = ds.valid_series('Speed 10m Avg')
    assert len(valid) == 4
