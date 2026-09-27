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

from ._common import (_dir_sector_edges, _filter_rows, _CommonOptions)

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
