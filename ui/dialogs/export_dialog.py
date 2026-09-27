"""Export Data 对话框：支持多种风资源软件格式导出。

布局参考 Windographer 4.0.28 Export Data 对话框：紧凑三栏，底部文件预览。
"""
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


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Time Series tab
# ---------------------------------------------------------------------------
class _TimeSeriesTab(QWidget):
    def __init__(self, ds: Dataset, preview: QTextEdit, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self.step_min = _infer_timestep_minutes(ds)
        self._factor = 1.0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)

        # Left: column selector
        left = QGroupBox(tr('Select data columns to export'))
        v_left = QVBoxLayout(left)
        v_left.setSpacing(2)
        v_left.setContentsMargins(4, 4, 4, 4)
        self.chk_all = QCheckBox(tr('Select all'))
        self.chk_all.setChecked(True)
        v_left.addWidget(self.chk_all)
        self.lst_cols = QListWidget()
        self.lst_cols.setMinimumWidth(220)
        for c in self.ds.df.columns:
            item = QListWidgetItem(_col_disp(self.ds, c))
            item.setData(Qt.UserRole, c)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.lst_cols.addItem(item)
        v_left.addWidget(self.lst_cols)
        top.addWidget(left, stretch=1)

        # Middle: common options
        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid)

        # Right: Data + Other settings
        right = QVBoxLayout()
        right.setSpacing(4)

        g_data = QGroupBox(tr('Data'))
        f_data = QFormLayout(g_data)
        f_data.setSpacing(2)
        f_data.setContentsMargins(4, 4, 4, 4)
        h_int = QHBoxLayout()
        self.cmb_interval = QComboBox()
        self.cmb_interval.addItems(['Raw', '10 minutes', 'Hourly', 'Daily'])
        idx = {'Raw': 0, '10 minutes': 1, 'Hourly': 2, 'Daily': 3}.get(
            f'{self.step_min} minutes' if self.step_min != 60 else 'Hourly', 0)
        self.cmb_interval.setCurrentIndex(idx)
        h_int.addWidget(self.cmb_interval)
        h_int.addWidget(QLabel(tr('minutes')))
        h_int.addStretch()
        f_data.addRow('Interval:', h_int)
        self.chk_export_time = QCheckBox(tr('Export date and time'))
        self.chk_export_time.setChecked(True)
        f_data.addRow(self.chk_export_time)
        self.cmb_date_fmt = QComboBox()
        self.cmb_date_fmt.addItems(['YYYYMMDD', 'YYMMDD', 'DDMMYYYY',
                                     'DDMMYY', 'MMDDYY', 'MMDDYYYY'])
        f_data.addRow('Date format', self.cmb_date_fmt)
        self.cmb_date_delim = QComboBox()
        self.cmb_date_delim.addItems(['<none>', 'period', 'space', '/', '-'])
        f_data.addRow('Date delimiter', self.cmb_date_delim)
        self.cmb_time_fmt = QComboBox()
        self.cmb_time_fmt.addItems(['HH:MM', 'HH:MM:SS', 'HHMM', 'HHMMSS'])
        f_data.addRow('Time format', self.cmb_time_fmt)
        self.cmb_time_pos = QComboBox()
        self.cmb_time_pos.addItems(['start of time step', 'end of time step'])
        f_data.addRow('Time stamp indicates', self.cmb_time_pos)
        right.addWidget(g_data)

        g_other = QGroupBox(tr('Other settings'))
        f_other = QFormLayout(g_other)
        f_other.setSpacing(2)
        f_other.setContentsMargins(4, 4, 4, 4)
        self.cmb_delim = QComboBox()
        self.cmb_delim.addItems(['tab', 'comma', 'space', 'custom'])
        f_other.addRow('File delimiter', self.cmb_delim)
        h_custom = QHBoxLayout()
        self.lbl_custom = QLabel(tr('Custom:'))
        self.edit_custom_delim = QLineEdit('|')
        self.edit_custom_delim.setMaximumWidth(40)
        h_custom.addWidget(self.lbl_custom)
        h_custom.addWidget(self.edit_custom_delim)
        h_custom.addStretch()
        f_other.addRow(h_custom)
        self.edit_missing = QLineEdit()
        self.edit_missing.setPlaceholderText('e.g. -999')
        f_other.addRow('Missing data pair', self.edit_missing)
        self.cmb_export_rows = QComboBox()
        self.cmb_export_rows.addItems([
            'all time steps',
            'time steps with any valid data',
            'time steps with valid data in every column'])
        f_other.addRow('Export', self.cmb_export_rows)
        self.chk_maintain = QCheckBox(tr('Maintain constant wind speed'))
        self.chk_maintain.setVisible(False)
        f_other.addRow(self.chk_maintain)
        self.lbl_factor = QLabel('')
        self.lbl_factor.setVisible(False)
        f_other.addRow(self.lbl_factor)
        right.addWidget(g_other)
        right.addStretch()
        top.addLayout(right, stretch=1)

        lay.addLayout(top, stretch=2)

        # signals
        self.chk_all.stateChanged.connect(self._toggle_all)
        self.lst_cols.itemChanged.connect(self._maybe_update)
        self.cmb_delim.currentIndexChanged.connect(self._on_delim_changed)
        for w in (self.cmb_interval, self.cmb_date_fmt, self.cmb_date_delim,
                  self.cmb_time_fmt, self.cmb_time_pos, self.cmb_export_rows):
            w.currentIndexChanged.connect(self._maybe_update)
        self.chk_export_time.stateChanged.connect(self._maybe_update)
        self.edit_custom_delim.textChanged.connect(self._maybe_update)
        self.edit_missing.textChanged.connect(self._maybe_update)
        self.chk_maintain.stateChanged.connect(self._maybe_update)
        self.common.connect_changed(self._maybe_update)
        self.common.chk_auto_preview.stateChanged.connect(
            lambda: self._maybe_update() if self.common.chk_auto_preview.isChecked() else None)

        self._on_delim_changed()
        self._update_preview()

    def _on_delim_changed(self):
        visible = self.cmb_delim.currentText() == 'custom'
        self.lbl_custom.setVisible(visible)
        self.edit_custom_delim.setVisible(visible)
        self._maybe_update()

    def _toggle_all(self, state):
        for i in range(self.lst_cols.count()):
            self.lst_cols.item(i).setCheckState(
                Qt.Checked if state == Qt.Checked.value else Qt.Unchecked)
        self._maybe_update()

    def _maybe_update(self):
        is_every = (self.cmb_export_rows.currentText() ==
                    'time steps with valid data in every column')
        self.chk_maintain.setVisible(is_every)
        self.lbl_factor.setVisible(is_every and self.chk_maintain.isChecked())
        if self.common.chk_auto_preview.isChecked():
            self._update_preview()

    def _selected_cols(self) -> list[str]:
        cols = []
        for i in range(self.lst_cols.count()):
            item = self.lst_cols.item(i)
            if item.checkState() == Qt.Checked:
                cols.append(item.data(Qt.UserRole))
        return cols

    def _speed_cols_selected(self, cols: list[str]) -> list[str]:
        return [c for c in cols if c in self.ds.channels
                and self.ds.channels[c].kind == 'speed']

    def _delim(self):
        d = self.cmb_delim.currentText()
        if d == 'custom':
            return self.edit_custom_delim.text() or '|'
        return {'tab': '\t', 'comma': ',', 'space': ' '}[d]

    def _date_delim_char(self) -> str:
        d = self.cmb_date_delim.currentText()
        return {'<none>': '', 'period': '.', 'space': ' ', '/': '/', '-': '-'}.get(d, '')

    def _date_fmt_str(self) -> str:
        m = {
            'YYYYMMDD': '%Y-%m-%d',
            'YYMMDD': '%y-%m-%d',
            'DDMMYYYY': '%d-%m-%Y',
            'DDMMYY': '%d-%m-%y',
            'MMDDYY': '%m-%d-%y',
            'MMDDYYYY': '%m-%d-%Y',
        }
        return m[self.cmb_date_fmt.currentText()]

    def _time_fmt_str(self) -> str:
        m = {
            'HH:MM': '%H:%M',
            'HH:MM:SS': '%H:%M:%S',
            'HHMM': '%H%M',
            'HHMMSS': '%H%M%S',
        }
        return m[self.cmb_time_fmt.currentText()]

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text(preview=True))

    def generate_text(self, preview: bool = False) -> str:
        cols = self._selected_cols()
        if not cols:
            return '# No columns selected'
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        row_mode_map = {
            'all time steps': 'all',
            'time steps with any valid data': 'any',
            'time steps with valid data in every column': 'every',
        }
        row_mode = row_mode_map[self.cmb_export_rows.currentText()]
        # 先按标记/时间区间过滤，用于计算原始风速均值
        df0 = _filter_rows(self.ds, u, ic, inv, only_int, t0, t1,
                           row_valid_mode='all')
        speed_cols = self._speed_cols_selected(cols)
        original_mean = np.nan
        if speed_cols and not df0.empty:
            original_mean = df0[speed_cols].mean().mean()

        df = df0.copy()
        if row_mode == 'any':
            df = df[df.notna().any(axis=1)]
        elif row_mode == 'every':
            df = df[df[cols].notna().all(axis=1)]

        self._factor = 1.0
        if (row_mode == 'every' and self.chk_maintain.isChecked()
                and speed_cols and not pd.isna(original_mean)
                and not df.empty):
            filtered_mean = df[speed_cols].mean().mean()
            if filtered_mean and filtered_mean > 0:
                self._factor = original_mean / filtered_mean
                for c in speed_cols:
                    df[c] = df[c] * self._factor
        self.lbl_factor.setText(
            f'Scaling factor: {self._factor:.4f}'
            if self.chk_maintain.isChecked() else '')

        if df.empty:
            return '# No data in selection'
        delim = self._delim()
        date_fmt = self._date_fmt_str()
        date_delim = self._date_delim_char()
        time_fmt = self._time_fmt_str()
        pos = self.cmb_time_pos.currentText().split()[0]
        missing = self.edit_missing.text()
        buf = []
        header = []
        if self.chk_export_time.isChecked():
            header.extend(['Date', 'Time'])
        header.extend(cols)
        buf.append(delim.join(header))
        limit = 30 if preview else None
        for ts, row in df.iterrows():
            line = []
            if self.chk_export_time.isChecked():
                d, t = _format_timestamp(ts, date_fmt, date_delim,
                                           time_fmt, pos, self.step_min)
                line.extend([d, t])
            for c in cols:
                v = row.get(c)
                if pd.isna(v):
                    line.append(missing)
                else:
                    line.append(str(v))
            buf.append(delim.join(line))
            if limit and len(buf) > limit:
                buf.append('# ... (preview truncated)')
                break
        return '\n'.join(buf)

    def _extension(self) -> str:
        d = self.cmb_delim.currentText()
        return '.txt' if d in ('tab', 'space', 'custom') else '.csv'

    def do_export(self, parent):
        cols = self._selected_cols()
        if not cols:
            QMessageBox.warning(parent, tr('导出失败'), tr('请选择至少一列'))
            return False
        ext = self._extension()
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 Time Series',
            f'{self.ds.name}{ext}',
            f'Text (*{ext});;All files (*.*)')
        if not path:
            return False
        text = self.generate_text(preview=False)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        return True


