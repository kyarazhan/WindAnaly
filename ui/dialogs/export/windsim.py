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

from ._common import (_dir_sector_edges, _dir_mid_sectors, _filter_rows, _format_period, _CommonOptions)

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
