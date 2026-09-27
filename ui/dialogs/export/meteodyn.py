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
