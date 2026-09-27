"""ConfigureDatasetDialog 自动关联（Auto-associate SD/Max/Min）回归测试。

覆盖 Speed/Dir/Temp/Pres/RH/Wz 各类 Avg 通道的 SD/Max/Min 自动关联，
以及非 Avg 通道不被反向填充、不同高度/方位不串扰（2026-09-01 引入）。
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PySide6.QtWidgets import QApplication

from core.dataset import (KIND_DIR, KIND_PRES, KIND_RH, KIND_SPEED,
                                  KIND_SPEED_SD, KIND_TEMP, KIND_WZ, Channel,
                                  Dataset)

app = QApplication.instance() or QApplication([])

from ui.dialogs.configure_dataset import ConfigureDatasetDialog


def _make_ds() -> Dataset:
    """两高度、两方位、六类通道的完整/残缺组合。"""
    ds = Dataset('m')
    ds.df = pd.DataFrame(
        {f'c{i}': [1.0] * 4 for i in range(20)},
        index=pd.date_range('2024-01-01', periods=4, freq='10min'))

    def add(name, kind, height, role, orient=''):
        ds.add_channel(Channel(name=name, kind=kind, height=height,
                               role=role))

    # Speed 10m N：四件套齐全
    add('Speed 10m N Avg', KIND_SPEED, 10, 'Avg', 'N')
    add('Speed 10m N SD', KIND_SPEED_SD, 10, 'SD', 'N')
    add('Speed 10m N Max', KIND_SPEED, 10, 'Max', 'N')
    add('Speed 10m N Min', KIND_SPEED, 10, 'Min', 'N')
    # Speed 10m S：只有 Avg（不应串到 N 组）
    add('Speed 10m S Avg', KIND_SPEED, 10, 'Avg', 'S')
    # Speed 20m N：只有 Avg（不同高度不串扰）
    add('Speed 20m N Avg', KIND_SPEED, 20, 'Avg', 'N')
    # 其余类型各一组 Avg+SD
    add('Dir 10m N Avg', KIND_DIR, 10, 'Avg', 'N')
    add('Dir 10m N SD', KIND_DIR, 10, 'SD', 'N')
    add('Temp Avg', KIND_TEMP, None, 'Avg')
    add('Temp SD', KIND_TEMP, None, 'SD')
    add('Pres Avg', KIND_PRES, None, 'Avg')
    add('Pres SD', KIND_PRES, None, 'SD')
    add('RH Avg', KIND_RH, None, 'Avg')
    add('RH SD', KIND_RH, None, 'SD')
    add('Wz 10m N Avg', KIND_WZ, 10, 'Avg', 'N')
    add('Wz 10m N SD', KIND_WZ, 10, 'SD', 'N')
    return ds


def _rows_by_name(dlg):
    return {r['name']: r for r in dlg._rows}


def test_auto_associate_full_group():
    dlg = ConfigureDatasetDialog(_make_ds())
    dlg._auto_associate()
    rows = _rows_by_name(dlg)
    r = rows['Speed 10m N Avg']
    assert r['sd_col'] == 'Speed 10m N SD'
    assert r['max_col'] == 'Speed 10m N Max'
    assert r['min_col'] == 'Speed 10m N Min'


def test_auto_associate_all_kinds():
    dlg = ConfigureDatasetDialog(_make_ds())
    dlg._auto_associate()
    rows = _rows_by_name(dlg)
    for avg, sd in [('Dir 10m N Avg', 'Dir 10m N SD'),
                    ('Temp Avg', 'Temp SD'),
                    ('Pres Avg', 'Pres SD'),
                    ('RH Avg', 'RH SD'),
                    ('Wz 10m N Avg', 'Wz 10m N SD')]:
        assert rows[avg]['sd_col'] == sd, f'{avg} -> {rows[avg]["sd_col"]}'


def test_no_cross_talk_between_height_or_orient():
    dlg = ConfigureDatasetDialog(_make_ds())
    dlg._auto_associate()
    rows = _rows_by_name(dlg)
    # 不同方位不串扰
    assert rows['Speed 10m S Avg']['sd_col'] == ''
    # 不同高度不串扰
    assert rows['Speed 20m N Avg']['sd_col'] == ''
    # SD/Min/Max 通道自身不反向填充
    assert rows['Speed 10m N SD']['sd_col'] == ''
    assert rows['Speed 10m N Max']['sd_col'] == ''
    assert rows['Speed 10m N Min']['min_col'] == ''


def test_orphan_avg_without_sd():
    dlg = ConfigureDatasetDialog(_make_ds())
    dlg._auto_associate()
    rows = _rows_by_name(dlg)
    # Speed 10m S / 20m N 无 SD → 关联留空且不报错
    assert rows['Speed 10m S Avg']['max_col'] == ''
    assert rows['Speed 20m N Avg']['max_col'] == ''