# ---------------------------------------------------------------------------
# WAsP .tab
# ---------------------------------------------------------------------------
class _WasPTab(QWidget):
    def __init__(self, ds, preview, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)

        # Left: WAsP options
        left = QGroupBox(tr('WAsP options'))
        f_left = QFormLayout(left)
        f_left.setSpacing(2)
        f_left.setContentsMargins(4, 4, 4, 4)
        self.cmb_speed = QComboBox()
        for c in _speed_cols(self.ds):
            self.cmb_speed.addItem(_col_disp(self.ds, c), c)
        f_left.addRow('Wind speed sensor:', self.cmb_speed)
        self.cmb_dir = QComboBox()
        for c in _dir_cols(self.ds):
            self.cmb_dir.addItem(_col_disp(self.ds, c), c)
        f_left.addRow('Wind direction sensor:', self.cmb_dir)
        self.cmb_sectors = QComboBox()
        self.cmb_sectors.addItems(['8', '12', '16', '24', '36', '48'])
        self.cmb_sectors.setCurrentText('16')
        f_left.addRow('Wind direction sectors:', self.cmb_sectors)
        h_bin = QHBoxLayout()
        self.spn_bin = QDoubleSpinBox()
        self.spn_bin.setRange(0.1, 10.0)
        self.spn_bin.setValue(1.0)
        self.spn_bin.setDecimals(1)
        self.spn_bin.setSuffix(' m/s')
        h_bin.addWidget(self.spn_bin)
        self.chk_half = QCheckBox(tr('First bin half this size'))
        h_bin.addWidget(self.chk_half)
        h_bin.addStretch()
        f_left.addRow('Wind speed bin size:', h_bin)
        v_exp = QVBoxLayout()
        self.rb_occ = QRadioButton(tr('occurrences'))
        self.rb_freq = QRadioButton(tr('frequencies'))
        self.rb_freq.setChecked(True)
        v_exp.addWidget(self.rb_occ)
        v_exp.addWidget(self.rb_freq)
        f_left.addRow('Export:', v_exp)
        self.chk_seasonal = QCheckBox(tr('Remove seasonal bias'))
        f_left.addRow(self.chk_seasonal)
        top.addWidget(left, stretch=2)

        # Middle: common options
        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid, stretch=1)

        # Right: scale/offset/property
        right = QVBoxLayout()
        right.setSpacing(4)
        h_scale = QHBoxLayout()
        self.chk_scale = QCheckBox(tr('Scale to mean wind speed of'))
        self.spn_scale_target = QDoubleSpinBox()
        self.spn_scale_target.setRange(0.0, 30.0)
        self.spn_scale_target.setDecimals(2)
        self.spn_scale_target.setSuffix(' m/s')
        h_scale.addWidget(self.chk_scale)
        h_scale.addWidget(self.spn_scale_target)
        h_scale.addStretch()
        right.addLayout(h_scale)
        self.chk_offset = QCheckBox(tr('Offset directions clockwise'))
        right.addWidget(self.chk_offset)
        g_prop = QGroupBox(tr('Property'))
        v_prop = QVBoxLayout(g_prop)
        v_prop.setContentsMargins(4, 4, 4, 4)
        self.tbl_prop = QTableWidget()
        self.tbl_prop.setColumnCount(3)
        self.tbl_prop.setHorizontalHeaderLabels(
            ['Property', 'Time Series', 'TAB file'])
        self.tbl_prop.horizontalHeader().setStretchLastSection(True)
        self.tbl_prop.verticalHeader().setVisible(False)
        self.tbl_prop.setRowCount(2)
        self.tbl_prop.setItem(0, 0, QTableWidgetItem('Mean speed (m/s)'))
        self.tbl_prop.setItem(1, 0, QTableWidgetItem('Mean WPD (W/m2)'))
        self.tbl_prop.setMinimumHeight(100)
        v_prop.addWidget(self.tbl_prop)
        self.lbl_steps = QLabel(tr('Time steps in time series'))
        v_prop.addWidget(self.lbl_steps)
        right.addWidget(g_prop)
        right.addStretch()
        top.addLayout(right, stretch=1)

        lay.addLayout(top, stretch=2)

        # signals
        for w in (self.cmb_speed, self.cmb_dir, self.cmb_sectors):
            w.currentIndexChanged.connect(self._maybe_update)
        self.spn_bin.valueChanged.connect(self._maybe_update)
        self.chk_half.stateChanged.connect(self._maybe_update)
        self.rb_occ.toggled.connect(self._maybe_update)
        self.rb_freq.toggled.connect(self._maybe_update)
        self.chk_seasonal.stateChanged.connect(self._maybe_update)
        self.chk_scale.stateChanged.connect(self._maybe_update)
        self.spn_scale_target.valueChanged.connect(self._maybe_update)
        self.chk_offset.stateChanged.connect(self._maybe_update)
        self.common.connect_changed(self._maybe_update)
        self.common.chk_auto_preview.stateChanged.connect(
            lambda: self._maybe_update() if self.common.chk_auto_preview.isChecked() else None)

        self._update_preview()

    def _maybe_update(self):
        if self.common.chk_auto_preview.isChecked():
            self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text(preview=True))

    def _filtered(self):
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        return _filter_rows(self.ds, u, ic, inv, only_int, t0, t1)

    def _matrix_and_series(self):
        """返回 (H_counts, speed_edges, dir_mids, speed_series_aligned)。"""
        speed_col = self.cmb_speed.currentData()
        dir_col = self.cmb_dir.currentData()
        if not speed_col or not dir_col:
            return None
        sectors = int(self.cmb_sectors.currentText())
        bin_size = self.spn_bin.value()
        df = self._filtered()
        s = df[speed_col].dropna()
        d = df[dir_col].reindex(s.index).dropna()
        if len(d) == 0:
            return None
        s = s.reindex(d.index)
        # scale
        if self.chk_scale.isChecked():
            target = self.spn_scale_target.value()
            if s.mean() and s.mean() > 0:
                s = s * (target / s.mean())
        # offset directions clockwise
        if self.chk_offset.isChecked():
            offset = self.ds.attrs.get('dir_offset', 0.0)
            d = (d + offset) % 360.0
        max_speed = math.ceil(s.max() / bin_size) * bin_size
        if self.chk_half.isChecked():
            edges = [0.0, bin_size / 2.0]
            edges += list(np.arange(bin_size, max_speed + bin_size, bin_size))
        else:
            edges = list(np.arange(0.0, max_speed + bin_size, bin_size))
        dir_edges = _dir_sector_edges(sectors)
        H, _, _ = np.histogram2d(s, d, bins=[edges, dir_edges])

        # seasonal bias: 月均矩阵再平均
        if self.chk_seasonal.isChecked() and not df.empty:
            monthly = []
            for _, g in df.groupby([df.index.year, df.index.month]):
                gs = g[speed_col].dropna()
                gd = g[dir_col].reindex(gs.index).dropna()
                if len(gd) == 0:
                    continue
                gs = gs.reindex(gd.index)
                if self.chk_scale.isChecked() and gs.mean() and gs.mean() > 0:
                    gs = gs * (self.spn_scale_target.value() / gs.mean())
                if self.chk_offset.isChecked():
                    offset = self.ds.attrs.get('dir_offset', 0.0)
                    gd = (gd + offset) % 360.0
                Hm, _, _ = np.histogram2d(gs, gd, bins=[edges, dir_edges])
                monthly.append(Hm)
            if monthly:
                H = np.mean(monthly, axis=0)
        return H, np.array(edges), _dir_mid_sectors(sectors), s

    def _update_properties(self):
        speed_col = self.cmb_speed.currentData()
        r = self._matrix_and_series()
        if r is None or not speed_col:
            self.lbl_steps.setText('Time steps in time series 0')
            for i in range(2):
                for j in (1, 2):
                    self.tbl_prop.setItem(i, j, QTableWidgetItem(''))
            return
        H, edges, _, s = r
        rho = self.ds.attrs.get('air_density', 1.225)

        # Time series 统计（要求同时有 speed/dir）
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        df = _filter_rows(self.ds, u, ic, inv, only_int, t0, t1)
        dir_col = self.cmb_dir.currentData()
        valid = df[[speed_col, dir_col]].notna().all(axis=1)
        ts_speed = df.loc[valid, speed_col]
        ts_wpd = 0.5 * rho * (ts_speed ** 3)
        ts_mean_speed = ts_speed.mean()
        ts_mean_wpd = ts_wpd.mean()

        # TAB file 统计（用 occurrences 加权 bin 中点）
        mids = (edges[:-1] + edges[1:]) / 2.0
        if self.chk_half.isChecked():
            mids[0] = edges[1] / 4.0
        total_occ = H.sum()
        if total_occ > 0:
            tab_mean_speed = np.sum(mids * H.sum(axis=1)) / total_occ
            tab_mean_wpd = np.sum(0.5 * rho * (mids ** 3) * H.sum(axis=1)) / total_occ
        else:
            tab_mean_speed = np.nan
            tab_mean_wpd = np.nan

        vals = [
            (ts_mean_speed, tab_mean_speed),
            (ts_mean_wpd, tab_mean_wpd),
        ]
        for i, (ts_v, tab_v) in enumerate(vals):
            self.tbl_prop.setItem(
                i, 1, QTableWidgetItem('' if pd.isna(ts_v) else f'{ts_v:.3f}'))
            self.tbl_prop.setItem(
                i, 2, QTableWidgetItem('' if pd.isna(tab_v) else f'{tab_v:.1f}'))
        self.lbl_steps.setText(f'Time steps in time series {len(ts_speed)}')

    def generate_text(self, preview: bool = False) -> str:
        self._update_properties()
        r = self._matrix_and_series()
        if r is None:
            return '# Created by WindAnaly\n# No valid speed/direction data'
        H, speed_edges, dir_mids, _ = r
        speed_col = self.cmb_speed.currentData()
        dir_col = self.cmb_dir.currentData()
        sectors = int(self.cmb_sectors.currentText())
        lat = self.ds.attrs.get('latitude', 0.0)
        lon = self.ds.attrs.get('longitude', 0.0)
        h = _height_of(speed_col) or 0.0
        desc = (f'{self.ds.name}; speed={self.cmb_speed.currentText()}, '
                f'dir={self.cmb_dir.currentText()}')
        if self.chk_seasonal.isChecked():
            desc += ', seasonal bias removed'
        if self.chk_scale.isChecked():
            desc += f', scaled to {self.spn_scale_target.value():.2f} m/s'

        lines = [f'# {desc}']
        lines.append(f'{lat}\t{lon}\t{h}')
        lines.append(f'{sectors}\t1.00\t0.00')

        col_totals = H.sum(axis=0)
        grand = col_totals.sum()
        if grand > 0:
            overall_pct = col_totals / grand * 100.0
        else:
            overall_pct = np.zeros(sectors)
        lines.append('\t'.join([''] + [f'{v:.4f}' for v in overall_pct]))

        if self.rb_freq.isChecked():
            # 每扇区 per mille
            out = np.zeros_like(H)
            for c in range(sectors):
                if col_totals[c] > 0:
                    out[:, c] = H[:, c] / col_totals[c] * 1000.0
        else:
            out = H
        for i, row in enumerate(out):
            label = f'{speed_edges[i+1]:.1f}'
            vals = [f'{v:.6f}' for v in row]
            lines.append('\t'.join([label] + vals))
        return '\n'.join(lines)

    def do_export(self, parent):
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 WAsP .tab', f'{self.ds.name}.tab',
            'WAsP (*.tab);;All files (*.*)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text(preview=False))
        return True


