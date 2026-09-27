"""Export Data 格式选项卡（拆分自 export_dialog，B3）。"""
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

from ._common import (_infer_timestep_minutes, _filter_rows, _format_timestamp, _CommonOptions)

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
