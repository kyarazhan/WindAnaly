"""fix_quantization.py：见 _common 与 shim。"""
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

from ._common import (_numeric_cols, _to_num, _col_from_display, _DateTimeRow)

class FixQuantizationDialog(QDialog):
    HELP = ('Detect quantization in a data column and add small random '
            'offsets to each data point so the distribution no longer '
            'shows empty bins. The left histogram shows the original data; '
            'the right shows the randomized data.')

    ORIG_COLOR = '#1f4e79'    # 原版：原始数据深蓝
    FIX_COLOR = '#8f5900'     # 原版：修改后数据棕黄

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Fix Quantization'))
        self.resize(900, 580)
        self._ds = ds
        self._step: float = 1.0
        self._month: pd.Timestamp | None = None
        self._info = ''
        self._orig_disp: pd.Series | None = None
        self._fixed_disp: pd.Series | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        # ---- 顶部：第一行 Data column + Modify；第二行 Display（对齐原版）----
        top = QGridLayout()
        top.setHorizontalSpacing(14)
        top.addWidget(QLabel(tr('Data column:')), 0, 0)
        self.channel = QComboBox()
        self.channel.addItems([display_name(c) for c in _numeric_cols(ds)])
        self.channel.setMinimumContentsLength(24)
        self.channel.currentIndexChanged.connect(self._update)
        top.addWidget(self.channel, 0, 1)
        top.setColumnStretch(1, 1)

        grp_mod = QGroupBox(tr('Modify'))
        mv = QVBoxLayout(grp_mod)
        hm = QHBoxLayout()
        self.m_all = QRadioButton(tr('all time steps'))
        self.m_int = QRadioButton(tr('only the interval:'))
        self.m_all.setChecked(True)
        self._bg_mod = QButtonGroup(self)
        self._bg_mod.addButton(self.m_all)
        self._bg_mod.addButton(self.m_int)
        hm.addWidget(self.m_all)
        hm.addWidget(self.m_int)
        hm.addStretch(1)
        mv.addLayout(hm)
        iv = QGridLayout()
        iv.addWidget(QLabel(tr('from')), 0, 0)
        self.int0 = _DateTimeRow('')
        iv.addWidget(self.int0, 0, 1)
        iv.addWidget(QLabel(tr('to')), 1, 0)
        self.int1 = _DateTimeRow('')
        iv.addWidget(self.int1, 1, 1)
        mv.addLayout(iv)
        top.addWidget(grp_mod, 0, 2, 2, 1)

        grp_disp = QGroupBox(tr('Display'))
        dh = QHBoxLayout(grp_disp)
        self.d_freq = QRadioButton(tr('frequency distributions'))
        self.d_time = QRadioButton(tr('time series graph'))
        self.d_freq.setChecked(True)
        self._bg_disp = QButtonGroup(self)
        self._bg_disp.addButton(self.d_freq)
        self._bg_disp.addButton(self.d_time)
        dh.addWidget(self.d_freq)
        dh.addWidget(self.d_time)
        top.addWidget(grp_disp, 1, 0, 1, 2)
        lay.addLayout(top)

        # ---- 图表区：频率=左右双直方图；时序=单图叠加 + 月份导航 ----
        self.stack = QStackedWidget()
        freq_w = QWidget()
        fh = QHBoxLayout(freq_w)
        fh.setContentsMargins(0, 0, 0, 0)
        self.c_orig = PlotCanvas(tr('Original Data'))
        self.c_fixed = PlotCanvas(tr('Modified Data'))
        for c in (self.c_orig, self.c_fixed):
            c.setMinimumHeight(240)
            fh.addWidget(c, 1)
        self.stack.addWidget(freq_w)

        time_w = QWidget()
        tv = QVBoxLayout(time_w)
        tv.setContentsMargins(0, 0, 0, 0)
        self.c_both = PlotCanvas('')
        tv.addWidget(self.c_both, 1)
        nav = QHBoxLayout()
        self.btn_prev_m = QPushButton('◀')
        self.btn_prev_m.setFixedWidth(34)
        self.btn_next_m = QPushButton('▶')
        self.btn_next_m.setFixedWidth(34)
        self.lbl_month = QLabel('')
        self.lbl_month.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        nav.addWidget(self.btn_prev_m)
        nav.addWidget(self.btn_next_m)
        nav.addWidget(self.lbl_month, 1)
        tv.addLayout(nav)
        self.stack.addWidget(time_w)
        lay.addWidget(self.stack, 1)
        self.btn_prev_m.clicked.connect(lambda: self._shift_month(-1))
        self.btn_next_m.clicked.connect(lambda: self._shift_month(1))

        # ---- 底部：Help + 信息提示 + Cancel/OK（同原版一行）----
        bottom = QHBoxLayout()
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, tr('Help'), tr(self.HELP)))
        bottom.addWidget(help_btn)
        info_icon = QLabel('ⓘ')
        info_icon.setStyleSheet('color:#2c7be5; font-size:16px;')
        bottom.addWidget(info_icon)
        self.info_lbl = QLabel()
        self.info_lbl.setStyleSheet('color:#5a6573; font-size:11px;')
        self.info_lbl.setWordWrap(True)
        bottom.addWidget(self.info_lbl, 1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('OK'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        bottom.addWidget(cancel)
        bottom.addWidget(ok)
        lay.addLayout(bottom)

        # ---- 事件 ----
        self.d_freq.toggled.connect(lambda _c: self._update())
        self.m_all.toggled.connect(lambda _c: self._update())
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._update)
        for wgt in (self.int0.date, self.int0.time, self.int1.date, self.int1.time):
            wgt.dateTimeChanged.connect(self._debounce.start)

        if not ds.df.empty:
            self.int0.set_dt(pd.Timestamp(ds.df.index[0]))
            self.int1.set_dt(pd.Timestamp(ds.df.index[-1]))
        self._update()

    # ---- 基础 ----
    def _col(self) -> str | None:
        if self.channel.count() == 0:
            return None
        return _col_from_display(self._ds, self.channel.currentText())

    def _mask(self) -> pd.Series:
        if self.m_all.isChecked() or self._ds.df.empty:
            return pd.Series(True, index=self._ds.df.index)
        a = self.int0.get_dt()
        b = self.int1.get_dt()
        return (self._ds.df.index >= a) & (self._ds.df.index <= b)

    def _detect_step(self, s: pd.Series) -> float:
        vals = s.dropna().sort_values().unique()
        if len(vals) < 2:
            return 1.0
        diffs = np.diff(vals)
        diffs = diffs[diffs > 1e-12]
        if len(diffs) == 0:
            return 1.0
        from collections import Counter
        rounded = np.round(diffs, decimals=max(
            0, 3 - int(math.log10(max(diffs.min(), 1e-9)))))
        step = float(Counter(rounded).most_common(1)[0][0])
        if step <= 0:
            step = float(np.median(diffs))
        return max(step, 1e-6)

    def _fixed(self, s: pd.Series, step: float, col: str) -> pd.Series:
        # 固定随机种子：同一列每次预览噪声一致（原版行为：预览稳定）
        rng = np.random.default_rng(abs(hash(col)) % (2 ** 32))
        noise = rng.uniform(-step / 2, step / 2, size=len(s))
        return s + noise

    def _unit_of(self, col: str) -> str:
        return next((c.units for c in self._ds.channels.values()
                     if c.name == col), '')

    # ---- 绘制 ----
    def _hist_density(self, s: pd.Series):
        """返回 (edges, density%)：密度 = 占比% / 单位宽度，同原版
        Frequency Density (%/m/s) 轴。"""
        vals = s.dropna()
        if len(vals) == 0:
            return np.array([0.0, 1.0]), np.array([])
        lo, hi = float(vals.min()), float(vals.max())
        if hi <= lo:
            hi = lo + max(abs(lo) * 0.1, 1.0)
        edges = np.linspace(lo, hi, 41)
        counts, _ = np.histogram(vals, bins=edges)
        bin_w = edges[1] - edges[0]
        dens = counts / max(len(vals), 1) / bin_w * 100.0
        return edges, dens

    def _draw_freq(self, col: str):
        unit = self._unit_of(col)
        ylabel = tr('Frequency Density') + (f' (%/{unit})' if unit else ' (%)')
        xlabel = display_name(col) + (f' ({unit})' if unit else '')
        edges, dens_o = self._hist_density(self._orig_disp)
        _, dens_f = self._hist_density(self._fixed_disp)
        for canvas, dens, color, title in (
                (self.c_orig, dens_o, self.ORIG_COLOR, tr('Original Data')),
                (self.c_fixed, dens_f, self.FIX_COLOR, tr('Modified Data'))):
            canvas.set_title(title)
            canvas.plot_histogram(edges, dens, xlabel=xlabel, ylabel=ylabel,
                                  color=color)

    def _month_title(self, m: pd.Timestamp) -> str:
        if language() == 'en':
            names = ['January', 'February', 'March', 'April', 'May', 'June',
                     'July', 'August', 'September', 'October', 'November',
                     'December']
            return f'{names[m.month - 1]} {m.year}'
        return f'{m.year}年{m.month}月'

    def _init_month(self):
        if self._month is None and self._orig_disp is not None \
                and len(self._orig_disp):
            t0 = self._orig_disp.index[0]
            self._month = pd.Timestamp(t0.year, t0.month, 1)

    def _shift_month(self, k: int):
        if self._month is None:
            return
        m = self._month.month + k
        y = self._month.year
        if m == 0:
            m, y = 12, y - 1
        elif m == 13:
            m, y = 1, y + 1
        self._month = pd.Timestamp(y, m, 1)
        self._draw_time()

    def _draw_time(self):
        if self._month is None or self._orig_disp is None:
            return
        col = self._cur_col
        m0 = self._month
        m1 = m0 + pd.offsets.MonthBegin(1)
        o = self._orig_disp[(self._orig_disp.index >= m0)
                            & (self._orig_disp.index < m1)]
        f = self._fixed_disp[(self._fixed_disp.index >= m0)
                             & (self._fixed_disp.index < m1)]
        title = self._month_title(m0)
        self.c_both.set_title(title)
        self.lbl_month.setText(title)

        # x = 月内日 + 一天内的时刻比例（1..31 数轴，同原版）
        def dayx(index):
            return (index.day
                    + (index.hour * 60 + index.minute) / 1440.0).to_numpy()

        lbl_o = f'{display_name(col)} ({tr("original")})'
        lbl_f = f'{display_name(col)} ({tr("modified")})'
        self.c_both.set_series_color(lbl_o, self.ORIG_COLOR)
        self.c_both.set_series_color(lbl_f, self.FIX_COLOR)
        self.c_both.plot_lines(
            [(lbl_o, dayx(o.index), o.to_numpy()),
             (lbl_f, dayx(f.index), f.to_numpy())],
            ylabel=self._unit_of(col), xtick_step=2)

    # ---- 刷新 ----
    def _update(self):
        col = self._col()
        if col is None or col not in self._ds.df.columns:
            self.c_orig.clear(tr('No data'))
            self.c_fixed.clear(tr('No data'))
            self.c_both.clear(tr('No data'))
            return
        self._cur_col = col
        s = _to_num(self._ds.df[col])
        self._step = self._detect_step(s)
        mask = self._mask()
        self._orig_disp = s[mask]
        self._fixed_disp = self._fixed(s, self._step, col)[mask]
        self._month = None
        if self.d_freq.isChecked():
            self.stack.setCurrentIndex(0)
            self._draw_freq(col)
        else:
            self.stack.setCurrentIndex(1)
            self._init_month()
            self._draw_time()

        ratio = s.nunique() / max(len(s.dropna()), 1)
        if ratio < 0.1:
            msg = tr('Your data is highly quantized. This operation will '
                     'have a significant effect on your data.')
        elif ratio < 0.3:
            msg = tr('Your data shows moderate quantization. This operation '
                     'may have a moderate effect on your data.')
        else:
            msg = tr('Your data is not very highly quantized. Using this '
                     'window will likely not have a significant effect on '
                     'your data.')
        self.info_lbl.setText(f'{msg} (detected step ≈ {self._step:.4g})')

    # ---- 执行 ----
    def _on_ok(self):
        col = self._col()
        if not col or col not in self._ds.df.columns:
            return
        s = _to_num(self._ds.df[col])
        self._step = self._detect_step(s)
        mask = self._mask()
        fixed = self._fixed(s, self._step, col)
        self._ds.df.loc[mask, col] = fixed.where(mask, s)
        self._info = tr('Quantization fixed: {} (step {})',
                        display_name(col), f'{self._step:.4g}')
        self.accept()

    def result_info(self):
        return self._info