# ---------------------------------------------------------------------------
# WindSim
# ---------------------------------------------------------------------------
class _WindSimTab(QWidget):
    def __init__(self, ds, preview, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)

        left = QGroupBox(tr('WindSim options'))
        f = QFormLayout(left)
        f.setSpacing(2)
        f.setContentsMargins(4, 4, 4, 4)
        h = QHBoxLayout()
        self.rb_wws = QRadioButton('WWS')
        self.rb_tws = QRadioButton('TWS')
        self.rb_wws.setChecked(True)
        h.addWidget(self.rb_wws)
        h.addWidget(self.rb_tws)
        h.addStretch()
        f.addRow('File type:', h)

        self.stack = QStackedWidget()
        # WWS page
        wws = QWidget()
        f_wws = QFormLayout(wws)
        f_wws.setContentsMargins(0, 0, 0, 0)
        f_wws.setSpacing(4)
        self.cmb_speed = QComboBox()
        for c in _speed_cols(self.ds):
            self.cmb_speed.addItem(_col_disp(self.ds, c), c)
        f_wws.addRow('Wind speed sensor:', self.cmb_speed)
        self.cmb_dir = QComboBox()
        for c in _dir_cols(self.ds):
            self.cmb_dir.addItem(_col_disp(self.ds, c), c)
        f_wws.addRow('Wind direction sensor:', self.cmb_dir)
        self.spn_bin = QDoubleSpinBox()
        self.spn_bin.setRange(0.1, 10.0)
        self.spn_bin.setValue(0.5)
        self.spn_bin.setDecimals(1)
        self.spn_bin.setSuffix(' m/s')
        f_wws.addRow('Speed bin size:', self.spn_bin)
        self.cmb_sectors = QComboBox()
        self.cmb_sectors.addItems(['8', '12', '16', '24', '36', '48'])
        self.cmb_sectors.setCurrentText('16')
        f_wws.addRow('Direction sectors:', self.cmb_sectors)
        self.stack.addWidget(wws)
        # TWS page
        tws = QWidget()
        f_tws = QFormLayout(tws)
        f_tws.setContentsMargins(0, 0, 0, 0)
        f_tws.setSpacing(4)
        self.cmb_speed_tws = QComboBox()
        for c in _speed_cols(self.ds):
            self.cmb_speed_tws.addItem(_col_disp(self.ds, c), c)
        f_tws.addRow('Wind speed sensor:', self.cmb_speed_tws)
        self.cmb_dir_tws = QComboBox()
        for c in _dir_cols(self.ds):
            self.cmb_dir_tws.addItem(_col_disp(self.ds, c), c)
        f_tws.addRow('Wind direction sensor:', self.cmb_dir_tws)
        v = QHBoxLayout()
        self.rb_old = QRadioButton(tr('WindSim 4.8 and earlier'))
        self.rb_new = QRadioButton(tr('WindSim 4.9 and later'))
        self.rb_new.setChecked(True)
        v.addWidget(self.rb_old)
        v.addWidget(self.rb_new)
        v.addStretch()
        f_tws.addRow('Target version:', v)
        self.stack.addWidget(tws)
        f.addRow(self.stack)
        top.addWidget(left, stretch=2)

        mid = QVBoxLayout()
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid, stretch=1)

        right = QVBoxLayout()
        right.addStretch()
        top.addLayout(right, stretch=1)

        lay.addLayout(top, stretch=2)

        self.rb_wws.toggled.connect(self._on_type_changed)
        self.rb_tws.toggled.connect(self._on_type_changed)
        for w in (self.cmb_speed, self.cmb_dir, self.cmb_sectors,
                  self.cmb_speed_tws, self.cmb_dir_tws):
            w.currentIndexChanged.connect(self._maybe_update)
        self.spn_bin.valueChanged.connect(self._maybe_update)
        self.rb_old.toggled.connect(self._maybe_update)
        self.rb_new.toggled.connect(self._maybe_update)
        self.common.connect_changed(self._maybe_update)
        self.common.chk_auto_preview.stateChanged.connect(
            lambda: self._maybe_update() if self.common.chk_auto_preview.isChecked() else None)

        self._on_type_changed()
        self._update_preview()

    def _on_type_changed(self):
        self.stack.setCurrentIndex(0 if self.rb_wws.isChecked() else 1)
        self._maybe_update()

    def _maybe_update(self):
        if self.common.chk_auto_preview.isChecked():
            self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text(preview=True))

    def _filtered(self):
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        return _filter_rows(self.ds, u, ic, inv, only_int, t0, t1)

    def generate_text(self, preview: bool = False) -> str:
        df = self._filtered()
        lat = self.ds.attrs.get('latitude', 0.0)
        lon = self.ds.attrs.get('longitude', 0.0)
        t0, t1 = (df.index[0], df.index[-1]) if not df.empty else (None, None)
        lines = []
        if self.rb_tws.isChecked():
            speed_col = self.cmb_speed_tws.currentData()
            dir_col = self.cmb_dir_tws.currentData()
            if not speed_col or not dir_col:
                return '# No speed/direction sensor selected'
            h = _height_of(speed_col) or 0.0
            lines.append('version\t:49')
            lines.append(f'site name\t:{self.ds.name}')
            if t0 and t1:
                lines.append(
                    f'measurement period\t:'
                    f'{t0.strftime("%d/%m/%Y %H:%M")} - '
                    f'{t1.strftime("%d/%m/%Y %H:%M")}')
            else:
                lines.append('measurement period\t:')
            lines.append(f'site position\t:{lon} {lat}')
            lines.append('coordinate system\t:3')
            lines.append(f'measurement height\t:{h}')
            lines.append('')
            lines.append(
                'rec nr:\tyear:\tmon:\tdate:\thour:\tmin:\tdir:\tspeed:\tSDspeed:')
            ch = self.ds.channels.get(speed_col)
            for i, (ts, row) in enumerate(df.iterrows(), 1):
                sp = row.get(speed_col, -1.0)
                dr = row.get(dir_col, -1.0)
                if pd.isna(sp):
                    sp = -1.0
                if pd.isna(dr):
                    dr = -1.0
                sds = -1.0
                if ch and ch.sd_col and ch.sd_col in df.columns:
                    v = row.get(ch.sd_col)
                    if not pd.isna(v):
                        sds = v
                lines.append(
                    f'{i}\t{ts.year:04d}\t{ts.month:02d}\t{ts.day:02d}\t'
                    f'{ts.hour:02d}\t{ts.minute:02d}\t{dr:.1f}\t{sp:.3f}\t'
                    f'{sds:.3f}')
                if preview and len(lines) > 35:
                    lines.append('# ... (preview truncated)')
                    break
        else:
            speed_col = self.cmb_speed.currentData()
            dir_col = self.cmb_dir.currentData()
            if not speed_col or not dir_col:
                return '# No speed/direction sensor selected'
            sectors = int(self.cmb_sectors.currentText())
            bin_size = self.spn_bin.value()
            s = df[speed_col].dropna()
            d = df[dir_col].reindex(s.index).dropna()
            if len(d) == 0:
                return '# No valid speed/direction data'
            s = s.reindex(d.index)
            max_speed = math.ceil(s.max() / bin_size) * bin_size
            edges = list(np.arange(0.0, max_speed + bin_size, bin_size))
            dir_edges = _dir_sector_edges(sectors)
            H, _, _ = np.histogram2d(s, d, bins=[edges, dir_edges])
            total = H.sum()
            freq = H / total if total > 0 else H
            h = _height_of(speed_col) or 0.0
            lines.append('version\t:43')
            lines.append(f'site name\t:{self.ds.name}')
            if t0 and t1:
                lines.append(
                    f'measurement period\t:'
                    f'{_format_period(t0, t1)}')
            else:
                lines.append('measurement period\t:')
            lines.append(f'site position\t:{lon} {lat}')
            lines.append('coordinate system\t:3')
            lines.append(f'measurement height\t:{h}')
            lines.append(f'number of sectors\t:{sectors}')
            lines.append(f'number of bins\t:{len(edges) - 1}')
            lines.append(f'total records\t:{len(df)}')
            lines.append('')
            lines.append(
                '\t'.join([''] + [str(int(x)) for x in _dir_mid_sectors(sectors)]))
            for i, row in enumerate(freq):
                lines.append(
                    '\t'.join([f'{edges[i]:.1f}'] + [f'{v:.6f}' for v in row]))
        return '\n'.join(lines)

    def do_export(self, parent):
        ext = '.tws' if self.rb_tws.isChecked() else '.wws'
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 WindSim', f'{self.ds.name}{ext}',
            f'WindSim (*{ext});;All files (*.*)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text(preview=False))
        return True


