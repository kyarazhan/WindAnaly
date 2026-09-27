"""combine_sensors.py：见 _common 与 shim。"""
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

from ._common import (_to_num, _col_from_display)

class CombineSensorsDialog(QDialog):
    HELP = ('Select a first and second anemometer, choose a combination '
            'method, and optionally hide the original columns.')

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('组合风速仪'))
        self.resize(640, 420)
        self._ds = ds

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        main = QHBoxLayout()
        # First Anemometer
        g1 = QGroupBox(tr('First Anemometer'))
        v1 = QVBoxLayout(g1)
        self.list1 = QListWidget()
        self.list1.setSelectionMode(QAbstractItemView.SingleSelection)
        v1.addWidget(self.list1)
        main.addWidget(g1, 1)

        # Second Anemometer
        g2 = QGroupBox(tr('Second Anemometer'))
        v2 = QVBoxLayout(g2)
        self.list2 = QListWidget()
        self.list2.setSelectionMode(QAbstractItemView.SingleSelection)
        v2.addWidget(self.list2)
        main.addWidget(g2, 1)

        # Method
        g3 = QGroupBox(tr('Combination Method'))
        v3 = QVBoxLayout(g3)
        self.method = QComboBox()
        self.method.addItems(['average', 'primary', 'minimum', 'maximum'])
        v3.addWidget(self.method)
        v3.addStretch(1)
        main.addWidget(g3, 1)

        lay.addLayout(main, 1)

        self.hide_orig = QCheckBox(tr('Hide original data columns'))
        lay.addWidget(self.hide_orig)

        # 填充风速列表
        speeds = [c.name for c in ds.channels.values() if c.kind == 'speed']
        for c in speeds:
            self.list1.addItem(display_name(c))
            self.list2.addItem(display_name(c))

        btns = QHBoxLayout()
        btns.addStretch(1)
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, 'Help', self.HELP))
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(help_btn)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _sel(self, lst: QListWidget) -> str | None:
        it = lst.currentItem()
        if not it:
            return None
        return _col_from_display(self._ds, it.text())

    def _on_ok(self):
        c1 = self._sel(self.list1)
        c2 = self._sel(self.list2)
        if not c1 or not c2:
            QMessageBox.warning(self, tr('通道不足'), tr('请选择两个风速通道'))
            return
        if c1 == c2:
            QMessageBox.warning(self, tr('通道重复'), tr('两个通道不能相同'))
            return
        df = self._ds.df
        s1 = _to_num(df[c1])
        s2 = _to_num(df[c2])
        method = self.method.currentText()
        if method == 'average':
            res = pd.concat([s1, s2], axis=1).mean(axis=1, min_count=1)
        elif method == 'primary':
            res = s1.fillna(s2)
        elif method == 'minimum':
            res = pd.concat([s1, s2], axis=1).min(axis=1)
        else:
            res = pd.concat([s1, s2], axis=1).max(axis=1)
        out = f'Combined {display_name(c1)}'
        if out in df.columns:
            out = f'Combined {c1}'
        df[out] = res
        src = self._ds.channels.get(c1)
        ch = Channel(
            name=out,
            kind=src.kind if src else 'speed',
            height=src.height if src else None,
            units=src.units if src else '',
            role='Combined')
        self._ds.channels[out] = ch
        if self.hide_orig.isChecked():
            for c in (c1, c2):
                if c in df.columns:
                    df.drop(columns=[c], inplace=True)
                self._ds.channels.pop(c, None)
                self._ds.calibrations.pop(c, None)
        self._info = f'已组合 {display_name(c1)} + {display_name(c2)}（{method}）'
        self.accept()
