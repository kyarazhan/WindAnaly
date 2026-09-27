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