# ---------------------------------------------------------------------------
# Meteodyn WT
# ---------------------------------------------------------------------------
class _MeteodynWTTab(QWidget):
    def __init__(self, ds, preview, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self._factor = 1.0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)

        left = QGroupBox(tr('Meteodyn WT options'))
        f = QFormLayout(left)
        f.setSpacing(2)
        f.setContentsMargins(4, 4, 4, 4)
        self.cmb_speed = QComboBox()
        for c in _speed_cols(self.ds):
            self.cmb_speed.addItem(_col_disp(self.ds, c), c)
        f.addRow('Wind speed sensor:', self.cmb_speed)
        self.cmb_dir = QComboBox()
        for c in _dir_cols(self.ds):
            self.cmb_dir.addItem(_col_disp(self.ds, c), c)
        f.addRow('Wind direction sensor:', self.cmb_dir)
        self.chk_maintain = QCheckBox(tr('Maintain constant wind speed'))
        self.chk_maintain.stateChanged.connect(self._maybe_update)
        f.addRow(self.chk_maintain)
        self.lbl_factor = QLabel('')
        f.addRow(self.lbl_factor)
        top.addWidget(left, stretch=2)

        mid = QVBoxLayout()
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid, stretch=1)

        right = QVBoxLayout()
        right.addStretch()
        top.addLayout(right, stretch=1)

        lay.addLayout(top, stretch=2)

        for w in (self.cmb_speed, self.cmb_dir):
            w.currentIndexChanged.connect(self._maybe_update)
        self.common.connect_changed(self._maybe_update)
        self.common.chk_auto_preview.stateChanged.connect(
            lambda: self._maybe_update() if self.common.chk_auto_preview.isChecked() else None)
        self._update_preview()

    def _maybe_update(self):
        if self.common.chk_auto_preview.isChecked():
            self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text(preview=True))

    def generate_text(self, preview: bool = False) -> str:
        speed_col = self.cmb_speed.currentData()
        dir_col = self.cmb_dir.currentData()
        if not speed_col or not dir_col:
            return '# Please select wind speed and direction sensors'
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        df0 = _filter_rows(self.ds, u, ic, inv, only_int, t0, t1,
                           row_valid_mode='all')
        df = df0.dropna(subset=[speed_col, dir_col]).copy()
        if df.empty:
            return '# No data'
        orig_mean = df0[speed_col].mean()
        self._factor = 1.0
        if self.chk_maintain.isChecked() and not pd.isna(orig_mean):
            filt_mean = df[speed_col].mean()
            if filt_mean and filt_mean > 0:
                self._factor = orig_mean / filt_mean
                df[speed_col] = df[speed_col] * self._factor
        self.lbl_factor.setText(
            f'Scaling factor: {self._factor:.4f}'
            if self.chk_maintain.isChecked() else '')

        ch = self.ds.channels.get(speed_col)
        lines = []
        for ts, row in df.iterrows():
            sp = row[speed_col]
            dr = row[dir_col]
            vals = [f'{sp:.2f}', f'{dr:.1f}']
            if ch and ch.sd_col and ch.sd_col in df.columns:
                sdv = row.get(ch.sd_col)
                vals.append('' if pd.isna(sdv) else f'{sdv:.2f}')
            vals.extend([ts.strftime('%H:%M:%S'), ts.strftime('%d-%m-%Y')])
            lines.append(' '.join(vals))
            if preview and len(lines) > 30:
                lines.append('# ...')
                break
        return '\n'.join(lines)

    def do_export(self, parent):
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 Meteodyn WT', f'{self.ds.name}.tim',
            'Meteodyn WT (*.tim);;All files (*.*)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text(preview=False))
        return True


