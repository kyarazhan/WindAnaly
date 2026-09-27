""""各格式选项卡共享的工具函数与公共选项基类（B3 拆分聚集）。"""
from __future__ import annotations

import math
import os
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QRadioButton, QSizePolicy, QSpinBox, QStackedWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QDoubleSpinBox,
)

from core.dataset import KIND_DIR, KIND_SPEED, Dataset
from core.i18n import tr
from ui.dialogs.compare_dialogs import (
    _col_disp, _dir_cols, _height_of, _numeric_cols, _speed_cols,
)


def _dir_sector_edges(sectors: int) -> np.ndarray:
    return np.linspace(0.0, 360.0, sectors + 1)


def _dir_mid_sectors(sectors: int) -> np.ndarray:
    edges = _dir_sector_edges(sectors)
    return (edges[:-1] + edges[1:]) / 2.0


def _circular_mean(angles: pd.Series) -> float:
    a = np.radians(np.asarray(angles.dropna()))
    if len(a) == 0:
        return np.nan
    return (np.degrees(np.arctan2(np.mean(np.sin(a)),
                                   np.mean(np.cos(a)))) + 360.0) % 360.0


def _infer_timestep_minutes(ds: Dataset) -> int:
    if ds.df.empty or len(ds.df.index) < 2:
        return 10
    deltas = ds.df.index.to_series().diff().dropna().dt.total_seconds()
    if len(deltas) == 0:
        return 10
    med = int(round(deltas.median() / 60.0))
    return max(1, med)


def _filter_rows(ds: Dataset, include_unflagged: bool, include_icing: bool,
                 include_invalid: bool, only_interval: bool,
                 t0: datetime, t1: datetime,
                 row_valid_mode: str = 'all',
                 cols: list[str] | None = None) -> pd.DataFrame:
    """按标记、时间区间、列有效性筛选行。"""
    df = ds.df.copy()
    if only_interval and not df.empty:
        df = df[(df.index >= t0) & (df.index <= t1)]
    mask = pd.Series(False, index=df.index)
    if include_unflagged:
        master = ds.flags.reindex(df.index, fill_value=False)
        mask = mask | (~master)
    if include_icing and 'Icing' in ds.flag_masks:
        m = ds.flag_masks['Icing'].reindex(df.index, fill_value=False)
        mask = mask | m
    if include_invalid and 'Invalid' in ds.flag_masks:
        m = ds.flag_masks['Invalid'].reindex(df.index, fill_value=False)
        mask = mask | m
    df = df[mask]
    if row_valid_mode == 'any':
        df = df[df.notna().any(axis=1)]
    elif row_valid_mode == 'every' and cols:
        present = [c for c in cols if c in df.columns]
        if present:
            df = df[df[present].notna().all(axis=1)]
    return df


def _format_timestamp(dt: datetime, date_fmt: str, date_delim: str,
                      time_fmt: str, pos: str, step_min: int) -> tuple[str, str]:
    if pos == 'end' and step_min > 0:
        dt = dt + pd.Timedelta(minutes=step_min)
    date_str = dt.strftime(date_fmt)
    if date_delim:
        date_str = date_str.replace('-', date_delim).replace('/', date_delim).replace('.', date_delim)
    time_str = dt.strftime(time_fmt)
    return date_str, time_str


def _format_period(t0: datetime, t1: datetime, fmt: str = 'short') -> str:
    if fmt == 'tws':
        return f'{t0.strftime("%d/%m/%Y %H:%M")} - {t1.strftime("%d/%m/%Y %H:%M")}'
    return f'{t0.strftime("%Y/%m/%d %H:%M")} - {t1.strftime("%Y/%m/%d %H:%M")}'


def _momm(s: pd.Series) -> float:
    """月均均值 (Mean of Monthly Means)。"""
    if s.empty:
        return np.nan
    return s.groupby([s.index.year, s.index.month]).mean().mean()


