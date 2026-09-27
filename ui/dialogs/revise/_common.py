"""本包各对话框共享的助手与基类（S2 拆分聚集）。"""
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


_NUMERIC_KINDS = {'speed', 'dir', 'temp', 'pres', 'rh', 'ti',
                  'synthetic', 'speed_sd'}


def _all_cols(ds: Dataset) -> list[str]:
    return list(ds.channels.keys())


def _numeric_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind in _NUMERIC_KINDS]


def _to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors='coerce')


def _col_from_display(ds: Dataset, disp: str) -> str:
    for c in ds.channels:
        if display_name(c) == disp:
            return c
    return disp


def _interp(series: pd.Series, method: str) -> pd.Series:
    s = _to_num(series)
    if method == 'linear':
        s = s.interpolate(method='linear', limit_direction='both')
    elif method == 'time':
        s = s.interpolate(method='time', limit_direction='both')
    elif method == 'ffill':
        s = s.ffill().bfill()
    elif method == 'bfill':
        s = s.bfill().ffill()
    elif method == 'spline':
        s = s.interpolate(method='spline', order=2, limit_direction='both')
    elif method == 'mean':
        s = s.fillna(s.mean())
    return s


# ------------------------------------------------------------------ 可复用组件
class _CheckList(QWidget):
    """带「全选」复选框 + 多选列表的可复用组件。"""

    def __init__(self, title: str = '', parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.sel_all = QCheckBox(tr('全选'))
        self.sel_all.stateChanged.connect(self._on_all)
        top.addWidget(self.sel_all)
        top.addStretch(1)
        if title:
            top.addWidget(QLabel(title))
            top.addStretch(1)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.MultiSelection)
        lay.addWidget(self.list, 1)

    def add_items(self, names: list[str]):
        for n in names:
            it = QListWidgetItem(display_name(n))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, n)
            self.list.addItem(it)

    def _on_all(self, state):
        chk = Qt.Checked if state == Qt.Checked.value else Qt.Unchecked
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(chk)

    def checked(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole) or actual_name(it.text()))
        return out

    def set_checked(self, names: set[str]):
        name_set = set(names)
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in name_set
                             else Qt.Unchecked)


class _DateTimeRow(QWidget):
    """标签 + 日期 + 时间的组合行。"""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(label))
        self.date = QDateTimeEdit()
        self.date.setDisplayFormat('yyyy/M/d')
        self.date.setCalendarPopup(True)
        self.time = QDateTimeEdit()
        self.time.setDisplayFormat('HH:mm')
        lay.addWidget(self.date)
        lay.addWidget(self.time)
        lay.addStretch(1)

    def set_dt(self, ts: pd.Timestamp):
        self.date.setDateTime(ts.to_pydatetime())
        self.time.setDateTime(ts.to_pydatetime())

    def get_dt(self) -> pd.Timestamp:
        d = self.date.dateTime().toPython()
        t = self.time.dateTime().toPython()
        return pd.Timestamp(d.replace(hour=t.hour, minute=t.minute,
                                      second=t.second))


def _ok_cancel_help(lay, ok_slot, help_text: str = ''):
    """在布局底部添加 Help + Cancel + OK。"""
    btns = QHBoxLayout()
    btns.addStretch(1)
    help_btn = QPushButton(tr('Help'))
    if help_text:
        help_btn.clicked.connect(
            lambda: QMessageBox.information(None, 'Help', help_text))
    cancel = QPushButton(tr('Cancel'))
    ok = QPushButton('OK')
    ok.setObjectName('primaryBtn')
    cancel.clicked.connect(lambda: None)
    ok.clicked.connect(ok_slot)
    btns.addWidget(help_btn)
    btns.addWidget(cancel)
    btns.addWidget(ok)
    lay.addLayout(btns)
    return help_btn, cancel, ok