# ---------------------------------------------------------------------------
# Openwind
# ---------------------------------------------------------------------------
class _OpenwindTab(QWidget):
    def __init__(self, ds, preview, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)

        left = QGroupBox(tr('Openwind options'))
        f = QFormLayout(left)
        f.setSpacing(2)
        f.setContentsMargins(4, 4, 4, 4)
        h = QHBoxLayout()
        self.rb_single = QRadioButton(tr('single height'))
        self.rb_multi = QRadioButton(tr('multiple heights'))
        self.rb_single.setChecked(True)
        h.addWidget(self.rb_single)
        h.addWidget(self.rb_multi)
        h.addStretch()
        f.addRow('Export:', h)

        self.stack = QStackedWidget()
        # single page
        single = QWidget()
        f_single = QFormLayout(single)
        f_single.setContentsMargins(0, 0, 0, 0)
        f_single.setSpacing(4)
        self.cmb_speed = QComboBox()
        for c in _speed_cols(self.ds):
            self.cmb_speed.addItem(_col_disp(self.ds, c), c)
        f_single.addRow('Wind speed sensor:', self.cmb_speed)
        self.cmb_dir = QComboBox()
        for c in _dir_cols(self.ds):
            self.cmb_dir.addItem(_col_disp(self.ds, c), c)
        f_single.addRow('Wind direction sensor:', self.cmb_dir)
        self.stack.addWidget(single)
        # multi page
        multi = QWidget()
        v_multi = QVBoxLayout(multi)
        v_multi.setSpacing(4)
        v_multi.setContentsMargins(0, 0, 0, 0)
        info = QLabel(
            tr('To export multiple heights the data set must contain speed, TI, '
            'direction, and temperature columns at each height. Use the Vertical '
            'Extrapolation window to generate one or more such columns.'))
        info.setWordWrap(True)
        v_multi.addWidget(info)
        self.lst_heights = QListWidget()
        self.lst_heights.setMinimumWidth(180)
        v_multi.addWidget(self.lst_heights)
        self.lbl_warn = QLabel('')
        self.lbl_warn.setStyleSheet('color: red')
        v_multi.addWidget(self.lbl_warn)
        self.stack.addWidget(multi)
        f.addRow(self.stack)
        top.addWidget(left, stretch=2)

        mid = QVBoxLayout()
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid, stretch=1)

        right = QVBoxLayout()
        right.setSpacing(4)
        g_scale = QGroupBox()
        h_scale = QHBoxLayout(g_scale)
        h_scale.setSpacing(2)
        h_scale.setContentsMargins(4, 4, 4, 4)
        self.chk_scale = QCheckBox(tr('Scale speeds so'))
        self.cmb_scale_sensor = QComboBox()
        for c in _speed_cols(self.ds):
            self.cmb_scale_sensor.addItem(_col_disp(self.ds, c), c)
        self.spn_scale_target = QDoubleSpinBox()
        self.spn_scale_target.setRange(0.0, 30.0)
        self.spn_scale_target.setValue(5.0)
        self.spn_scale_target.setDecimals(2)
        self.spn_scale_target.setSuffix(' m/s')
        h_scale.addWidget(self.chk_scale)
        h_scale.addWidget(self.cmb_scale_sensor)
        h_scale.addWidget(QLabel(tr('has a mean speed of')))
        h_scale.addWidget(self.spn_scale_target)
        h_scale.addStretch()
        right.addWidget(g_scale)
        g_prop = QGroupBox(tr('Properties of exported data'))
        v_prop = QVBoxLayout(g_prop)
        v_prop.setContentsMargins(4, 4, 4, 4)
        self.tbl_prop = QTableWidget()
        self.tbl_prop.setColumnCount(2)
        self.tbl_prop.setHorizontalHeaderLabels(['', ''])
        self.tbl_prop.horizontalHeader().setVisible(False)
        self.tbl_prop.verticalHeader().setVisible(False)
        self.tbl_prop.setRowCount(3)
        self.tbl_prop.setItem(0, 0, QTableWidgetItem('Valid speed values:'))
        self.tbl_prop.setItem(1, 0, QTableWidgetItem('Mean speed @ 0 m'))
        self.tbl_prop.setItem(2, 0, QTableWidgetItem('Scaling factor:'))
        self.tbl_prop.setMinimumHeight(90)
        v_prop.addWidget(self.tbl_prop)
        right.addWidget(g_prop)
        right.addStretch()
        top.addLayout(right, stretch=1)

        lay.addLayout(top, stretch=2)

        self.rb_single.toggled.connect(self._on_mode_changed)
        self.rb_multi.toggled.connect(self._on_mode_changed)
        for w in (self.cmb_speed, self.cmb_dir, self.cmb_scale_sensor):
            w.currentIndexChanged.connect(self._maybe_update)
        self.chk_scale.stateChanged.connect(self._maybe_update)
        self.spn_scale_target.valueChanged.connect(self._maybe_update)
        self.lst_heights.itemChanged.connect(self._maybe_update)
        self.common.connect_changed(self._maybe_update)
        self.common.chk_auto_preview.stateChanged.connect(
            lambda: self._maybe_update() if self.common.chk_auto_preview.isChecked() else None)

        self._populate_heights()
        self._on_mode_changed()
        self._update_preview()

    def _populate_heights(self):
        self.lst_heights.clear()
        seen = set()
        for c in _speed_cols(self.ds):
            h = _height_of(c)
            if h is None or h in seen:
                continue
            seen.add(h)
            item = QListWidgetItem(f'{h} m')
            item.setData(Qt.UserRole, h)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.lst_heights.addItem(item)

    def _selected_heights(self) -> list[float]:
        heights = []
        for i in range(self.lst_heights.count()):
            item = self.lst_heights.item(i)
            if item.checkState() == Qt.Checked:
                heights.append(item.data(Qt.UserRole))
        return heights

    def _on_mode_changed(self):
        self.stack.setCurrentIndex(0 if self.rb_single.isChecked() else 1)
        self._maybe_update()

    def _maybe_update(self):
        if self.common.chk_auto_preview.isChecked():
            self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text(preview=True))

    def _cols_for_height(self, height: float):
        """返回 (speed_col, dir_col, temp_col, dens_col, ti_col)。"""
        speed_col = dir_col = temp_col = dens_col = ti_col = None
        for c in self.ds.df.columns:
            ch = self.ds.channels.get(c)
            if ch is None or ch.height != height:
                continue
            if speed_col is None and ch.kind == 'speed':
                speed_col = c
            elif dir_col is None and ch.kind == 'dir':
                dir_col = c
            elif temp_col is None and (ch.kind in ('temp', 'temperature') or
                                       (ch.units and 'C' in ch.units.upper())):
                temp_col = c
            elif dens_col is None and (ch.kind in ('density', 'rho') or
                                       (ch.units and 'kg' in ch.units.lower())):
                dens_col = c
            elif ti_col is None and ch.kind in ('ti', 'turbulence'):
                ti_col = c
        # 回退任意列
        if temp_col is None:
            temp_col, dens_col, ti_col = _find_aux_cols(self.ds, None)
        return speed_col, dir_col, temp_col, dens_col, ti_col

    def _scale_factor(self, df: pd.DataFrame) -> float:
        sf = 1.0
        if self.chk_scale.isChecked():
            sc = self.cmb_scale_sensor.currentData()
            if sc and sc in df.columns:
                m = df[sc].mean()
                if m and m > 0:
                    sf = self.spn_scale_target.value() / m
        return sf

    def _update_properties(self, valid_count: int, mean_speed: float,
                           sf: float, height: float):
        self.tbl_prop.setItem(0, 1, QTableWidgetItem(f'{valid_count}'))
        self.tbl_prop.setItem(
            1, 0, QTableWidgetItem(f'Mean speed @ {height:.0f} m'))
        self.tbl_prop.setItem(
            1, 1, QTableWidgetItem(f'{mean_speed:.3f}'))
        self.tbl_prop.setItem(2, 1, QTableWidgetItem(f'{sf:.3f}'))

    def generate_text(self, preview: bool = False) -> str:
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        df = _filter_rows(self.ds, u, ic, inv, only_int, t0, t1)
        if df.empty:
            return '# No data'
        lat = self.ds.attrs.get('latitude', 0.0)
        lon = self.ds.attrs.get('longitude', 0.0)
        elev = self.ds.attrs.get('elevation', 0.0)

        if self.rb_single.isChecked():
            speed_col = self.cmb_speed.currentData()
            dir_col = self.cmb_dir.currentData()
            if not speed_col or not dir_col:
                return '# Select speed/direction sensors'
            h = _height_of(speed_col) or 0.0
            temp_col, dens_col, ti_col = _find_aux_cols(self.ds, h)
            sf = self._scale_factor(df)
            valid = df[[speed_col, dir_col]].notna().all(axis=1)
            self._update_properties(
                int(valid.sum()), df.loc[valid, speed_col].mean() * sf, sf, h)
            lines = ['MM,1', f'{lon},{lat},{elev}',
                     f'0,{self.ds.name},{self.ds.name}']
            header = ['Year', 'Month', 'Day', 'Hour', 'Minute',
                      f'{speed_col} [m/s]', f'{dir_col} [deg]']
            aux = []
            if temp_col:
                aux.append((temp_col, '[°C]'))
            if dens_col:
                aux.append((dens_col, '[kg/m3]'))
            if ti_col:
                aux.append((ti_col, '[TI]'))
            for col, unit in aux:
                header.append(f'{col} {unit}')
            lines.append(','.join(header))
            for ts, row in df.iterrows():
                sp = row.get(speed_col)
                dr = row.get(dir_col)
                if pd.isna(sp) or pd.isna(dr):
                    continue
                vals = [f'{ts.year:04d}', f'{ts.month:02d}', f'{ts.day:02d}',
                        f'{ts.hour:02d}', f'{ts.minute:02d}',
                        f'{sp * sf:.3f}', f'{dr:.1f}']
                for col, _ in aux:
                    v = row.get(col)
                    vals.append('-999' if pd.isna(v) else f'{v:.3f}')
                lines.append(','.join(vals))
                if preview and len(lines) > 30:
                    lines.append('# ...')
                    break
            return '\n'.join(lines)

        # multiple heights
        heights = self._selected_heights()
        if not heights:
            self.lbl_warn.setText(
                tr('You must select at least one measurement height to export an MM2 file.'))
            return ''
        self.lbl_warn.setText('')
        lines = ['MM,2']
        for h in heights:
            speed_col, dir_col, temp_col, dens_col, ti_col = self._cols_for_height(h)
            if not speed_col or not dir_col:
                continue
            sf = self._scale_factor(df)
            cols = [speed_col, dir_col]
            for c in (temp_col, dens_col, ti_col):
                if c:
                    cols.append(c)
            lines.append(f'# Height {h} m')
            for ts, row in df.iterrows():
                if any(pd.isna(row.get(c)) for c in cols):
                    continue
                vals = [f'{ts.year:04d}', f'{ts.month:02d}', f'{ts.day:02d}',
                        f'{ts.hour:02d}', f'{ts.minute:02d}', f'{h:.1f}']
                for c in cols:
                    v = row.get(c)
                    if c == speed_col:
                        vals.append(f'{v * sf:.3f}')
                    elif c == dir_col:
                        vals.append(f'{v:.1f}')
                    else:
                        vals.append(f'{v:.3f}')
                lines.append(','.join(vals))
                if preview and len(lines) > 30:
                    lines.append('# ...')
                    return '\n'.join(lines)
        return '\n'.join(lines)

    def do_export(self, parent):
        ext = '.mm2' if self.rb_multi.isChecked() else '.txt'
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 Openwind', f'{self.ds.name}{ext}',
            f'Openwind (*{ext});;All files (*.*)')
        if not path:
            return False
        if self.rb_multi.isChecked() and not self._selected_heights():
            QMessageBox.warning(
                parent, tr('导出失败'),
                'Please select at least one measurement height for MM2 export.')
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text(preview=False))
        return True


