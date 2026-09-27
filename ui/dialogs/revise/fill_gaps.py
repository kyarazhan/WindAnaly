"""fill_gaps.py：见 _common 与 shim。"""
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

from ._common import (_numeric_cols, _interp, _DateTimeRow)

class CoverageTimeline(QWidget):
    """原版风格的数据覆盖时间线：每通道一行色带，缺测处留白形成白色竖线。

    set_data 一次性把每通道时间轴降采样为固定桶数（时间比例位置），
    之后 paintEvent 只做快速绘制，勾选变化不重新计算。
    """

    PALETTE = ['#1f4e79', '#7b241c', '#7d6608', '#ca6f1e', '#2471a3',
               '#839192', '#148f77', '#7d3c98', '#b7950b', '#a04000',
               '#1e8449', '#2874a6', '#943126', '#6e2c00', '#4a235a',
               '#34495e', '#884313', '#196f3d']

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, np.ndarray]] = []
        self._t0 = None
        self._t1 = None

    def set_data(self, df: pd.DataFrame, cols: list[str], buckets: int = 1000):
        """每通道一次向量化降采样：桶 = 时间比例分格，值 = 有效率。"""
        self._rows = []
        self._t0 = self._t1 = None
        n = len(df)
        if n == 0 or not isinstance(df.index, pd.DatetimeIndex):
            self.update()
            return
        self._t0 = pd.Timestamp(df.index[0])
        self._t1 = pd.Timestamp(df.index[-1])
        buckets = max(20, min(buckets, n))
        tv = df.index.asi8.astype(np.float64)
        t0v, t1v = float(tv[0]), float(tv[-1])
        span = max(t1v - t0v, 1.0)
        bidx = np.clip(((tv - t0v) / span * buckets).astype(np.int64),
                       0, buckets - 1)
        cnt = np.bincount(bidx, minlength=buckets).astype(np.float64)
        for col in cols:
            if col not in df.columns:
                continue
            pres = pd.notna(df[col].to_numpy()).astype(np.float64)
            s = np.bincount(bidx, weights=pres, minlength=buckets)
            frac = np.divide(s, cnt, out=np.zeros(buckets), where=cnt > 0)
            self._rows.append((display_name(col), frac))
        self.update()

    def paintEvent(self, ev):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#ffffff'))
        if not self._rows or self._t0 is None:
            painter.end()
            return
        w = self.width()
        label_w = min(210, max(120, w // 5))
        top = 4
        bottom = 30
        h = max(self.height() - top - bottom, 10)
        n_rows = len(self._rows)
        row_h = max(3.0, min(26.0, h / n_rows))
        font = QFont(self.font())
        font.setPointSizeF(7.5)
        painter.setFont(font)
        span = max((self._t1 - self._t0).total_seconds(), 1.0)
        plot_w = w - label_w - 6

        def tx(ts):
            return (label_w + (pd.Timestamp(ts) - self._t0).total_seconds()
                    / span * plot_w)

        # 月份网格线与标签
        months = pd.date_range(self._t0.replace(day=1), self._t1, freq='MS')
        painter.setPen(QPen(QColor('#d5d8dc'), 1))
        for m in months:
            x = tx(m)
            painter.drawLine(int(x), top, int(x), int(top + h))
        # 每行色带（连续有效桶合并为矩形，缺测桶留白）
        buckets = len(self._rows[0][1])
        bx = plot_w / buckets
        for ri, (label, frac) in enumerate(self._rows):
            y = top + ri * row_h
            color = QColor(self.PALETTE[ri % len(self.PALETTE)])
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            present = np.flatnonzero(frac >= 0.5)
            if len(present):
                splits = np.flatnonzero(np.diff(present) > 1)
                starts = np.r_[present[0], present[splits + 1]]
                ends = np.r_[present[splits], present[-1]]
                for s, e in zip(starts, ends):
                    painter.drawRect(QRectF(label_w + s * bx, y + 1.0,
                                            (e - s + 1) * bx, row_h - 2.0))
            painter.setPen(QColor('#2c3e50'))
            painter.drawText(QRectF(0, y, label_w - 6, row_h),
                             Qt.AlignRight | Qt.AlignVCenter, label)
        # 月份名 + 年份
        painter.setPen(QColor('#566573'))
        for m in months:
            x = tx(m)
            painter.drawText(QRectF(x - 16, top + h + 2, 34, 12),
                             Qt.AlignCenter, m.strftime('%b'))
        for yr in sorted({m.year for m in months}):
            ya = max(self._t0, pd.Timestamp(yr, 1, 1))
            yb = min(self._t1, pd.Timestamp(yr, 12, 31, 23, 59))
            xc = (tx(ya) + tx(yb)) / 2
            painter.drawText(QRectF(xc - 24, top + h + 14, 48, 12),
                             Qt.AlignCenter, str(yr))
        painter.end()


class FillGapsDialog(QDialog):
    HELP = ('Choose an action, select the data columns to fill, then click '
            'Fill Gaps. The timeline below shows data coverage before '
            'filling; white stripes mark missing segments.')

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Fill Gaps'))
        self.resize(980, 640)
        self._ds = ds
        self._cols_all = _numeric_cols(ds)
        self._nan_count: dict[str, int] = {}
        self._runs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._dt_hours = 1.0
        self._info = ''

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        top = QHBoxLayout()
        # 左侧：动作与范围（对齐原版）
        left = QVBoxLayout()
        left.addWidget(QLabel(tr('What action should Windographer perform?')))
        self.rb_recon = QRadioButton(
            tr('Reconstruct using data from other heights where available'))
        self.rb_synth = QRadioButton(
            tr('Reconstruct, then fill remaining gaps with synthetic data'))
        self.rb_recon.setChecked(True)
        self._bg_action = QButtonGroup(self)
        self._bg_action.addButton(self.rb_recon)
        self._bg_action.addButton(self.rb_synth)
        left.addWidget(self.rb_recon)
        left.addWidget(self.rb_synth)
        left.addSpacing(12)
        left.addWidget(QLabel(tr('Fill gaps in')))
        self.rb_all = QRadioButton(tr('all time steps'))
        self.rb_seg = QRadioButton(tr('particular time segment'))
        self.rb_all.setChecked(True)
        self._bg_range = QButtonGroup(self)
        self._bg_range.addButton(self.rb_all)
        self._bg_range.addButton(self.rb_seg)
        left.addWidget(self.rb_all)
        left.addWidget(self.rb_seg)
        self.seg0 = _DateTimeRow(tr('Start time'))
        self.seg1 = _DateTimeRow(tr('End time'))
        left.addWidget(self.seg0)
        left.addWidget(self.seg1)
        self.chk_flag = QCheckBox(tr('Flag gap filled segments with'))
        self.chk_flag.setChecked(True)
        self.flag_gap = QComboBox()
        self.flag_gap.addItems(['Synthesized', 'Icing', 'Invalid',
                                'Low quality', 'Tower shading'])
        fl = QHBoxLayout()
        fl.addWidget(self.chk_flag)
        fl.addWidget(self.flag_gap, 1)
        left.addLayout(fl)
        left.addStretch(1)
        top.addLayout(left, 1)

        # 中间：通道勾选列表（全部默认勾选）
        mid = QVBoxLayout()
        mid.addWidget(QLabel(tr('Fill gaps in the following data columns:')))
        self.chk_sel_all = QCheckBox(tr('Select all'))
        self.chk_sel_all.setChecked(True)
        self.chk_sel_all.stateChanged.connect(self._on_select_all)
        mid.addWidget(self.chk_sel_all)
        self.col_listw = QListWidget()
        self.col_listw.setSelectionMode(QAbstractItemView.NoSelection)
        self.col_listw.setUniformItemSizes(True)
        for c in self._cols_all:
            item = QListWidgetItem(display_name(c))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, c)
            self.col_listw.addItem(item)
        self.col_listw.itemChanged.connect(self._queue_update)
        mid.addWidget(self.col_listw, 1)
        top.addLayout(mid, 1)

        # 右侧：统计表
        stats_w = QWidget()
        sl = QVBoxLayout(stats_w)
        sl.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(7, 3)
        self.table.setHorizontalHeaderLabels([
            tr('Statistic'), tr('Entire Data Set'), tr('Selected Subset')])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        sl.addWidget(self.table)
        top.addWidget(stats_w, 1)
        lay.addLayout(top, 1)

        # 底部：时间线（仅打开时计算一次，与勾选无关）
        self.timeline = CoverageTimeline()
        self.timeline.setMinimumHeight(210)
        lay.addWidget(self.timeline, 1)

        # 按钮
        btns = QHBoxLayout()
        btns.addStretch(1)
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, tr('Help'), tr(self.HELP)))
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('Fill Gaps...'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(help_btn)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        # 事件：勾选/区间变化 → 250ms 防抖后仅刷新统计表（毫秒级）
        self.rb_all.toggled.connect(self._on_range_mode)
        self._range_widgets = (self.seg0.date, self.seg0.time,
                               self.seg1.date, self.seg1.time)
        for wgt in self._range_widgets:
            wgt.dateTimeChanged.connect(self._queue_update)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_stats)

        if not ds.df.empty:
            self.seg0.set_dt(pd.Timestamp(ds.df.index[0]))
            self.seg1.set_dt(pd.Timestamp(ds.df.index[-1]))
        self._set_seg_enabled(False)
        self._build_cache()
        self.timeline.set_data(ds.df, self._cols_all)
        self._update_stats()

    # ---- 交互 ----
    def _on_select_all(self, state):
        chk = Qt.Checked if state == Qt.Checked else Qt.Unchecked
        for i in range(self.col_listw.count()):
            self.col_listw.item(i).setCheckState(chk)

    def _on_range_mode(self, all_mode):
        self._set_seg_enabled(not all_mode)
        self._queue_update()

    def _set_seg_enabled(self, on: bool):
        self.seg0.setEnabled(on)
        self.seg1.setEnabled(on)

    def _queue_update(self, *args):
        self._timer.start()

    def _checked_cols(self) -> list[str]:
        out = []
        for i in range(self.col_listw.count()):
            it = self.col_listw.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    # ---- 一次性缓存（向量化，毫秒级）----
    def _build_cache(self):
        df = self._ds.df
        if df.empty or not isinstance(df.index, pd.DatetimeIndex):
            return
        if len(df) > 1:
            diffs = pd.Series(df.index).diff().dropna()
            self._dt_hours = max(pd.Timedelta(
                diffs.median()).total_seconds() / 3600.0, 1e-9)
        for col in self._cols_all:
            if col not in df.columns:
                continue
            miss = pd.isna(df[col].to_numpy())
            self._nan_count[col] = int(miss.sum())
            m8 = miss.astype(np.int8)
            d = np.diff(m8)
            starts = np.flatnonzero(d == 1) + 1
            ends = np.flatnonzero(d == -1) + 1
            if miss[0]:
                starts = np.r_[0, starts]
            if miss[-1]:
                ends = np.r_[ends, m8.size]
            self._runs[col] = (starts, ends)

    def _row_range(self) -> tuple[int, int]:
        n = len(self._ds.df)
        if self.rb_all.isChecked() or n == 0:
            return 0, n
        idx = self._ds.df.index
        a = int(idx.searchsorted(pd.Timestamp(self.seg0.get_dt())))
        b = int(idx.searchsorted(pd.Timestamp(self.seg1.get_dt()),
                                 side='right'))
        return a, max(b, a)

    # ---- 统计（选择变化时仅做向量运算，O(k) 汇总 + 区间裁剪）----
    def _gap_stats(self, cols: list[str], i0: int, i1: int) -> tuple:
        n_gaps = 0
        lens = []
        for col in cols:
            r = self._runs.get(col)
            if r is None:
                continue
            s, e = r
            sel = (s < i1) & (e > i0)
            if not sel.any():
                continue
            ss = np.clip(s[sel], i0, i1)
            ee = np.clip(e[sel], i0, i1)
            n_gaps += int(sel.sum())
            lens.append((ee - ss) * self._dt_hours)
        if n_gaps:
            all_lens = np.concatenate(lens)
            return n_gaps, float(all_lens.mean()), float(all_lens.min()), \
                float(all_lens.max())
        return 0, 0.0, 0.0, 0.0

    def _update_stats(self):
        df = self._ds.df
        cols = self._checked_cols()
        n = len(df)
        if not cols or n == 0:
            self.table.setRowCount(0)
            return
        k = len(cols)
        i0, i1 = self._row_range()
        span = max(i1 - i0, 0)

        total_all = n * k
        miss_all = sum(self._nan_count.get(c, 0) for c in cols)
        comp_all = 100.0 * (total_all - miss_all) / total_all if total_all else 0.0
        g_all = self._gap_stats(cols, 0, n)

        total_sub = span * k
        miss_sub = 0
        for c in cols:
            if c in df.columns:
                miss_sub += int(pd.isna(df[c].to_numpy()[i0:i1]).sum())
        comp_sub = (100.0 * (total_sub - miss_sub) / total_sub
                    if total_sub else 0.0)
        g_sub = self._gap_stats(cols, i0, i1)

        rows = [
            (tr('Total data points'), f'{total_all:,}', f'{total_sub:,}'),
            (tr('Missing data points'), f'{miss_all:,}', f'{miss_sub:,}'),
            (tr('Data completeness (%)'), f'{comp_all:.1f}', f'{comp_sub:.1f}'),
            (tr('Number of gaps'), f'{g_all[0]:,}', f'{g_sub[0]:,}'),
            (tr('Mean gap length (hr)'), f'{g_all[1]:.1f}', f'{g_sub[1]:.1f}'),
            (tr('Shortest gap (hr)'), f'{g_all[2]:.1f}', f'{g_sub[2]:.1f}'),
            (tr('Longest gap (hr)'), f'{g_all[3]:.1f}', f'{g_sub[3]:.1f}'),
        ]
        self.table.setRowCount(len(rows))
        for r, (name, a, b) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(a))
            self.table.setItem(r, 2, QTableWidgetItem(b))

    # ---- 执行 ----
    def _reconstruct(self, col: str, i0: int, i1: int, synth: bool):
        """用同类其它高度通道重建，synth=True 时再线性填补剩余缺测。"""
        ds = self._ds
        df = ds.df
        seg = df[col].iloc[i0:i1].copy()
        ch = ds.channels.get(col)
        others = []
        for c in self._cols_all:
            if c == col or c not in df.columns:
                continue
            oc = ds.channels.get(c)
            if oc is not None and ch is not None and oc.kind == ch.kind:
                others.append(c)
        h0 = ch.height if ch is not None else None
        others.sort(key=lambda c: abs(
            (ds.channels[c].height or 0) - (h0 or 0)))
        for oc in others:
            need = pd.isna(seg.to_numpy())
            if not need.any():
                break
            src = df[oc].iloc[i0:i1]
            ok_vals = src.to_numpy()[need]
            good = ~pd.isna(ok_vals)
            idx = np.flatnonzero(need)[good]
            seg.iloc[idx] = src.to_numpy()[need][good]
        if synth:
            seg = _interp(seg, 'linear')
        return seg

    def _on_ok(self):
        cols = self._checked_cols()
        if not cols:
            QMessageBox.warning(self, tr('No columns'),
                                tr('Please select at least one data column'))
            return
        df = self._ds.df
        if df.empty:
            self.reject()
            return
        i0, i1 = self._row_range()
        use_recon = self.rb_recon.isChecked()
        n_fill = 0
        for col in cols:
            if col not in df.columns:
                continue
            before = int(pd.isna(df[col].to_numpy()[i0:i1]).sum())
            if before == 0:
                continue
            filled = self._reconstruct(col, i0, i1, synth=not use_recon)
            df.iloc[i0:i1, df.columns.get_loc(col)] = filled.to_numpy()
            after = int(pd.isna(df[col].to_numpy()[i0:i1]).sum())
            n_fill += before - after
        self._info = tr('Filled {} data points in {} columns',
                        n_fill, len(cols))
        self.accept()

    def result_info(self):
        return self._info
