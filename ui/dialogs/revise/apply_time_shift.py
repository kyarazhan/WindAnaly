"""apply_time_shift.py：见 _common 与 shim。"""
from __future__ import annotations

import copy
import math

import numpy as np
import pandas as pd
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateTimeEdit,
    QDialog, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QRadioButton, QSpinBox, QSplitter, QStackedWidget,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.dataset import Channel, Dataset
from core.i18n import language, tr
from core.io_import import build_canon_name
from ui.modules.analysis_tabs import actual_name, display_name
from ui.modules.plot import PlotCanvas


class ApplyTimeShiftDialog(QDialog):
    """Apply Time Shift.

    What would you like to do? / Shift columns / Time interval / Steps.
    """

    def __init__(self, ds, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Apply Time Shift'))
        self.resize(640, 520)
        self._ds = ds
        self._info = ''

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        left = QVBoxLayout()
        left.addWidget(QLabel(tr('What would you like to do?')))
        self.rb_all = QRadioButton(tr('Shift the entire data set in time'))
        self.rb_seg = QRadioButton(tr('Shift a particular data segment in time'))
        self.rb_all.setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self.rb_all)
        bg.addButton(self.rb_seg)
        left.addWidget(self.rb_all)
        left.addWidget(self.rb_seg)

        left.addWidget(QLabel(tr('Shift the following data columns...')))
        self.chk_select_all = QCheckBox(tr('Select all'))
        self.chk_select_all.setChecked(True)
        self.chk_select_all.stateChanged.connect(self._toggle_all)
        left.addWidget(self.chk_select_all)

        self.col_listw = QListWidget()
        self.col_listw.setSelectionMode(QAbstractItemView.NoSelection)
        for c in ds.df.columns:
            item = QListWidgetItem(display_name(c))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.col_listw.addItem(item)
        left.addWidget(self.col_listw, 1)
        root.addLayout(left, 0)

        right = QVBoxLayout()
        right.addWidget(QLabel(tr('in the following time interval...')))
        iv_gb = QGroupBox()
        iv_form = QFormLayout(iv_gb)
        iv_form.setSpacing(4)
        from PySide6.QtCore import QDateTime
        self.dt_start = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDisplayFormat('yyyy/M/d HH:mm')
        self.dt_end = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_end.setCalendarPopup(True)
        self.dt_end.setDisplayFormat('yyyy/M/d HH:mm')
        self.rb_all.toggled.connect(self._toggle_interval)
        self._toggle_interval(True)
        iv_form.addRow(tr('Start time'), self.dt_start)
        iv_form.addRow(tr('End time'), self.dt_end)
        right.addWidget(iv_gb)

        by_gb = QGroupBox()
        by_form = QFormLayout(by_gb)
        by_form.setSpacing(4)
        self.sp_steps = QSpinBox()
        self.sp_steps.setRange(-999999, 999999)
        by_form.addRow(tr('by'), self.sp_steps)
        by_form.addRow(QLabel(tr('time steps')))
        self.rb_fwd = QRadioButton(tr('forward in time'))
        self.rb_bwd = QRadioButton(tr('backward in time'))
        self.rb_fwd.setChecked(True)
        by_form.addRow(self.rb_fwd)
        by_form.addRow(self.rb_bwd)
        right.addWidget(by_gb)
        right.addStretch(1)
        root.addLayout(right, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, tr('Help'),
            tr('Shift the selected data columns in time by the specified '
               'number of time steps, forward or backward.')))
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('OK'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(help_btn)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

        self._init_time_range()

    def _toggle_interval(self, entire_mode):
        # 整体时移时无需指定时间区间
        self.dt_start.setEnabled(not entire_mode)
        self.dt_end.setEnabled(not entire_mode)

    def _toggle_all(self, state):
        checked = state == Qt.Checked
        for i in range(self.col_listw.count()):
            self.col_listw.item(i).setCheckState(
                Qt.Checked if checked else Qt.Unchecked)

    def _init_time_range(self):
        if self._ds.df.empty:
            return
        t0 = pd.Timestamp(self._ds.df.index[0])
        t1 = pd.Timestamp(self._ds.df.index[-1])
        from PySide6.QtCore import QDate, QDateTime, QTime

        def _qdt(ts):
            return QDateTime(QDate(ts.year, ts.month, ts.day),
                             QTime(ts.hour, ts.minute))

        self.dt_start.setDateTime(_qdt(t0))
        self.dt_end.setDateTime(_qdt(t1))

    def _selected_columns(self):
        cols = []
        for i in range(self.col_listw.count()):
            item = self.col_listw.item(i)
            if item.checkState() == Qt.Checked:
                cols.append(item.text())
        return cols

    def _on_ok(self):
        if self._ds.df.empty:
            self.reject()
            return
        steps = self.sp_steps.value()
        if steps == 0:
            QMessageBox.warning(self, tr('No shift'),
                                tr('Please enter a non-zero number of steps'))
            return
        cols = []
        for i in range(self.col_listw.count()):
            item = self.col_listw.item(i)
            if item.checkState() == Qt.Checked:
                cols.append(actual_name(item.text()))
        if not cols:
            QMessageBox.warning(self, tr('No columns'),
                                tr('Please select columns to shift'))
            return

        dt_min = 10.0
        try:
            diffs = np.diff(np.asarray(self._ds.df.index)
                            .astype('datetime64[s]').astype('int64')) / 60.0
            diffs = diffs[diffs > 0]
            if len(diffs):
                dt_min = float(np.median(diffs))
        except Exception:
            pass
        td = pd.Timedelta(minutes=steps * dt_min)

        df = self._ds.df
        if self.rb_all.isChecked():
            new_index = df.index + td
            df.index = new_index
            if len(self._ds.flags) == len(new_index):
                self._ds.flags.index = new_index
            for periods in self._ds.calibrations.values():
                for per in periods:
                    if per.get('start'):
                        per['start'] = str(pd.Timestamp(per['start']) + td)
                    if per.get('end'):
                        per['end'] = str(pd.Timestamp(per['end']) + td)
            self._info = f'{tr("Time shift")}: {td}'
        else:
            start = pd.Timestamp(self.dt_start.dateTime().toPython())
            end = pd.Timestamp(self.dt_end.dateTime().toPython())
            in_iv = (df.index >= start) & (df.index <= end)
            if not in_iv.any():
                QMessageBox.warning(self, tr('No data'),
                                    tr('No data in the selected time interval'))
                return
            n_shift = 0
            for col in cols:
                if col not in df.columns:
                    continue
                vals = df.loc[in_iv, col].copy()
                src_idx = df.index[in_iv]
                df.loc[in_iv, col] = np.nan
                for si, ni in zip(src_idx, src_idx + td):
                    if ni in df.index:
                        df.at[ni, col] = vals.loc[si]
                        n_shift += 1
            df.sort_index(inplace=True)
            self._info = f'{tr("Time shift")}: {len(cols)} cols, {n_shift} pts, {td}'
        self.accept()

    def result_info(self):
        return self._info