# ---------------------------------------------------------------------------
# WindFarmer
# ---------------------------------------------------------------------------
class _WindFarmerTab(QWidget):
    def __init__(self, ds, preview, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)

        left = QGroupBox(tr('WindFarmer options'))
        f = QFormLayout(left)
        f.setSpacing(2)
        f.setContentsMargins(4, 4, 4, 4)
        self.cmb_speed = QComboBox()
        for c in _speed_cols(self.ds):
            self.cmb_speed.addItem(_col_disp(self.ds, c), c)
        f.addRow('Wind speed sensor:', self.cmb_speed)
        self.cmb_dir = QComboBox()
        for c in _dir_cols(self.ds):
            self.cmb_dir.addItem(_col_disp(self.ds, c), c)
        f.addRow('Wind direction sensor:', self.cmb_dir)
        self.cmb_sectors = QComboBox()
        self.cmb_sectors.addItems(['8', '12', '16', '24', '36', '48'])
        self.cmb_sectors.setCurrentText('16')
        f.addRow('Wind direction sectors:', self.cmb_sectors)
        top.addWidget(left, stretch=2)

        mid = QVBoxLayout()
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid, stretch=1)

        right = QVBoxLayout()
        right.addStretch()
        top.addLayout(right, stretch=1)
        lay.addLayout(top, stretch=2)


        for w in (self.cmb_speed, self.cmb_dir, self.cmb_sectors):
            w.currentIndexChanged.connect(self._maybe_update)
        self.common.connect_changed(self._maybe_update)
        self.common.chk_auto_preview.stateChanged.connect(
            lambda: self._maybe_update() if self.common.chk_auto_preview.isChecked() else None)
        self._update_preview()

    def _maybe_update(self):
        if self.common.chk_auto_preview.isChecked():
            self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text(preview=True))

    def _filtered(self):
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        return _filter_rows(self.ds, u, ic, inv, only_int, t0, t1)

    def generate_text(self, preview: bool = False) -> str:
        speed_col = self.cmb_speed.currentData()
        dir_col = self.cmb_dir.currentData()
        if not speed_col or not dir_col:
            return '# Select speed/direction sensors'
        ch = self.ds.channels.get(speed_col)
        sd_col = ch.sd_col if ch else None
        ti_col = None
        if not sd_col or sd_col not in self.ds.df.columns:
            h = _height_of(speed_col)
            for c in self.ds.df.columns:
                ch2 = self.ds.channels.get(c)
                if ch2 and ch2.kind in ('ti', 'turbulence') and ch2.height == h:
                    ti_col = c
                    break
            if not ti_col:
                return '# Need standard deviation or turbulence intensity column'

        sectors = int(self.cmb_sectors.currentText())
        df = self._filtered()
        s = df[speed_col].dropna()
        d = df[dir_col].reindex(s.index).dropna()
        s = s.reindex(d.index)
        if len(d) == 0:
            return '# No data'

        if sd_col and sd_col in df.columns:
            sd = df[sd_col].reindex(d.index)
            ti = (sd / s) * 100.0
        else:
            ti = df[ti_col].reindex(d.index) * 100.0
            sd = None

        max_speed = math.ceil(s.max())
        uppers = [0.5] + [i + 0.5 for i in range(1, int(max_speed) + 1)]
        edges = [0.0] + uppers
        dir_edges = _dir_sector_edges(sectors)
        n_bins = len(uppers)

        speed_idx = np.digitize(s.values, edges) - 1
        dir_idx = np.digitize(d.values, dir_edges) - 1
        speed_idx = np.clip(speed_idx, 0, n_bins - 1)
        dir_idx = np.clip(dir_idx, 0, sectors - 1)

        cells_ti = [[[] for _ in range(sectors)] for _ in range(n_bins)]
        cells_sd = [[[] for _ in range(sectors)] for _ in range(n_bins)]
        for i in range(len(s)):
            si = speed_idx[i]
            di = dir_idx[i]
            v = ti.iloc[i]
            if not pd.isna(v):
                cells_ti[si][di].append(v)
            if sd is not None:
                sv = sd.iloc[i]
                if not pd.isna(sv):
                    cells_sd[si][di].append(sv)

        def fill_table(cells, use_sd=False):
            arr = np.full((n_bins, sectors), np.nan)
            for si in range(n_bins):
                for di in range(sectors):
                    vals = cells[si][di]
                    if len(vals) >= 5:
                        arr[si, di] = np.mean(vals)
                    else:
                        all_vals = [v for d in range(sectors) for v in cells[si][d]]
                        if len(all_vals) >= 5:
                            arr[si, di] = np.mean(all_vals)
                        else:
                            overall = [v for si2 in range(n_bins)
                                       for d in range(sectors) for v in cells[si2][d]]
                            if overall:
                                arr[si, di] = np.mean(overall)
            return arr

        mean_ti = fill_table(cells_ti)
        sd_table = fill_table(cells_sd, use_sd=True) if sd is not None else np.zeros((n_bins, sectors))
        counts = np.array([[len(cells_ti[si][di]) for di in range(sectors)]
                           for si in range(n_bins)])

        lines = [f'#Created {datetime.now().strftime("%Y/%m/%d %H:%M")} by WindAnaly',
                 str(sectors)]
        for si in range(n_bins):
            lines.append('\t'.join(
                [str(si + 1)] +
                [f'{v:.4f}' if not np.isnan(v) else '0.0000' for v in mean_ti[si]]))
        lines.append('')
        for si in range(n_bins):
            lines.append('\t'.join(
                [str(si + 1)] +
                [f'{v:.4f}' if not np.isnan(v) else '0.0000' for v in sd_table[si]]))
        lines.append('')
        for si in range(n_bins):
            lines.append('\t'.join(
                [str(si + 1)] + [str(int(v)) for v in counts[si]]))
        return '\n'.join(lines)

    def do_export(self, parent):
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 WindFarmer', f'{self.ds.name}.wti',
            'WindFarmer (*.wti);;All files (*.*)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text(preview=False))
        return True