def _find_aux_cols(ds: Dataset, height: float | None):
    """为 Openwind 单高度导出寻找同高度的温度/密度/TI 列（如没有则回退到任意列）。"""
    temp_col = dens_col = ti_col = None
    if height is not None:
        for c in ds.df.columns:
            ch = ds.channels.get(c)
            if ch is None:
                continue
            if ch.height != height:
                continue
            if temp_col is None and ch.kind in ('temp', 'temperature') or (ch.units and 'C' in ch.units.upper()):
                temp_col = c
            if dens_col is None and ch.kind in ('density', 'rho') or (ch.units and 'kg' in ch.units.lower()):
                dens_col = c
            if ti_col is None and ch.kind in ('ti', 'turbulence'):
                ti_col = c
    # 回退：任意温度/密度/TI 列
    if temp_col is None:
        for c in ds.df.columns:
            ch = ds.channels.get(c)
            if ch and (ch.kind in ('temp', 'temperature') or (ch.units and 'C' in ch.units.upper())):
                temp_col = c
                break
    if dens_col is None:
        for c in ds.df.columns:
            ch = ds.channels.get(c)
            if ch and (ch.kind in ('density', 'rho') or (ch.units and 'kg' in ch.units.lower())):
                dens_col = c
                break
    if ti_col is None:
        for c in ds.df.columns:
            ch = ds.channels.get(c)
            if ch and ch.kind in ('ti', 'turbulence'):
                ti_col = c
                break
    return temp_col, dens_col, ti_col


# ---------------------------------------------------------------------------
# 公共选项（紧凑版）
# ---------------------------------------------------------------------------
class _CommonOptions(QWidget):
    """包含 Include、Export 区间、Preview settings 三个紧凑小组。"""

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.ds = ds
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # Include
        g1 = QGroupBox(tr('Include'))
        v1 = QVBoxLayout(g1)
        v1.setSpacing(2)
        v1.setContentsMargins(4, 4, 4, 4)
        self.chk_unflagged = QCheckBox('<Unflagged data>')
        self.chk_unflagged.setChecked(True)
        self.chk_icing = QCheckBox(tr('Icing'))
        self.chk_invalid = QCheckBox(tr('Invalid'))
        v1.addWidget(self.chk_unflagged)
        v1.addWidget(self.chk_icing)
        v1.addWidget(self.chk_invalid)
        lay.addWidget(g1)

        # Export interval
        g2 = QGroupBox(tr('Export'))
        v2 = QVBoxLayout(g2)
        v2.setSpacing(2)
        v2.setContentsMargins(4, 4, 4, 4)
        self.rb_all = QRadioButton(tr('all time steps'))
        self.rb_all.setChecked(True)
        self.rb_interval = QRadioButton(tr('only the interval:'))
        v2.addWidget(self.rb_all)
        v2.addWidget(self.rb_interval)

        h_from = QHBoxLayout()
        h_from.setSpacing(2)
        h_from.addWidget(QLabel(tr('from')))
        self.dt_from = QDateTimeEdit()
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat('yyyy/M/d h:mm')
        h_from.addWidget(self.dt_from)
        h_from.addStretch()
        v2.addLayout(h_from)

        h_to = QHBoxLayout()
        h_to.setSpacing(2)
        h_to.addWidget(QLabel('to'))
        self.dt_to = QDateTimeEdit()
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat('yyyy/M/d h:mm')
        h_to.addWidget(self.dt_to)
        h_to.addStretch()
        v2.addLayout(h_to)
        lay.addWidget(g2)

        # Preview settings
        g3 = QGroupBox(tr('Preview settings'))
        v3 = QVBoxLayout(g3)
        v3.setSpacing(2)
        v3.setContentsMargins(4, 4, 4, 4)
        self.chk_auto_preview = QCheckBox(tr('Automatically update preview'))
        self.chk_auto_preview.setChecked(True)
        self.btn_update = QPushButton(tr('Update Preview'))
        v3.addWidget(self.chk_auto_preview)
        v3.addWidget(self.btn_update)
        lay.addWidget(g3)
        lay.addStretch()

        if not self.ds.df.empty:
            self.dt_from.setDateTime(self.ds.df.index[0])
            self.dt_to.setDateTime(self.ds.df.index[-1])

    def filter(self) -> tuple[bool, bool, bool, bool, datetime, datetime]:
        return (
            self.chk_unflagged.isChecked(),
            self.chk_icing.isChecked(),
            self.chk_invalid.isChecked(),
            self.rb_interval.isChecked(),
            self.dt_from.dateTime().toPython(),
            self.dt_to.dateTime().toPython(),
        )

    def connect_changed(self, slot):
        for w in (self.chk_unflagged, self.chk_icing, self.chk_invalid):
            w.stateChanged.connect(slot)
        for w in (self.rb_all, self.rb_interval):
            w.toggled.connect(slot)
        self.dt_from.dateTimeChanged.connect(slot)
        self.dt_to.dateTimeChanged.connect(slot)
