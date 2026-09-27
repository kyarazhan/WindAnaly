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