# ---------------------------------------------------------------------------
# EPE
# ---------------------------------------------------------------------------
class _EPETab(QWidget):
    def __init__(self, ds, preview, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        left = QGroupBox(tr('EPE options'))
        f = QFormLayout(left)
        f.setSpacing(2)
        f.setContentsMargins(4, 4, 4, 4)
        self.cmb_upper_spd = QComboBox()
        self.cmb_mid_spd = QComboBox()
        self.cmb_lower_spd = QComboBox()
        for c in _speed_cols(self.ds):
            for cb in (self.cmb_upper_spd, self.cmb_mid_spd, self.cmb_lower_spd):
                cb.addItem(_col_disp(self.ds, c), c)
        f.addRow('Upper anemometer:', self.cmb_upper_spd)
        f.addRow('Middle anemometer:', self.cmb_mid_spd)
        f.addRow('Lower anemometer:', self.cmb_lower_spd)
        self.cmb_upper_dir = QComboBox()
        self.cmb_lower_dir = QComboBox()
        for c in _dir_cols(self.ds):
            self.cmb_upper_dir.addItem(_col_disp(self.ds, c), c)
            self.cmb_lower_dir.addItem(_col_disp(self.ds, c), c)
        f.addRow('Upper wind vane:', self.cmb_upper_dir)
        f.addRow('Lower wind vane:', self.cmb_lower_dir)
        top.addWidget(left, stretch=2)

        mid = QVBoxLayout()
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid, stretch=1)

        right = QVBoxLayout()
        right.addStretch()
        top.addLayout(right, stretch=1)
        lay.addLayout(top, stretch=2)


        for w in (self.cmb_upper_spd, self.cmb_mid_spd, self.cmb_lower_spd,
                  self.cmb_upper_dir, self.cmb_lower_dir):
            w.currentIndexChanged.connect(self._maybe_update)
        self.common.connect_changed(self._maybe_update)
        self.common.chk_auto_preview.stateChanged.connect(
            lambda: self._maybe_update() if self.common.chk_auto_preview.isChecked() else None)
        self._update_preview()

    def _maybe_update(self):
        if self.common.chk_auto_preview.isChecked():
            self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text(preview=True))

    def generate_text(self, preview: bool = False) -> str:
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        df = _filter_rows(self.ds, u, ic, inv, only_int, t0, t1)
        lines = ['# EPE export by WindAnaly', f'# Site: {self.ds.name}',
                 f'# Start {df.index[0] if not df.empty else ""}',
                 f'# End {df.index[-1] if not df.empty else ""}', '']
        cols = []
        names = []
        for label, cb in (('upper', self.cmb_upper_spd),
                          ('middle', self.cmb_mid_spd),
                          ('lower', self.cmb_lower_spd),
                          ('upper_vane', self.cmb_upper_dir),
                          ('lower_vane', self.cmb_lower_dir)):
            c = cb.currentData()
            if c:
                cols.append(c)
                names.append(label)
        lines.append('# ' + '\t'.join(names))
        for ts, row in df.iterrows():
            vals = []
            for c in cols:
                v = row.get(c)
                vals.append('' if pd.isna(v) else f'{v:.2f}')
            lines.append('\t'.join(vals))
            if preview and len(lines) > 30:
                lines.append('# ...')
                break
        return '\n'.join(lines)

    def do_export(self, parent):
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 EPE', f'{self.ds.name}.txt',
            'EPE (*.txt);;All files (*.*)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text(preview=False))
        return True


# ---------------------------------------------------------------------------
# MGM
# ---------------------------------------------------------------------------
class _MGMTab(QWidget):
    def __init__(self, ds, preview, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        left = QGroupBox(tr('MGM options'))
        f = QFormLayout(left)
        f.setSpacing(2)
        f.setContentsMargins(4, 4, 4, 4)
        self.edit_station = QLineEdit('000000')
        f.addRow('Station number:', self.edit_station)
        self.cmb_interval = QComboBox()
        self.cmb_interval.addItems(['10 minutes', 'Hourly', 'Daily'])
        f.addRow('Data interval:', self.cmb_interval)
        top.addWidget(left, stretch=2)

        mid = QVBoxLayout()
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid, stretch=1)

        right = QVBoxLayout()
        right.addStretch()
        top.addLayout(right, stretch=1)
        lay.addLayout(top, stretch=2)


        self.edit_station.textChanged.connect(self._maybe_update)
        self.cmb_interval.currentIndexChanged.connect(self._maybe_update)
        self.common.connect_changed(self._maybe_update)
        self.common.chk_auto_preview.stateChanged.connect(
            lambda: self._maybe_update() if self.common.chk_auto_preview.isChecked() else None)
        self._update_preview()

    def _maybe_update(self):
        if self.common.chk_auto_preview.isChecked():
            self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text(preview=True))

    def generate_text(self, preview: bool = False) -> str:
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        df = _filter_rows(self.ds, u, ic, inv, only_int, t0, t1)
        stn = self.edit_station.text() or '000000'
        lines = [f'# MGM export by WindAnaly', f'# Station {stn}',
                 f'# {df.index[0] if not df.empty else ""} - '
                 f'{df.index[-1] if not df.empty else ""}', '']
        spd_cols = _speed_cols(self.ds)
        dir_cols = _dir_cols(self.ds)
        spd_col = spd_cols[0] if spd_cols else None
        dir_col = dir_cols[0] if dir_cols else None
        if not spd_col or not dir_col:
            return '# No speed/direction sensor'
        for ts, row in df.iterrows():
            sp = row.get(spd_col, -8888.0)
            dr = row.get(dir_col, -8888.0)
            if pd.isna(sp):
                sp = -8888.0
            if pd.isna(dr):
                dr = -8888.0
            lines.append(f'{stn}\t{ts.year:04d}\t{ts.month:02d}\t'
                         f'{ts.day:02d}\t{ts.hour:02d}\t{ts.minute:02d}\t'
                         f'{sp:.1f}\t{dr:.1f}')
            if preview and len(lines) > 30:
                lines.append('# ...')
                break
        return '\n'.join(lines)

    def do_export(self, parent):
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 MGM', f'{self.ds.name}.txt',
            'MGM (*.txt);;All files (*.*)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text(preview=False))
        return True


