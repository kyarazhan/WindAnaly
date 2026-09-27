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

from ._common import (_dir_sector_edges, _dir_mid_sectors, _filter_rows, _CommonOptions)

class _WasPTab(QWidget):
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

        # Left: WAsP options
        left = QGroupBox(tr('WAsP options'))
        f_left = QFormLayout(left)
        f_left.setSpacing(2)
        f_left.setContentsMargins(4, 4, 4, 4)
        self.cmb_speed = QComboBox()
        for c in _speed_cols(self.ds):
            self.cmb_speed.addItem(_col_disp(self.ds, c), c)
        f_left.addRow('Wind speed sensor:', self.cmb_speed)
        self.cmb_dir = QComboBox()
        for c in _dir_cols(self.ds):
            self.cmb_dir.addItem(_col_disp(self.ds, c), c)
        f_left.addRow('Wind direction sensor:', self.cmb_dir)
        self.cmb_sectors = QComboBox()
        self.cmb_sectors.addItems(['8', '12', '16', '24', '36', '48'])
        self.cmb_sectors.setCurrentText('16')
        f_left.addRow('Wind direction sectors:', self.cmb_sectors)
        h_bin = QHBoxLayout()
        self.spn_bin = QDoubleSpinBox()
        self.spn_bin.setRange(0.1, 10.0)
        self.spn_bin.setValue(1.0)
        self.spn_bin.setDecimals(1)
        self.spn_bin.setSuffix(' m/s')
        h_bin.addWidget(self.spn_bin)
        self.chk_half = QCheckBox(tr('First bin half this size'))
        h_bin.addWidget(self.chk_half)
        h_bin.addStretch()
        f_left.addRow('Wind speed bin size:', h_bin)
        v_exp = QVBoxLayout()
        self.rb_occ = QRadioButton(tr('occurrences'))
        self.rb_freq = QRadioButton(tr('frequencies'))
        self.rb_freq.setChecked(True)
        v_exp.addWidget(self.rb_occ)
        v_exp.addWidget(self.rb_freq)
        f_left.addRow('Export:', v_exp)
        self.chk_seasonal = QCheckBox(tr('Remove seasonal bias'))
        f_left.addRow(self.chk_seasonal)
        top.addWidget(left, stretch=2)

        # Middle: common options
        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid, stretch=1)

        # Right: scale/offset/property
        right = QVBoxLayout()
        right.setSpacing(4)
        h_scale = QHBoxLayout()
        self.chk_scale = QCheckBox(tr('Scale to mean wind speed of'))
        self.spn_scale_target = QDoubleSpinBox()
        self.spn_scale_target.setRange(0.0, 30.0)
        self.spn_scale_target.setDecimals(2)
        self.spn_scale_target.setSuffix(' m/s')
        h_scale.addWidget(self.chk_scale)
        h_scale.addWidget(self.spn_scale_target)
        h_scale.addStretch()
        right.addLayout(h_scale)
        self.chk_offset = QCheckBox(tr('Offset directions clockwise'))
        right.addWidget(self.chk_offset)
        g_prop = QGroupBox(tr('Property'))
        v_prop = QVBoxLayout(g_prop)
        v_prop.setContentsMargins(4, 4, 4, 4)
        self.tbl_prop = QTableWidget()
        self.tbl_prop.setColumnCount(3)
        self.tbl_prop.setHorizontalHeaderLabels(
            ['Property', 'Time Series', 'TAB file'])
        self.tbl_prop.horizontalHeader().setStretchLastSection(True)
        self.tbl_prop.verticalHeader().setVisible(False)
        self.tbl_prop.setRowCount(2)
        self.tbl_prop.setItem(0, 0, QTableWidgetItem('Mean speed (m/s)'))
        self.tbl_prop.setItem(1, 0, QTableWidgetItem('Mean WPD (W/m2)'))
        self.tbl_prop.setMinimumHeight(100)
        v_prop.addWidget(self.tbl_prop)
        self.lbl_steps = QLabel(tr('Time steps in time series'))
        v_prop.addWidget(self.lbl_steps)
        right.addWidget(g_prop)
        right.addStretch()
        top.addLayout(right, stretch=1)

        lay.addLayout(top, stretch=2)

        # signals
        for w in (self.cmb_speed, self.cmb_dir, self.cmb_sectors):
            w.currentIndexChanged.connect(self._maybe_update)
        self.spn_bin.valueChanged.connect(self._maybe_update)
        self.chk_half.stateChanged.connect(self._maybe_update)
        self.rb_occ.toggled.connect(self._maybe_update)
        self.rb_freq.toggled.connect(self._maybe_update)
        self.chk_seasonal.stateChanged.connect(self._maybe_update)
        self.chk_scale.stateChanged.connect(self._maybe_update)
        self.spn_scale_target.valueChanged.connect(self._maybe_update)
        self.chk_offset.stateChanged.connect(self._maybe_update)
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

    def _matrix_and_series(self):
        """返回 (H_counts, speed_edges, dir_mids, speed_series_aligned)。"""
        speed_col = self.cmb_speed.currentData()
        dir_col = self.cmb_dir.currentData()
        if not speed_col or not dir_col:
            return None
        sectors = int(self.cmb_sectors.currentText())
        bin_size = self.spn_bin.value()
        df = self._filtered()
        s = df[speed_col].dropna()
        d = df[dir_col].reindex(s.index).dropna()
        if len(d) == 0:
            return None
        s = s.reindex(d.index)
        # scale
        if self.chk_scale.isChecked():
            target = self.spn_scale_target.value()
            if s.mean() and s.mean() > 0:
                s = s * (target / s.mean())
        # offset directions clockwise
        if self.chk_offset.isChecked():
            offset = self.ds.attrs.get('dir_offset', 0.0)
            d = (d + offset) % 360.0
        max_speed = math.ceil(s.max() / bin_size) * bin_size
        if self.chk_half.isChecked():
            edges = [0.0, bin_size / 2.0]
            edges += list(np.arange(bin_size, max_speed + bin_size, bin_size))
        else:
            edges = list(np.arange(0.0, max_speed + bin_size, bin_size))
        dir_edges = _dir_sector_edges(sectors)
        H, _, _ = np.histogram2d(s, d, bins=[edges, dir_edges])

        # seasonal bias: 月均矩阵再平均
        if self.chk_seasonal.isChecked() and not df.empty:
            monthly = []
            for _, g in df.groupby([df.index.year, df.index.month]):
                gs = g[speed_col].dropna()
                gd = g[dir_col].reindex(gs.index).dropna()
                if len(gd) == 0:
                    continue
                gs = gs.reindex(gd.index)
                if self.chk_scale.isChecked() and gs.mean() and gs.mean() > 0:
                    gs = gs * (self.spn_scale_target.value() / gs.mean())
                if self.chk_offset.isChecked():
                    offset = self.ds.attrs.get('dir_offset', 0.0)
                    gd = (gd + offset) % 360.0
                Hm, _, _ = np.histogram2d(gs, gd, bins=[edges, dir_edges])
                monthly.append(Hm)
            if monthly:
                H = np.mean(monthly, axis=0)
        return H, np.array(edges), _dir_mid_sectors(sectors), s

    def _update_properties(self):
        speed_col = self.cmb_speed.currentData()
        r = self._matrix_and_series()
        if r is None or not speed_col:
            self.lbl_steps.setText('Time steps in time series 0')
            for i in range(2):
                for j in (1, 2):
                    self.tbl_prop.setItem(i, j, QTableWidgetItem(''))
            return
        H, edges, _, s = r
        rho = self.ds.attrs.get('air_density', 1.225)

        # Time series 统计（要求同时有 speed/dir）
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        df = _filter_rows(self.ds, u, ic, inv, only_int, t0, t1)
        dir_col = self.cmb_dir.currentData()
        valid = df[[speed_col, dir_col]].notna().all(axis=1)
        ts_speed = df.loc[valid, speed_col]
        ts_wpd = 0.5 * rho * (ts_speed ** 3)
        ts_mean_speed = ts_speed.mean()
        ts_mean_wpd = ts_wpd.mean()

        # TAB file 统计（用 occurrences 加权 bin 中点）
        mids = (edges[:-1] + edges[1:]) / 2.0
        if self.chk_half.isChecked():
            mids[0] = edges[1] / 4.0
        total_occ = H.sum()
        if total_occ > 0:
            tab_mean_speed = np.sum(mids * H.sum(axis=1)) / total_occ
            tab_mean_wpd = np.sum(0.5 * rho * (mids ** 3) * H.sum(axis=1)) / total_occ
        else:
            tab_mean_speed = np.nan
            tab_mean_wpd = np.nan

        vals = [
            (ts_mean_speed, tab_mean_speed),
            (ts_mean_wpd, tab_mean_wpd),
        ]
        for i, (ts_v, tab_v) in enumerate(vals):
            self.tbl_prop.setItem(
                i, 1, QTableWidgetItem('' if pd.isna(ts_v) else f'{ts_v:.3f}'))
            self.tbl_prop.setItem(
                i, 2, QTableWidgetItem('' if pd.isna(tab_v) else f'{tab_v:.1f}'))
        self.lbl_steps.setText(f'Time steps in time series {len(ts_speed)}')

    def generate_text(self, preview: bool = False) -> str:
        self._update_properties()
        r = self._matrix_and_series()
        if r is None:
            return '# Created by WindAnaly\n# No valid speed/direction data'
        H, speed_edges, dir_mids, _ = r
        speed_col = self.cmb_speed.currentData()
        dir_col = self.cmb_dir.currentData()
        sectors = int(self.cmb_sectors.currentText())
        lat = self.ds.attrs.get('latitude', 0.0)
        lon = self.ds.attrs.get('longitude', 0.0)
        h = _height_of(speed_col) or 0.0
        desc = (f'{self.ds.name}; speed={self.cmb_speed.currentText()}, '
                f'dir={self.cmb_dir.currentText()}')
        if self.chk_seasonal.isChecked():
            desc += ', seasonal bias removed'
        if self.chk_scale.isChecked():
            desc += f', scaled to {self.spn_scale_target.value():.2f} m/s'

        lines = [f'# {desc}']
        lines.append(f'{lat}\t{lon}\t{h}')
        lines.append(f'{sectors}\t1.00\t0.00')

        col_totals = H.sum(axis=0)
        grand = col_totals.sum()
        if grand > 0:
            overall_pct = col_totals / grand * 100.0
        else:
            overall_pct = np.zeros(sectors)
        lines.append('\t'.join([''] + [f'{v:.4f}' for v in overall_pct]))

        if self.rb_freq.isChecked():
            # 每扇区 per mille
            out = np.zeros_like(H)
            for c in range(sectors):
                if col_totals[c] > 0:
                    out[:, c] = H[:, c] / col_totals[c] * 1000.0
        else:
            out = H
        for i, row in enumerate(out):
            label = f'{speed_edges[i+1]:.1f}'
            vals = [f'{v:.6f}' for v in row]
            lines.append('\t'.join([label] + vals))
        return '\n'.join(lines)

    def do_export(self, parent):
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 WAsP .tab', f'{self.ds.name}.tab',
            'WAsP (*.tab);;All files (*.*)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text(preview=False))
        return True
