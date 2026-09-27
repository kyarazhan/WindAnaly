"""Calibration 校准窗口（对齐 Windographer 原版布局）。

上方时间轴显示各通道的校准段，下方左侧为 Selected time / Store constants，
右侧为 Constants 表格。全英文标签，中英文经 tr() 切换。
"""

from __future__ import annotations

import math
import copy

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDoubleSpinBox,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QMenu, QMessageBox, QPushButton, QRadioButton,
                               QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ui.modules.analysis_tabs import display_name
from core.i18n import tr


class CalibrationTimeline(QWidget):
    """校准时间轴：一行为一个通道，分段显示校准区间。"""

    selectedTimeChanged = Signal(object)

    def __init__(self, dataset, parent=None):
        super().__init__(parent)
        self._ds = dataset
        self._cals = dataset.calibrations
        self._selected = dataset.df.index[0] if not dataset.df.empty else None
        self._row_height = 22
        self._left_margin = 170
        self._right_margin = 12
        self._top_margin = 24
        self._bottom_margin = 28
        self._colors = ['#fff9c4', '#c8e6c9', '#bbdefb', '#ffccbc', '#e1bee7']
        self.setMinimumHeight(200)
        self.setStyleSheet('background-color:#ffffff;')
        self.setAutoFillBackground(True)

    def set_selected(self, t):
        self._selected = t
        self.update()
        self.selectedTimeChanged.emit(t)

    def selected_time(self):
        return self._selected

    def _time_range(self):
        if self._ds.df.empty:
            return None, None
        return self._ds.df.index[0], self._ds.df.index[-1]

    def _x_of(self, t, rect):
        t0, t1 = self._time_range()
        if t0 is None or t1 is None or t1 == t0:
            return rect.left() + self._left_margin
        frac = (t - t0) / (t1 - t0)
        w = rect.width() - self._left_margin - self._right_margin
        return rect.left() + self._left_margin + frac * w

    def _time_of(self, x, rect):
        t0, t1 = self._time_range()
        if t0 is None or t1 is None:
            return None
        w = rect.width() - self._left_margin - self._right_margin
        frac = (x - rect.left() - self._left_margin) / w
        frac = max(0.0, min(1.0, frac))
        return t0 + pd.Timedelta(seconds=frac * (t1 - t0).total_seconds())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(4, 4, -4, -4)
        t0, t1 = self._time_range()
        cols = list(self._cals.keys())
        n = len(cols)
        h = max(self.height(),
                self._top_margin + n * self._row_height + self._bottom_margin)

        # 时间轴刻度标签
        p.setPen(QPen(QColor('#5a6573'), 1))
        p.drawLine(int(self._x_of(t0, rect)), self._top_margin - 4,
                   int(self._x_of(t1, rect)), self._top_margin - 4)
        for label, frac in [('Start', 0.0), ('25%', 0.25), ('50%', 0.5),
                            ('75%', 0.75), ('End', 1.0)]:
            t = t0 + pd.Timedelta(seconds=frac * (t1 - t0).total_seconds()) \
                if t1 != t0 else t0
            x = self._x_of(t, rect)
            p.drawText(int(x) - 20, 14, 40, 14, Qt.AlignCenter, label)

        for i, col in enumerate(cols):
            y = self._top_margin + i * self._row_height
            p.setPen(QColor('#212529'))
            p.drawText(4, y, self._left_margin - 8, self._row_height - 2,
                       Qt.AlignRight | Qt.AlignVCenter, display_name(col))
            periods = self._cals.get(col, [])
            for pi, per in enumerate(periods):
                ps = pd.Timestamp(per['start']) if per.get('start') else t0
                pe = pd.Timestamp(per['end']) if per.get('end') else t1
                x1 = self._x_of(ps, rect)
                x2 = self._x_of(pe, rect)
                color = QColor(self._colors[pi % len(self._colors)])
                if self._selected is not None and ps <= self._selected <= pe:
                    color = QColor('#90caf9')
                p.fillRect(int(x1), y, max(1, int(x2 - x1)),
                           self._row_height - 2, color)
                p.setPen(QPen(QColor('#9e9e9e'), 1))
                p.drawRect(int(x1), y, max(1, int(x2 - x1)), self._row_height - 2)
            p.setPen(QPen(QColor('#212121'), 2))
            for per in periods:
                if per.get('start'):
                    xb = self._x_of(pd.Timestamp(per['start']), rect)
                    p.drawLine(int(xb), y, int(xb), y + self._row_height - 2)

        if self._selected is not None:
            xs = int(self._x_of(self._selected, rect))
            p.setPen(QPen(QColor('#d32f2f'), 2, Qt.DashLine))
            p.drawLine(xs, self._top_margin, xs,
                       self._top_margin + n * self._row_height)
        p.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        rect = self.rect().adjusted(4, 4, -4, -4)
        t = self._time_of(event.position().x(), rect)
        if t is not None:
            self.set_selected(t)

    def contextMenuEvent(self, event):
        rect = self.rect().adjusted(4, 4, -4, -4)
        t = self._time_of(event.position().x(), rect)
        if t is None:
            return
        row = int((event.position().y() - self._top_margin) // self._row_height)
        cols = list(self._cals.keys())
        if row < 0 or row >= len(cols):
            return
        col = cols[row]
        menu = QMenu(self)
        act = QAction(f'Merge {display_name(col)} with previous period', self)
        act.triggered.connect(lambda: self._merge_previous(col, t))
        menu.addAction(act)
        menu.exec(event.globalPosition().toPoint())

    def _merge_previous(self, col, t):
        periods = self._cals.get(col, [])
        for i, per in enumerate(periods):
            ps = pd.Timestamp(per['start']) if per.get('start') \
                else self._time_range()[0]
            pe = pd.Timestamp(per['end']) if per.get('end') \
                else self._time_range()[1]
            if ps <= t <= pe and i > 0:
                prev = periods[i - 1]
                per['scale'] = prev['scale']
                per['offset'] = prev['offset']
                per['serial'] = prev['serial']
                prev['end'] = per['end']
                periods.pop(i)
                self.update()
                self.selectedTimeChanged.emit(self._selected)
                break


class CalibrationDialog(QDialog):
    """校准主对话框（全英文标签，对齐原版布局）。"""

    def __init__(self, dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Calibration'))
        self.resize(1100, 720)
        self._ds = dataset
        self._cals = self._copy_cals(dataset.calibrations)
        self._old_cals = self._copy_cals(dataset.calibrations)
        self._ensure_periods()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Vertical)

        # ---- 上方时间轴 ----
        top = QWidget()
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        self.timeline = CalibrationTimeline(dataset, self)
        self.timeline._cals = self._cals
        self.timeline.selectedTimeChanged.connect(self._on_time_changed)
        top_lay.addWidget(self.timeline)
        splitter.addWidget(top)

        # ---- 下方左：Selected time + Store constants ----
        bottom = QWidget()
        bottom_lay = QHBoxLayout(bottom)
        bottom_lay.setContentsMargins(0, 0, 0, 0)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)

        left_lay.addWidget(QLabel(tr('Selected time:')))
        time_grid = QGridLayout()
        time_grid.setSpacing(4)
        self.sel_year = QDoubleSpinBox()
        self.sel_year.setRange(1900, 2100)
        self.sel_year.setDecimals(0)
        self.sel_month = QDoubleSpinBox()
        self.sel_month.setRange(1, 12)
        self.sel_month.setDecimals(0)
        self.sel_day = QDoubleSpinBox()
        self.sel_day.setRange(1, 31)
        self.sel_day.setDecimals(0)
        self.sel_hour = QDoubleSpinBox()
        self.sel_hour.setRange(0, 23)
        self.sel_hour.setDecimals(0)
        for col_i, (lbl, sp) in enumerate(
                [('Y', self.sel_year), ('M', self.sel_month),
                 ('D', self.sel_day), ('h', self.sel_hour)]):
            time_grid.addWidget(QLabel(lbl), 0, col_i * 2)
            time_grid.addWidget(sp, 0, col_i * 2 + 1)
        left_lay.addLayout(time_grid)

        self.btn_new = QPushButton(
            tr('Create New Calibration Period Starting Here'))
        self.btn_new.clicked.connect(self._create_period)
        left_lay.addWidget(self.btn_new)
        left_lay.addStretch(1)

        # ---- Store these constants（左下角，原版位置）----
        store_lbl = QLabel(tr('Store these constants:'))
        store_lbl.setStyleSheet('font-weight: bold;')
        left_lay.addWidget(store_lbl)
        self.radio_apply = QRadioButton(tr('and apply them to the data'))
        self.radio_store = QRadioButton(
            'but don\u2019t change the data')
        self.radio_store.setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self.radio_apply)
        bg.addButton(self.radio_store)
        left_lay.addWidget(self.radio_apply)
        left_lay.addWidget(self.radio_store)

        # ---- 下方右：Constants 表格 ----
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.addWidget(QLabel(tr('Constants in selected calibration period:')))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ['Data Channel', 'Serial No.', 'Scale', 'Offset'])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._on_table_changed)
        right_lay.addWidget(self.table)

        bottom_lay.addWidget(left, 0)
        bottom_lay.addWidget(right, 1)
        splitter.addWidget(bottom)
        splitter.setSizes([300, 380])
        lay.addWidget(splitter, 1)

        # ---- 底部按钮 ----
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        self._refresh_table()

    # ------------------------------------------------------------------
    def _copy_cals(self, cals):
        return copy.deepcopy(cals)

    def _ensure_periods(self):
        if self._ds.df.empty:
            return
        t0, t1 = self._ds.df.index[0], self._ds.df.index[-1]
        for col in self._ds.df.columns:
            if not self._cals.get(col):
                self._cals[col] = [{
                    'start': str(t0), 'end': str(t1),
                    'scale': 1.0, 'offset': 0.0, 'serial': ''}]

    def _on_time_changed(self, t):
        self.sel_year.setValue(t.year)
        self.sel_month.setValue(t.month)
        self.sel_day.setValue(t.day)
        self.sel_hour.setValue(t.hour)
        self._refresh_table()

    def _active_period(self, col, t):
        for per in self._cals.get(col, []):
            ps = pd.Timestamp(per['start']) if per.get('start') \
                else self._ds.df.index[0]
            pe = pd.Timestamp(per['end']) if per.get('end') \
                else self._ds.df.index[-1]
            if ps <= t <= pe:
                return per
        return None

    def _refresh_table(self):
        t = self.timeline.selected_time()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        if t is None:
            self.table.blockSignals(False)
            return
        cols = list(self._cals.keys())
        self.table.setRowCount(len(cols))
        for r, col in enumerate(cols):
            per = self._active_period(col, t)
            if per is None:
                per = {'scale': 1.0, 'offset': 0.0, 'serial': ''}
            self.table.setItem(r, 0, QTableWidgetItem(display_name(col)))
            self.table.setItem(r, 1,
                               QTableWidgetItem(str(per.get('serial', ''))))
            self.table.setItem(r, 2, QTableWidgetItem(
                f"{float(per.get('scale', 1.0)):.6f}"))
            self.table.setItem(r, 3, QTableWidgetItem(
                f"{float(per.get('offset', 0.0)):.6f}"))
        self.table.blockSignals(False)

    def _on_table_changed(self, item):
        r = item.row()
        c = item.column()
        col_item = self.table.item(r, 0)
        if col_item is None:
            return
        col = self._col_from_display(col_item.text())
        t = self.timeline.selected_time()
        per = self._active_period(col, t)
        if per is None:
            return
        text = item.text().strip()
        try:
            if c == 1:
                per['serial'] = text
            elif c == 2:
                per['scale'] = float(text)
            elif c == 3:
                per['offset'] = float(text)
        except ValueError:
            pass

    def _col_from_display(self, display):
        for c in self._cals.keys():
            if display_name(c) == display:
                return c
        return display

    def _create_period(self):
        t = self._selected_from_spinners()
        if t is None or self._ds.df.empty:
            return
        t0, t1 = self._ds.df.index[0], self._ds.df.index[-1]
        if t < t0 or t > t1:
            QMessageBox.warning(self, 'Out of range',
                                'Selected time is outside the data set range')
            return
        self.timeline.set_selected(t)
        for col in self._cals.keys():
            periods = self._cals[col]
            for i, per in enumerate(periods):
                ps = pd.Timestamp(per['start']) if per.get('start') else t0
                pe = pd.Timestamp(per['end']) if per.get('end') else t1
                if ps < t < pe:
                    new_per = {
                        'start': str(t), 'end': per['end'],
                        'scale': per['scale'], 'offset': per['offset'],
                        'serial': per['serial']}
                    per['end'] = str(t)
                    periods.insert(i + 1, new_per)
                    break
        self.timeline.update()
        self._refresh_table()

    def _selected_from_spinners(self):
        try:
            return pd.Timestamp(
                int(self.sel_year.value()), int(self.sel_month.value()),
                int(self.sel_day.value()), int(self.sel_hour.value()))
        except Exception:
            return None

    def _on_ok(self):
        self._ds.calibrations = self._cals
        if self.radio_apply.isChecked():
            self._apply_to_data()
        self.accept()

    def _apply_to_data(self):
        df = self._ds.df
        if df.empty:
            return
        for col, periods in self._cals.items():
            if col not in df.columns:
                continue
            old_periods = self._old_cals.get(col, [])
            t0, t1 = df.index[0], df.index[-1]
            for per in periods:
                ps = pd.Timestamp(per['start']) if per.get('start') else t0
                pe = pd.Timestamp(per['end']) if per.get('end') else t1
                mask = (df.index >= ps) & (df.index <= pe)
                if not mask.any():
                    continue
                old_scale, old_offset = 1.0, 0.0
                for op in old_periods:
                    ops = pd.Timestamp(op['start']) if op.get('start') else t0
                    ope = pd.Timestamp(op['end']) if op.get('end') else t1
                    if ops <= ps <= ope or ops <= pe <= ope or \
                            (ps <= ops and pe >= ope):
                        old_scale = float(op.get('scale', 1.0))
                        old_offset = float(op.get('offset', 0.0))
                        break
                new_scale = float(per.get('scale', 1.0))
                new_offset = float(per.get('offset', 0.0))
                if old_scale == 0:
                    continue
                vals = pd.to_numeric(df.loc[mask, col], errors='coerce')
                df.loc[mask, col] = new_scale * \
                    (vals - old_offset) / old_scale + new_offset