# ---------------------------------------------------------------------------
# SAM
# ---------------------------------------------------------------------------
class _SAMTab(QWidget):
    def __init__(self, ds, preview, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        left = QGroupBox(tr('Select data columns to export'))
        v = QVBoxLayout(left)
        v.setSpacing(2)
        v.setContentsMargins(4, 4, 4, 4)
        self.chk_all = QCheckBox(tr('Select all'))
        self.chk_all.setChecked(True)
        v.addWidget(self.chk_all)
        self.lst_cols = QListWidget()
        self.lst_cols.setMinimumWidth(220)
        for c in self.ds.df.columns:
            item = QListWidgetItem(_col_disp(self.ds, c))
            item.setData(Qt.UserRole, c)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.lst_cols.addItem(item)
        v.addWidget(self.lst_cols)
        top.addWidget(left, stretch=1)

        mid = QVBoxLayout()
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid, stretch=1)

        right = QVBoxLayout()
        right.addStretch()
        top.addLayout(right, stretch=1)
        lay.addLayout(top, stretch=2)


        self.chk_all.stateChanged.connect(self._toggle_all)
        self.lst_cols.itemChanged.connect(self._maybe_update)
        self.common.connect_changed(self._maybe_update)
        self.common.chk_auto_preview.stateChanged.connect(
            lambda: self._maybe_update() if self.common.chk_auto_preview.isChecked() else None)
        self._update_preview()

    def _toggle_all(self, state):
        for i in range(self.lst_cols.count()):
            self.lst_cols.item(i).setCheckState(
                Qt.Checked if state == Qt.Checked.value else Qt.Unchecked)
        self._maybe_update()

    def _maybe_update(self):
        if self.common.chk_auto_preview.isChecked():
            self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text(preview=True))

    def _selected_cols(self):
        cols = []
        for i in range(self.lst_cols.count()):
            item = self.lst_cols.item(i)
            if item.checkState() == Qt.Checked:
                cols.append(item.data(Qt.UserRole))
        return cols

    def generate_text(self, preview: bool = False) -> str:
        cols = self._selected_cols()
        if not cols:
            return '# No columns selected'
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        df = _filter_rows(self.ds, u, ic, inv, only_int, t0, t1)
        lines = ['# SAM export by WindAnaly', f'# {self.ds.name}', '']
        lines.append(','.join(['Date', 'Time'] + cols))
        for ts, row in df.iterrows():
            vals = [ts.strftime('%Y-%m-%d'), ts.strftime('%H:%M')]
            for c in cols:
                v = row.get(c)
                vals.append('' if pd.isna(v) else str(v))
            lines.append(','.join(vals))
            if preview and len(lines) > 30:
                lines.append('# ...')
                break
        return '\n'.join(lines)

    def do_export(self, parent):
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 SAM', f'{self.ds.name}.csv',
            'SAM (*.csv);;All files (*.*)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text(preview=False))
        return True


# ---------------------------------------------------------------------------
# XML Metadata
# ---------------------------------------------------------------------------
class _XMLMetadataTab(QWidget):
    def __init__(self, ds, preview, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        g = QGroupBox(tr('XML Metadata'))
        v = QVBoxLayout(g)
        v.setContentsMargins(4, 4, 4, 4)
        lbl = QLabel(tr('This file describes the data set and its data columns, '
                     'but contains no time series data.'))
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.btn_update = QPushButton(tr('Update Preview'))
        self.btn_update.clicked.connect(self._update_preview)
        v.addWidget(self.btn_update)
        lay.addWidget(g)
        self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text())

    def generate_text(self) -> str:
        root = Element('windographerxml', {
            'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'xsi:noNamespaceSchemaLocation': 'windographerxml1.xsd',
            'version': '1.0',
        })
        md = SubElement(root, 'metadata')
        SubElement(md, 'site_name').text = self.ds.name
        SubElement(md, 'site_description').text = self.ds.description
        SubElement(md, 'latitude').text = str(self.ds.attrs.get('latitude', ''))
        SubElement(md, 'longitude').text = str(self.ds.attrs.get('longitude', ''))
        SubElement(md, 'elevation').text = str(self.ds.attrs.get('elevation', ''))
        if not self.ds.df.empty:
            SubElement(md, 'POR_start').text = self.ds.df.index[0].strftime('%Y-%m-%dT%H:%M:%S')
            SubElement(md, 'POR_end').text = self.ds.df.index[-1].strftime('%Y-%m-%dT%H:%M:%S')
        for c in self.ds.channels.values():
            dc = SubElement(md, 'data_column')
            SubElement(dc, 'label').text = c.name
            SubElement(dc, 'type').text = c.kind.upper()
            SubElement(dc, 'units').text = c.units
            SubElement(md, 'height').text = str(c.height if c.height is not None else '')
            SubElement(dc, 'color').text = c.color or '16367522'
            SubElement(dc, 'visible').text = 'yes'
            cal = SubElement(dc, 'calibration_period')
            SubElement(cal, 'start_time').text = ''
            SubElement(cal, 'serial_no').text = ''
            SubElement(cal, 'scale').text = '1'
        raw = tostring(root, encoding='unicode')
        return raw

    def do_export(self, parent):
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 XML Metadata', f'{self.ds.name}.xml',
            'XML (*.xml);;All files (*.*)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text())
        return True


# ---------------------------------------------------------------------------
# 主对话框
# ---------------------------------------------------------------------------
class ExportDataDialog(QDialog):
    """导出数据主对话框。"""

    _TABS = [
        ('Time Series', _TimeSeriesTab),
        ('WAsP .tab', _WasPTab),
        ('WindSim', _WindSimTab),
        ('Meteodyn WT', _MeteodynWTTab),
        ('Openwind', _OpenwindTab),
        ('WindFarmer', _WindFarmerTab),
        ('EPE', _EPETab),
        ('MGM', _MGMTab),
        ('SAM', _SAMTab),
        ('XML Metadata', _XMLMetadataTab),
    ]

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.setWindowTitle(tr('Export Data'))
        self.resize(1000, 700)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self.tabs = QTabWidget()
        self._tab_widgets = []
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont('Consolas', 9))
        for title, cls in self._TABS:
            w = cls(self.ds, self.preview)
            self.tabs.addTab(w, title)
            self._tab_widgets.append(w)
        lay.addWidget(self.tabs, stretch=3)
        # 单一共享预览面板（位于主对话框底部，随活动选项卡刷新）
        # 关键点：预览 QTextEdit 只在此处加入布局一次，避免被各选项卡
        # 的 addWidget 反复 reparent 到最后创建的选项卡中导致可见页空白。
        g_preview = QGroupBox(tr('File preview'))
        v_preview = QVBoxLayout(g_preview)
        v_preview.setContentsMargins(4, 4, 4, 4)
        v_preview.addWidget(self.preview)
        lay.addWidget(g_preview, stretch=2)
        self.btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Save)
        self.btns.button(QDialogButtonBox.StandardButton.Save).setText(tr('Export...'))
        self.btns.rejected.connect(self.reject)
        self.btns.accepted.connect(self._export_current)
        lay.addWidget(self.btns)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(0)

    def _on_tab_changed(self, idx: int):
        w = self._tab_widgets[idx]
        if hasattr(w, '_update_preview'):
            w._update_preview()

    def _export_current(self):
        w = self._tab_widgets[self.tabs.currentIndex()]
        if not w.do_export(self):
            return
        self.accept()