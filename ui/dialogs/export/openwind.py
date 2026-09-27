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

from ._common import (_filter_rows, _find_aux_cols, _CommonOptions)

class _OpenwindTab(QWidget):
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

        left = QGroupBox(tr('Openwind options'))
        f = QFormLayout(left)
        f.setSpacing(2)
        f.setContentsMargins(4, 4, 4, 4)
        h = QHBoxLayout()
        self.rb_single = QRadioButton(tr('single height'))
        self.rb_multi = QRadioButton(tr('multiple heights'))
        self.rb_single.setChecked(True)
        h.addWidget(self.rb_single)
        h.addWidget(self.rb_multi)
        h.addStretch()
        f.addRow('Export:', h)

        self.stack = QStackedWidget()
        # single page
        single = QWidget()
        f_single = QFormLayout(single)
        f_single.setContentsMargins(0, 0, 0, 0)
        f_single.setSpacing(4)
        self.cmb_speed = QComboBox()
        for c in _speed_cols(self.ds):
            self.cmb_speed.addItem(_col_disp(self.ds, c), c)
        f_single.addRow('Wind speed sensor:', self.cmb_speed)
        self.cmb_dir = QComboBox()
        for c in _dir_cols(self.ds):
            self.cmb_dir.addItem(_col_disp(self.ds, c), c)
        f_single.addRow('Wind direction sensor:', self.cmb_dir)
        self.stack.addWidget(single)
        # multi page
        multi = QWidget()
        v_multi = QVBoxLayout(multi)
        v_multi.setSpacing(4)
        v_multi.setContentsMargins(0, 0, 0, 0)
        info = QLabel(
            tr('To export multiple heights the data set must contain speed, TI, '
            'direction, and temperature columns at each height. Use the Vertical '
            'Extrapolation window to generate one or more such columns.'))
        info.setWordWrap(True)
        v_multi.addWidget(info)
        self.lst_heights = QListWidget()
        self.lst_heights.setMinimumWidth(180)
        v_multi.addWidget(self.lst_heights)
        self.lbl_warn = QLabel('')
        self.lbl_warn.setStyleSheet('color: red')
        v_multi.addWidget(self.lbl_warn)
        self.stack.addWidget(multi)
        f.addRow(self.stack)
        top.addWidget(left, stretch=2)

        mid = QVBoxLayout()
        self.common = _CommonOptions(self.ds)
        self.common.btn_update.clicked.connect(self._update_preview)
        mid.addWidget(self.common)
        mid.addStretch()
        top.addLayout(mid, stretch=1)

        right = QVBoxLayout()
        right.setSpacing(4)
        g_scale = QGroupBox()
        h_scale = QHBoxLayout(g_scale)
        h_scale.setSpacing(2)
        h_scale.setContentsMargins(4, 4, 4, 4)
        self.chk_scale = QCheckBox(tr('Scale speeds so'))
        self.cmb_scale_sensor = QComboBox()
        for c in _speed_cols(self.ds):
            self.cmb_scale_sensor.addItem(_col_disp(self.ds, c), c)
        self.spn_scale_target = QDoubleSpinBox()
        self.spn_scale_target.setRange(0.0, 30.0)
        self.spn_scale_target.setValue(5.0)
        self.spn_scale_target.setDecimals(2)
        self.spn_scale_target.setSuffix(' m/s')
        h_scale.addWidget(self.chk_scale)
        h_scale.addWidget(self.cmb_scale_sensor)
        h_scale.addWidget(QLabel(tr('has a mean speed of')))
        h_scale.addWidget(self.spn_scale_target)
        h_scale.addStretch()
        right.addWidget(g_scale)
        g_prop = QGroupBox(tr('Properties of exported data'))
        v_prop = QVBoxLayout(g_prop)
        v_prop.setContentsMargins(4, 4, 4, 4)
        self.tbl_prop = QTableWidget()
        self.tbl_prop.setColumnCount(2)
        self.tbl_prop.setHorizontalHeaderLabels(['', ''])
        self.tbl_prop.horizontalHeader().setVisible(False)
        self.tbl_prop.verticalHeader().setVisible(False)
        self.tbl_prop.setRowCount(3)
        self.tbl_prop.setItem(0, 0, QTableWidgetItem('Valid speed values:'))
        self.tbl_prop.setItem(1, 0, QTableWidgetItem('Mean speed @ 0 m'))
        self.tbl_prop.setItem(2, 0, QTableWidgetItem('Scaling factor:'))
        self.tbl_prop.setMinimumHeight(90)
        v_prop.addWidget(self.tbl_prop)
        right.addWidget(g_prop)
        right.addStretch()
        top.addLayout(right, stretch=1)

        lay.addLayout(top, stretch=2)

        self.rb_single.toggled.connect(self._on_mode_changed)
        self.rb_multi.toggled.connect(self._on_mode_changed)
        for w in (self.cmb_speed, self.cmb_dir, self.cmb_scale_sensor):
            w.currentIndexChanged.connect(self._maybe_update)
        self.chk_scale.stateChanged.connect(self._maybe_update)
        self.spn_scale_target.valueChanged.connect(self._maybe_update)
        self.lst_heights.itemChanged.connect(self._maybe_update)
        self.common.connect_changed(self._maybe_update)
        self.common.chk_auto_preview.stateChanged.connect(
            lambda: self._maybe_update() if self.common.chk_auto_preview.isChecked() else None)

        self._populate_heights()
        self._on_mode_changed()
        self._update_preview()

    def _populate_heights(self):
        self.lst_heights.clear()
        seen = set()
        for c in _speed_cols(self.ds):
            h = _height_of(c)
            if h is None or h in seen:
                continue
            seen.add(h)
            item = QListWidgetItem(f'{h} m')
            item.setData(Qt.UserRole, h)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.lst_heights.addItem(item)

    def _selected_heights(self) -> list[float]:
        heights = []
        for i in range(self.lst_heights.count()):
            item = self.lst_heights.item(i)
            if item.checkState() == Qt.Checked:
                heights.append(item.data(Qt.UserRole))
        return heights

    def _on_mode_changed(self):
        self.stack.setCurrentIndex(0 if self.rb_single.isChecked() else 1)
        self._maybe_update()

    def _maybe_update(self):
        if self.common.chk_auto_preview.isChecked():
            self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text(preview=True))

    def _cols_for_height(self, height: float):
        """返回 (speed_col, dir_col, temp_col, dens_col, ti_col)。"""
        speed_col = dir_col = temp_col = dens_col = ti_col = None
        for c in self.ds.df.columns:
            ch = self.ds.channels.get(c)
            if ch is None or ch.height != height:
                continue
            if speed_col is None and ch.kind == 'speed':
                speed_col = c
            elif dir_col is None and ch.kind == 'dir':
                dir_col = c
            elif temp_col is None and (ch.kind in ('temp', 'temperature') or
                                       (ch.units and 'C' in ch.units.upper())):
                temp_col = c
            elif dens_col is None and (ch.kind in ('density', 'rho') or
                                       (ch.units and 'kg' in ch.units.lower())):
                dens_col = c
            elif ti_col is None and ch.kind in ('ti', 'turbulence'):
                ti_col = c
        # 回退任意列
        if temp_col is None:
            temp_col, dens_col, ti_col = _find_aux_cols(self.ds, None)
        return speed_col, dir_col, temp_col, dens_col, ti_col

    def _scale_factor(self, df: pd.DataFrame) -> float:
        sf = 1.0
        if self.chk_scale.isChecked():
            sc = self.cmb_scale_sensor.currentData()
            if sc and sc in df.columns:
                m = df[sc].mean()
                if m and m > 0:
                    sf = self.spn_scale_target.value() / m
        return sf

    def _update_properties(self, valid_count: int, mean_speed: float,
                           sf: float, height: float):
        self.tbl_prop.setItem(0, 1, QTableWidgetItem(f'{valid_count}'))
        self.tbl_prop.setItem(
            1, 0, QTableWidgetItem(f'Mean speed @ {height:.0f} m'))
        self.tbl_prop.setItem(
            1, 1, QTableWidgetItem(f'{mean_speed:.3f}'))
        self.tbl_prop.setItem(2, 1, QTableWidgetItem(f'{sf:.3f}'))

    def generate_text(self, preview: bool = False) -> str:
        u, ic, inv, only_int, t0, t1 = self.common.filter()
        df = _filter_rows(self.ds, u, ic, inv, only_int, t0, t1)
        if df.empty:
            return '# No data'
        lat = self.ds.attrs.get('latitude', 0.0)
        lon = self.ds.attrs.get('longitude', 0.0)
        elev = self.ds.attrs.get('elevation', 0.0)

        if self.rb_single.isChecked():
            speed_col = self.cmb_speed.currentData()
            dir_col = self.cmb_dir.currentData()
            if not speed_col or not dir_col:
                return '# Select speed/direction sensors'
            h = _height_of(speed_col) or 0.0
            temp_col, dens_col, ti_col = _find_aux_cols(self.ds, h)
            sf = self._scale_factor(df)
            valid = df[[speed_col, dir_col]].notna().all(axis=1)
            self._update_properties(
                int(valid.sum()), df.loc[valid, speed_col].mean() * sf, sf, h)
            lines = ['MM,1', f'{lon},{lat},{elev}',
                     f'0,{self.ds.name},{self.ds.name}']
            header = ['Year', 'Month', 'Day', 'Hour', 'Minute',
                      f'{speed_col} [m/s]', f'{dir_col} [deg]']
            aux = []
            if temp_col:
                aux.append((temp_col, '[°C]'))
            if dens_col:
                aux.append((dens_col, '[kg/m3]'))
            if ti_col:
                aux.append((ti_col, '[TI]'))
            for col, unit in aux:
                header.append(f'{col} {unit}')
            lines.append(','.join(header))
            for ts, row in df.iterrows():
                sp = row.get(speed_col)
                dr = row.get(dir_col)
                if pd.isna(sp) or pd.isna(dr):
                    continue
                vals = [f'{ts.year:04d}', f'{ts.month:02d}', f'{ts.day:02d}',
                        f'{ts.hour:02d}', f'{ts.minute:02d}',
                        f'{sp * sf:.3f}', f'{dr:.1f}']
                for col, _ in aux:
                    v = row.get(col)
                    vals.append('-999' if pd.isna(v) else f'{v:.3f}')
                lines.append(','.join(vals))
                if preview and len(lines) > 30:
                    lines.append('# ...')
                    break
            return '\n'.join(lines)

        # multiple heights
        heights = self._selected_heights()
        if not heights:
            self.lbl_warn.setText(
                tr('You must select at least one measurement height to export an MM2 file.'))
            return ''
        self.lbl_warn.setText('')
        lines = ['MM,2']
        for h in heights:
            speed_col, dir_col, temp_col, dens_col, ti_col = self._cols_for_height(h)
            if not speed_col or not dir_col:
                continue
            sf = self._scale_factor(df)
            cols = [speed_col, dir_col]
            for c in (temp_col, dens_col, ti_col):
                if c:
                    cols.append(c)
            lines.append(f'# Height {h} m')
            for ts, row in df.iterrows():
                if any(pd.isna(row.get(c)) for c in cols):
                    continue
                vals = [f'{ts.year:04d}', f'{ts.month:02d}', f'{ts.day:02d}',
                        f'{ts.hour:02d}', f'{ts.minute:02d}', f'{h:.1f}']
                for c in cols:
                    v = row.get(c)
                    if c == speed_col:
                        vals.append(f'{v * sf:.3f}')
                    elif c == dir_col:
                        vals.append(f'{v:.1f}')
                    else:
                        vals.append(f'{v:.3f}')
                lines.append(','.join(vals))
                if preview and len(lines) > 30:
                    lines.append('# ...')
                    return '\n'.join(lines)
        return '\n'.join(lines)

    def do_export(self, parent):
        ext = '.mm2' if self.rb_multi.isChecked() else '.txt'
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 Openwind', f'{self.ds.name}{ext}',
            f'Openwind (*{ext});;All files (*.*)')
        if not path:
            return False
        if self.rb_multi.isChecked() and not self._selected_heights():
            QMessageBox.warning(
                parent, tr('导出失败'),
                'Please select at least one measurement height for MM2 export.')
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text(preview=False))
        return True
