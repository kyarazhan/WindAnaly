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

from ._common import (_filter_rows, _CommonOptions)

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
