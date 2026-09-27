"""Compare 菜单对话框：Compare Data Sets + Measure Correlate Predict (MCP)。

按 Windographer 风格实现 UI 骨架与基础计算，复杂算法后续按真机反馈精调。
"""
from __future__ import annotations

import math
import os
import re
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QRadioButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.dataset import KIND_DIR, KIND_SPEED, Channel, Dataset
from core.io_import import parse_file
from ui.modules.analysis_tabs import display_name
from ui.modules.plot import PlotCanvas
from core.i18n import tr


# ------------------------------------------------------------------ 工具函数
def _numeric_cols(ds: Dataset) -> list[str]:
    kinds = {'speed', 'dir', 'temp', 'pres', 'rh', 'ti', 'synthetic'}
    return [c.name for c in ds.channels.values() if c.kind in kinds]


def _speed_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind == KIND_SPEED]


def _dir_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind == KIND_DIR]


def _col_disp(ds: Dataset, name: str) -> str:
    return display_name(name)


def _height_of(name: str) -> float | None:
    m = re.search(r'(\d+(?:\.\d+)?)\s*m', name, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r'(?<!\d)(\d{2,3})(?=[mM]|\b)', name)
    if m:
        v = float(m.group(1))
        if 5 <= v <= 500:
            return v
    return None


def _step_to_freq(step_text: str) -> str | None:
    """MCP 时间步下拉文本 → pandas 重采样频率别名。"""
    s = (step_text or '').lower()
    if '10 minute' in s:
        return '10min'
    if '60 minute' in s or '1 hour' in s:
        return '60min'
    m = re.search(r'(\d+)\s*hour', s)
    if m:
        return f'{int(m.group(1))}h'
    d = re.search(r'(\d+)\s*day', s)
    if d:
        return f'{int(d.group(1))}D'
    return None


def _freq_to_hours(freq: str) -> int:
    """pandas 频率别名 → 小时数。"""
    if freq.endswith('min'):
        v = int(freq[:-3]) // 60
        return max(1, v)
    if freq.endswith('h'):
        return int(freq[:-1])
    if freq.endswith('D'):
        return int(freq[:-1]) * 24
    return 1


def _capped_corr(a: np.ndarray, b: np.ndarray) -> float:
    """安全 Pearson 相关（有限值、剔常值）。"""
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if len(a) < 3 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return -2.0
    return float(np.corrcoef(a, b)[0, 1])


def _diurnal_profile(s: pd.Series) -> pd.Series:
    """逐小时平均日变化。"""
    if s.empty:
        return pd.Series(dtype=float)
    return s.groupby(s.index.hour).mean()


def _monthly_profile(s: pd.Series) -> pd.Series:
    """逐月平均。"""
    if s.empty:
        return pd.Series(dtype=float)
    return s.groupby(s.index.month).mean()


def _wind_rose(dir_s: pd.Series, speed_s: pd.Series | None = None,
               sectors: int = 16):
    """返回 (sector_centers, frequencies_by_bin)。"""
    if dir_s.empty:
        return np.array([]), np.array([])
    bins = np.linspace(0, 360, sectors + 1)
    centers = (bins[:-1] + bins[1:]) / 2
    if speed_s is None or speed_s.empty:
        counts, _ = np.histogram(dir_s.dropna(), bins=bins)
        return centers, counts / max(counts.sum(), 1) * 100
    # 按风速分档统计频率
    spd = speed_s.reindex(dir_s.index)
    freq = np.zeros((len(centers), 3))
    mask_lo = (spd >= 0) & (spd < 5)
    mask_md = (spd >= 5) & (spd < 10)
    mask_hi = spd >= 10
    for i in range(len(centers)):
        lo = (dir_s >= bins[i]) & (dir_s < bins[i + 1]) & mask_lo
        md = (dir_s >= bins[i]) & (dir_s < bins[i + 1]) & mask_md
        hi = (dir_s >= bins[i]) & (dir_s < bins[i + 1]) & mask_hi
        freq[i, 0] = lo.sum()
        freq[i, 1] = md.sum()
        freq[i, 2] = hi.sum()
    total = freq.sum()
    if total > 0:
        freq = freq / total * 100
    return centers, freq


def _weibull_mle(x: np.ndarray):
    x = np.asarray(x, dtype=float)
    x = x[(x > 0) & np.isfinite(x)]
    if len(x) < 5:
        return None, None
    mean = x.mean()
    std = x.std(ddof=1)
    if std <= 0:
        return None, None
    k = (mean / std) ** (-1.086)
    if k <= 0:
        return None, None
    c = mean / math.gamma(1.0 + 1.0 / k)
    return k, c


# ------------------------------------------------------------------ 可复用组件
class _CheckList(QWidget):
    """带全选复选框的多选列表。"""

    def __init__(self, title: str = '', parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.sel_all = QCheckBox(tr('Select all'))
        self.sel_all.stateChanged.connect(self._on_all)
        top.addWidget(self.sel_all)
        top.addStretch(1)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.MultiSelection)
        lay.addWidget(self.list)
        self._items: dict[str, QListWidgetItem] = {}

    def set_items(self, names: list[str]):
        self.list.clear()
        self._items.clear()
        for n in names:
            item = QListWidgetItem(n)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, n)
            self.list.addItem(item)
            self._items[n] = item

    def checked_data(self) -> list[str]:
        out = []
        for item in self._items.values():
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out

    def _on_all(self, state):
        chk = Qt.Checked if state == Qt.Checked.value else Qt.Unchecked
        for item in self._items.values():
            item.setCheckState(chk)


# ------------------------------------------------------------------ 1. Compare Data Sets
class CompareDataSetsDialog(QDialog):
    """多数据集对比：Display 类型切换 + Settings + 多图展示。"""

    DISPLAYS = [
        'Summary', 'Diurnal profile', 'Vertical profile',
        'Monthly profile', 'Wind rose', 'Time series',
    ]

    def __init__(self, datasets: list[Dataset], parent=None):
        super().__init__(parent)
        self.datasets = datasets or []
        self.setWindowTitle(tr('Compare Data Sets'))
        self.setMinimumSize(1100, 760)
        self.resize(1200, 820)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # 左侧
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)

        gb_open = QGroupBox(tr('Open data sets'))
        gv = QVBoxLayout(gb_open)
        self.lst_datasets = QListWidget()
        self.lst_datasets.setSelectionMode(QListWidget.MultiSelection)
        for ds in self.datasets:
            item = QListWidgetItem(ds.name)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, id(ds))
            self.lst_datasets.addItem(item)
        gv.addWidget(self.lst_datasets)
        lv.addWidget(gb_open)

        gb_disp = QGroupBox(tr('Display'))
        dv = QVBoxLayout(gb_disp)
        self.rg_display = []
        for d in self.DISPLAYS:
            rb = QRadioButton(d)
            rb.setChecked(d == 'Diurnal profile')
            rb.toggled.connect(self.refresh)
            self.rg_display.append(rb)
            dv.addWidget(rb)
        lv.addWidget(gb_disp)

        gb_set = QGroupBox(tr('Settings'))
        sv = QVBoxLayout(gb_set)
        self.rb_all_sensors = QRadioButton(tr('all sensors'))
        self.rb_high_sensor = QRadioButton(tr('highest sensor only'))
        self.rb_all_sensors.setChecked(True)
        h = QHBoxLayout()
        h.addWidget(QLabel(tr('Plot')))
        h.addWidget(self.rb_all_sensors)
        h.addWidget(self.rb_high_sensor)
        h.addStretch(1)
        sv.addLayout(h)
        self.chk_overlap = QCheckBox(tr('Overlap period only'))
        sv.addWidget(self.chk_overlap)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel(tr('Sectors')))
        self.sp_sectors = QSpinBox()
        self.sp_sectors.setRange(4, 36)
        self.sp_sectors.setValue(16)
        h2.addWidget(self.sp_sectors)
        h2.addStretch(1)
        sv.addLayout(h2)
        lv.addWidget(gb_set)
        lv.addStretch(1)
        splitter.addWidget(left)

        # 右侧：多图网格
        self.right = QWidget()
        self.rv = QGridLayout(self.right)
        self.rv.setContentsMargins(0, 0, 0, 0)
        self.rv.setSpacing(8)
        self.plots: list[PlotCanvas] = []
        splitter.addWidget(self.right)
        splitter.setSizes([300, 900])

        # 底部按钮
        btns = QHBoxLayout()
        self.btn_help = QPushButton(tr('Help'))
        self.btn_close = QPushButton(tr('Close'))
        self.btn_close.clicked.connect(self.reject)
        btns.addWidget(self.btn_help)
        btns.addStretch(1)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        # 连接
        self.lst_datasets.itemChanged.connect(self.refresh)
        self.chk_overlap.stateChanged.connect(self.refresh)
        self.sp_sectors.valueChanged.connect(self.refresh)
        self.rb_all_sensors.toggled.connect(self.refresh)
        self.rb_high_sensor.toggled.connect(self.refresh)

        self.refresh()

    def _selected_datasets(self) -> list[Dataset]:
        selected = []
        for i in range(self.lst_datasets.count()):
            item = self.lst_datasets.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(self.datasets[i])
        return selected

    def _active_display(self) -> str:
        for rb in self.rg_display:
            if rb.isChecked():
                return rb.text()
        return 'Diurnal profile'

    def _clear_plots(self, n: int):
        """确保右侧有 n 个 PlotCanvas。"""
        while len(self.plots) < n:
            p = PlotCanvas()
            p.setMinimumHeight(220)
            self.plots.append(p)
        # 移除多余的
        for _ in range(len(self.plots) - n):
            w = self.plots.pop()
            w.setParent(None)
        # 清空布局
        while self.rv.count():
            it = self.rv.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
        for idx, p in enumerate(self.plots):
            row, col = divmod(idx, 2)
            self.rv.addWidget(p, row, col)

    def refresh(self):
        dss = self._selected_datasets()
        disp = self._active_display()
        sectors = self.sp_sectors.value()

        if disp == 'Summary':
            self._show_summary(dss)
        elif disp == 'Diurnal profile':
            self._show_diurnal(dss)
        elif disp == 'Vertical profile':
            self._show_vertical(dss)
        elif disp == 'Monthly profile':
            self._show_monthly(dss)
        elif disp == 'Wind rose':
            self._show_wind_rose(dss, sectors)
        elif disp == 'Time series':
            self._show_time_series(dss)

    def _speed_series(self, ds: Dataset) -> list[tuple[str, pd.Series]]:
        """返回 [(显示名, series), ...]，受传感器设置影响。"""
        cols = _speed_cols(ds)
        if self.rb_high_sensor.isChecked():
            by_h = {(_height_of(c) or 0): c for c in cols}
            if by_h:
                cols = [by_h[max(by_h)]]
        return [(_col_disp(ds, c), pd.to_numeric(ds.df[c], errors='coerce'))
                for c in cols if c in ds.df.columns]

    def _dir_series(self, ds: Dataset) -> tuple[str, pd.Series] | None:
        cols = _dir_cols(ds)
        if not cols:
            return None
        if self.rb_high_sensor.isChecked():
            by_h = {(_height_of(c) or 0): c for c in cols}
            cols = [by_h[max(by_h)]] if by_h else cols
        c = cols[0]
        return _col_disp(ds, c), pd.to_numeric(ds.df[c], errors='coerce')

    def _show_summary(self, dss: list[Dataset]):
        self._clear_plots(1)
        self.plots[0].clear('Summary table view')

    def _show_diurnal(self, dss: list[Dataset]):
        self._clear_plots(2)
        series = []
        for ds in dss:
            for label, s in self._speed_series(ds):
                prof = _diurnal_profile(s)
                if not prof.empty:
                    series.append((f'{ds.name}: {label}', prof.index.values, prof.values))
        if series:
            self.plots[0].plot_lines(series, xlabel='Hour of Day',
                                     ylabel='Mean Wind Speed (m/s)')
            self.plots[0].set_title('Mean Diurnal Profile')
        else:
            self.plots[0].clear()

        series2 = []
        for ds in dss:
            for label, s in self._speed_series(ds):
                monthly = _monthly_profile(s)
                if not monthly.empty:
                    series2.append((f'{ds.name}: {label}', monthly.index.values, monthly.values))
        if series2:
            self.plots[1].plot_lines(series2, xlabel='Month',
                                     ylabel='Mean Wind Speed (m/s)')
            self.plots[1].set_title('Mean Monthly Profile')
        else:
            self.plots[1].clear()

    def _show_vertical(self, dss: list[Dataset]):
        self._clear_plots(1)
        series = []
        for ds in dss:
            heights = []
            means = []
            for c in _speed_cols(ds):
                if c not in ds.df.columns:
                    continue
                h = _height_of(c)
                if h is None:
                    continue
                s = pd.to_numeric(ds.df[c], errors='coerce')
                if not s.empty:
                    heights.append(h)
                    means.append(s.mean())
            if heights:
                series.append((ds.name, np.array(heights), np.array(means)))
        if series:
            self.plots[0].plot_lines(series, xlabel='Mean Wind Speed (m/s)',
                                     ylabel='Height Above Ground (m)')
            self.plots[0].set_title('Vertical Wind Shear Profile')
        else:
            self.plots[0].clear()

    def _show_monthly(self, dss: list[Dataset]):
        self._clear_plots(2)
        self._show_diurnal(dss)

    def _show_wind_rose(self, dss: list[Dataset], sectors: int):
        self._clear_plots(2)
        if len(dss) >= 1:
            ds = dss[0]
            d = self._dir_series(ds)
            s = self._speed_series(ds)
            spd = s[0][1] if s else None
            if d:
                centers, freq = _wind_rose(d[1], spd, sectors)
                self.plots[0].plot_polar(centers, freq, title='Wind Frequency Rose')
            else:
                self.plots[0].clear()
        if len(dss) >= 2:
            ds = dss[1]
            d = self._dir_series(ds)
            s = self._speed_series(ds)
            spd = s[0][1] if s else None
            if d:
                centers, freq = _wind_rose(d[1], spd, sectors)
                self.plots[1].plot_polar(centers, freq, title='Wind Frequency Rose')
            else:
                self.plots[1].clear()

    def _show_time_series(self, dss: list[Dataset]):
        self._clear_plots(2)
        for idx, plot in enumerate(self.plots):
            if idx < len(dss):
                ds = dss[idx]
                series = []
                for label, s in self._speed_series(ds):
                    series.append((label, ds.df.index, s))
                if series:
                    plot.plot_lines(series, xlabel='Time',
                                    ylabel='Wind Speed (m/s)')
                    plot.set_title(ds.name)
                else:
                    plot.clear()
            else:
                plot.clear()


# ------------------------------------------------------------------ 2. Measure Correlate Predict
class _MCPImportTab(QWidget):
    """Import Data Tab：按 Windographer 截图布局重构。

    结构：
    - 顶部三栏：Target data set / Reference data set / Settings
      （Settings 含 Time step of / Offset reference data / Calculate...）
    - 底部三列属性表：Target / Reference / Final，每表两列 Property | Original。
    """

    def __init__(self, datasets: list[Dataset], parent=None):
        super().__init__(parent)
        self.datasets = datasets
        self.target_ds: Dataset | None = None
        self.ref_ds: Dataset | None = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(12)

        # ------------------ Target data set ------------------
        tg = QGroupBox(tr('Target data set'))
        tgv = QFormLayout(tg)
        tgv.setSpacing(6)

        self.cmb_target = QComboBox()
        self.cmb_target.addItem('<none loaded>', None)
        for ds in self.datasets:
            self.cmb_target.addItem(ds.name, ds)
        self.cmb_target.currentIndexChanged.connect(self._on_target_changed)
        self.btn_target_browse = QPushButton('...')
        self.btn_target_browse.setToolTip(tr('从文件导入数据集'))
        self.btn_target_browse.clicked.connect(self._browse_target)
        h = QHBoxLayout()
        h.addWidget(self.cmb_target, 1)
        h.addWidget(self.btn_target_browse)
        tgv.addRow('Target data set', h)

        self.cmb_tg_speed = QComboBox()
        self.cmb_tg_dir = QComboBox()
        tgv.addRow('Speed sensor', self.cmb_tg_speed)
        tgv.addRow('Direction sensor', self.cmb_tg_dir)

        self.cmb_tg_flag = QComboBox()
        self.cmb_tg_flag.addItems(['<Unflagged data>', 'Synthesized'])
        tgv.addRow('Flag', self.cmb_tg_flag)

        self.chk_tg_col = QCheckBox()
        self.cmb_tg_col = QComboBox()
        self.sp_tg_min = QDoubleSpinBox()
        self.sp_tg_min.setRange(-9999, 9999)
        self.sp_tg_min.setValue(0)
        self.sp_tg_min.setDecimals(2)
        self.sp_tg_max = QDoubleSpinBox()
        self.sp_tg_max.setRange(-9999, 9999)
        self.sp_tg_max.setValue(50)
        self.sp_tg_max.setDecimals(2)
        h2 = QHBoxLayout()
        h2.addWidget(self.cmb_tg_col)
        h2.addWidget(QLabel(tr('Min')))
        h2.addWidget(self.sp_tg_min)
        h2.addWidget(QLabel(tr('Max')))
        h2.addWidget(self.sp_tg_max)
        h2.addStretch(1)
        tgv.addRow(self.chk_tg_col, h2)

        top.addWidget(tg, 1)

        # ------------------ Reference data set ------------------
        rg = QGroupBox(tr('Reference data set'))
        rgv = QFormLayout(rg)
        rgv.setSpacing(6)

        self.cmb_ref = QComboBox()
        self.cmb_ref.addItem('<none loaded>', None)
        for ds in self.datasets:
            self.cmb_ref.addItem(ds.name, ds)
        self.cmb_ref.currentIndexChanged.connect(self._on_ref_changed)
        self.btn_ref_browse = QPushButton('...')
        self.btn_ref_browse.setToolTip(tr('从文件导入数据集'))
        self.btn_ref_browse.clicked.connect(self._browse_ref)
        h = QHBoxLayout()
        h.addWidget(self.cmb_ref, 1)
        h.addWidget(self.btn_ref_browse)
        rgv.addRow('Reference data set', h)

        self.cmb_ref_speed = QComboBox()
        self.cmb_ref_dir = QComboBox()
        rgv.addRow('Speed sensor', self.cmb_ref_speed)
        rgv.addRow('Direction sensor', self.cmb_ref_dir)

        self.cmb_ref_flag = QComboBox()
        self.cmb_ref_flag.addItems(['<Unflagged data>', 'Synthesized'])
        rgv.addRow('Flag', self.cmb_ref_flag)

        self.chk_ref_col = QCheckBox()
        self.cmb_ref_col = QComboBox()
        self.sp_ref_min = QDoubleSpinBox()
        self.sp_ref_min.setRange(-9999, 9999)
        self.sp_ref_min.setValue(0)
        self.sp_ref_min.setDecimals(2)
        self.sp_ref_max = QDoubleSpinBox()
        self.sp_ref_max.setRange(-9999, 9999)
        self.sp_ref_max.setValue(50)
        self.sp_ref_max.setDecimals(2)
        h2 = QHBoxLayout()
        h2.addWidget(self.cmb_ref_col)
        h2.addWidget(QLabel(tr('Min')))
        h2.addWidget(self.sp_ref_min)
        h2.addWidget(QLabel(tr('Max')))
        h2.addWidget(self.sp_ref_max)
        h2.addStretch(1)
        rgv.addRow(self.chk_ref_col, h2)

        top.addWidget(rg, 1)

        # ------------------ Settings ------------------
        setg = QGroupBox(tr('Settings'))
        setv = QVBoxLayout(setg)
        setv.setSpacing(10)

        self.cmb_timestep = QComboBox()
        self.cmb_timestep.addItems([
            '10 minutes', '60 minutes', '3 hours', '4 hours', '8 hours',
            '12 hours', '24 hours', '2 days', '3 days', '5 days',
            '7 days', '10 days', '30 days',
        ])
        self.cmb_timestep.setCurrentText('60 minutes')

        self.cmb_offset = QComboBox()
        self.cmb_offset.addItems(
            ['0 hours'] + [f'{i} hours ahead' for i in range(1, 25)]
            + [f'{i} hours back' for i in range(1, 25)][::-1])

        self.btn_calc = QPushButton(tr('Calculate...'))
        self.btn_calc.clicked.connect(self._calc_offset)

        h_set = QHBoxLayout()
        h_set.addWidget(QLabel(tr('Time step of')))
        h_set.addWidget(self.cmb_timestep)
        h_set.addSpacing(12)
        h_set.addWidget(QLabel(tr('Offset reference data')))
        h_set.addWidget(self.cmb_offset)
        h_set.addStretch(1)
        h_set.addWidget(self.btn_calc)
        setv.addLayout(h_set)

        setv.addStretch(1)

        top.addWidget(setg, 0)

        root.addLayout(top)

        # ------------------ 属性表 ------------------
        bot = QHBoxLayout()
        bot.setSpacing(8)

        self.tbl_tg = QTableWidget()
        self.tbl_tg.setColumnCount(2)
        self.tbl_tg.setHorizontalHeaderLabels(['Property', 'Original'])
        self.tbl_ref = QTableWidget()
        self.tbl_ref.setColumnCount(2)
        self.tbl_ref.setHorizontalHeaderLabels(['Property', 'Original'])

        for tbl in (self.tbl_tg, self.tbl_ref):
            tbl.horizontalHeader().setStretchLastSection(True)
            tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        g1 = QGroupBox(tr('Target data set'))
        v1 = QVBoxLayout(g1)
        v1.addWidget(self.tbl_tg)
        g2 = QGroupBox(tr('Reference data set'))
        v2 = QVBoxLayout(g2)
        v2.addWidget(self.tbl_ref)

        bot.addWidget(g1, 1)
        bot.addWidget(g2, 1)

        root.addLayout(bot, 1)

        if self.datasets:
            # 第 0 项为占位符 <none loaded>，真实数据从第 1 项起
            self.cmb_target.setCurrentIndex(1)
            self.cmb_ref.setCurrentIndex(1)

    def _on_target_changed(self, idx: int):
        ds = self.cmb_target.currentData()
        if not isinstance(ds, Dataset):
            self.target_ds = None
            self.cmb_tg_speed.clear()
            self.cmb_tg_dir.clear()
            self.cmb_tg_col.clear()
            self._fill_table(self.tbl_tg, None)
            return
        self.target_ds = ds
        self.cmb_tg_speed.clear()
        self.cmb_tg_dir.clear()
        self.cmb_tg_col.clear()
        for c in _speed_cols(ds):
            self.cmb_tg_speed.addItem(_col_disp(ds, c), c)
        for c in _dir_cols(ds):
            self.cmb_tg_dir.addItem(_col_disp(ds, c), c)
        for c in _numeric_cols(ds):
            self.cmb_tg_col.addItem(_col_disp(ds, c), c)
        self._fill_table(self.tbl_tg, ds)

    def _on_ref_changed(self, idx: int):
        ds = self.cmb_ref.currentData()
        if not isinstance(ds, Dataset):
            self.ref_ds = None
            self.cmb_ref_speed.clear()
            self.cmb_ref_dir.clear()
            self.cmb_ref_col.clear()
            self._fill_table(self.tbl_ref, None)
            return
        self.ref_ds = ds
        self.cmb_ref_speed.clear()
        self.cmb_ref_dir.clear()
        self.cmb_ref_col.clear()
        for c in _speed_cols(ds):
            self.cmb_ref_speed.addItem(_col_disp(ds, c), c)
        for c in _dir_cols(ds):
            self.cmb_ref_dir.addItem(_col_disp(ds, c), c)
        for c in _numeric_cols(ds):
            self.cmb_ref_col.addItem(_col_disp(ds, c), c)
        self._fill_table(self.tbl_ref, ds)

    def _fill_table(self, tbl: QTableWidget, ds: Dataset | None):
        if ds is None or ds.df is None or len(ds.df) == 0:
            rows = [
                ['Start time', ''], ['End time', ''], ['Duration', ''],
                ['Time step', ''], ['Time steps - speed', '0'],
                ['Time steps - direction', '0'], ['Mean speed', ''],
                ['Mean dir.', ''],
            ]
        else:
            df = ds.df
            idx = df.index
            speed_cols = _speed_cols(ds)
            dir_cols = _dir_cols(ds)
            if speed_cols:
                s = df[speed_cols[0]]
                mean_speed = f'{s.mean():.3f}' if s.notna().any() else ''
                n_speed = int(s.notna().sum())
            else:
                mean_speed, n_speed = '', 0
            if dir_cols:
                d = df[dir_cols[0]]
                mean_dir = f'{d.mean():.1f}' if d.notna().any() else ''
                n_dir = int(d.notna().sum())
            else:
                mean_dir, n_dir = '', 0
            # 估算时间步长（中位间隔）
            if isinstance(idx, pd.DatetimeIndex) and len(idx) > 1:
                step = idx.to_series().diff().dropna().median()
                step_str = f'{step}' if step is not None else ''
                dur = str(idx[-1] - idx[0])
            else:
                step_str, dur = '', ''
            rows = [
                ['Start time', str(idx[0]) if len(idx) else ''],
                ['End time', str(idx[-1]) if len(idx) else ''],
                ['Duration', dur],
                ['Time step', step_str],
                ['Time steps - speed', str(n_speed)],
                ['Time steps - direction', str(n_dir)],
                ['Mean speed', mean_speed],
                ['Mean dir.', mean_dir],
            ]
        tbl.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                tbl.setItem(r, c, QTableWidgetItem(v))

    # ----- 从文件导入数据集（修复“界面无法选择数据”的根因）-----
    def _browse_target(self):
        self._browse(self.cmb_target)

    def _browse_ref(self):
        self._browse(self.cmb_ref)

    def _browse(self, combo: QComboBox):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Import data file', '',
            'Data files (*.csv *.txt *.xlsx *.xls *.asc *.sta *.row *.rwd);;'
            'NRG binary (*.rld *.ndf);;All files (*.*)')
        if not path:
            return
        try:
            parsed = parse_file(path)
        except Exception as e:
            QMessageBox.critical(self, 'Import failed',
                                 tr('解析文件时出错：\n{}', e))
            return
        if parsed.df is None or len(parsed.df) == 0:
            QMessageBox.warning(self, 'Import failed',
                                tr('未能从该文件识别到可用的时序数据。'))
            return
        ds = self._dataset_from_parsed(parsed)
        if ds is None or len(ds.df) == 0:
            QMessageBox.warning(self, 'Import failed', tr('生成的数据集为空。'))
            return
        self.datasets.append(ds)
        combo.addItem(ds.name, ds)
        combo.setCurrentIndex(combo.count() - 1)
        QMessageBox.information(
            self, 'Import succeeded',
            tr('已导入：{}\n{} 行 · {} 通道', ds.name, len(ds.df), len(ds.channels)))

    @staticmethod
    def _dataset_from_parsed(parsed) -> Dataset:
        name = (parsed.station_no
                or os.path.splitext(os.path.basename(parsed.path))[0]
                or 'Imported')
        ds = Dataset(name=name)
        ds.df = parsed.df.copy()
        ds.attrs = {
            'lat': parsed.lat, 'lon': parsed.lon,
            'elevation': parsed.elevation,
            't_start': parsed.t_start, 't_end': parsed.t_end,
            'device_type': parsed.device_type,
        }
        for ch in parsed.channels:
            ds.add_channel(Channel(
                name=ch['name'], kind=ch.get('kind', 'other'),
                height=ch.get('height'), units=ch.get('units', ''),
                role=ch.get('role', '')))
        ds._sync_flags()
        return ds

    # ----- Calculate...：按相关系数估计最优时间偏移 -----
    def _calc_offset(self):
        if not isinstance(self.target_ds, Dataset) or \
                not isinstance(self.ref_ds, Dataset):
            QMessageBox.information(
                self, 'Calculate offset',
                tr('请先选择 Target 与 Reference 数据集。'))
            return
        tgt_sp = _speed_cols(self.target_ds)
        ref_sp = _speed_cols(self.ref_ds)
        if not tgt_sp or not ref_sp:
            QMessageBox.information(
                self, 'Calculate offset',
                tr('Target 与 Reference 均需包含风速通道。'))
            return
        freq = _step_to_freq(self.cmb_timestep.currentText()) or '60min'
        ta = (self.target_ds.df[tgt_sp[0]].resample(freq).mean()
              .interpolate().dropna())
        rb = (self.ref_ds.df[ref_sp[0]].resample(freq).mean()
              .interpolate().dropna())
        joined = pd.concat([ta, rb], axis=1, join='inner').dropna()
        if len(joined) < 10:
            QMessageBox.information(
                self, 'Calculate offset',
                tr('两个数据集在所选时间步下重叠样本不足，无法估算偏移。'))
            return
        x = joined.iloc[:, 0].to_numpy()
        y = joined.iloc[:, 1].to_numpy()
        n = len(x)
        max_shift = min(24, n // 2)
        best_corr, best_k = -2.0, 0
        for k in range(-max_shift, max_shift + 1):
            corr = _capped_corr(x, np.roll(y, k))
            if corr > best_corr:
                best_corr, best_k = corr, k
        hours = best_k * _freq_to_hours(freq)
        self.cmb_offset.setCurrentIndex(self._offset_index_for_hours(hours))
        QMessageBox.information(
            self, 'Calculate offset',
            f'最优时间偏移约 {hours:+.0f} 小时\n'
            f'（该偏移下相关系数 {best_corr:.3f}）')

    def _offset_index_for_hours(self, hours: float) -> int:
        """在下拉项（0h + 1..24 ahead + 1..24 back）中定位最接近项。"""
        best, best_i = 1e9, 0
        for i in range(self.cmb_offset.count()):
            m = re.search(r'(-?\d+)\s*hours', self.cmb_offset.itemText(i))
            val = int(m.group(1)) if m else 0
            d = abs(val - hours)
            if d < best:
                best, best_i = d, i
        return best_i


class _MCPCompareTab(QWidget):
    """Compare Sites Tab：多图对比展示。"""

    DISPLAYS = [
        'Summary graphs', 'Summary tables', 'Time series',
        'Speed scatter plot', 'Direction scatter plot',
        'Speed frequency', 'Direction frequency',
        'Diurnal profile', 'Monthly profile',
        'Vertical profile', 'Speed vs. direction',
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr('Display')))
        self.cmb_display = QComboBox()
        self.cmb_display.addItems(self.DISPLAYS)
        self.cmb_display.setCurrentText('Summary graphs')
        top.addWidget(self.cmb_display)

        self.btn_table = QPushButton(tr('Table'))
        self.btn_graph = QPushButton(tr('Graph'))
        top.addWidget(self.btn_table)
        top.addWidget(self.btn_graph)
        top.addWidget(QLabel(tr('Sectors')))
        self.sp_sectors = QSpinBox()
        self.sp_sectors.setRange(4, 36)
        self.sp_sectors.setValue(16)
        top.addWidget(self.sp_sectors)
        self.chk_overlap = QCheckBox(tr('Overlap period only'))
        top.addWidget(self.chk_overlap)
        top.addStretch(1)
        root.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.plots = []
        for r in range(2):
            for c in range(3):
                p = PlotCanvas()
                p.setMinimumHeight(220)
                self.plots.append(p)
                grid.addWidget(p, r, c)
        root.addLayout(grid, 1)


class _MCPCorrelateSpeedsTab(QWidget):
    """Correlate Speeds Tab：算法选择与回归参数 + 真实计算。"""

    ALGORITHMS = [
        'Linear Least Squares (LLS)',
        'Total Least Squares (TLS)',
        'Variance Ratio (VR)',
        'Matrix Time Series (MTS)',
        'SpeedSort',
        'Vertical Slice',
        'Weibull Fit',
        'Bulk Speed Ratio',
    ]

    # 算法简称 → mcp_algorithms 的 algorithm 参数映射
    _ALG_MAP = {
        'Linear Least Squares (LLS)': 'LLS',
        'Total Least Squares (TLS)': 'TLS',
        'Variance Ratio (VR)': 'VR',
        'Matrix Time Series (MTS)': 'MTS',
        'SpeedSort': 'SpeedSort',
        'Vertical Slice': 'Vertical Slice',
        'Weibull Fit': 'Weibull Fit',
        'Bulk Speed Ratio': 'Bulk Speed Ratio',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_speed: pd.Series | None = None
        self._ref_speed: pd.Series | None = None
        self._results: dict = {}
        self._build()

    def set_concurrent_data(self, tgt: pd.Series, ref: pd.Series):
        """由 MCP 主对话框注入并发目标/参考风速。"""
        self._target_speed = tgt
        self._ref_speed = ref
        self.refresh()

    def _selected_algorithms(self) -> list[str]:
        """用户勾选的算法列表（简称）。"""
        out = []
        for i in range(self.lst_algs.count()):
            item = self.lst_algs.item(i)
            if item.isSelected():
                full = item.text()
                for short, full_name in self._ALG_MAP.items():
                    if full_name in full:
                        out.append(short)
        return out or ['LLS']

    def compute(self):
        """运行选中的算法，更新回归参数表。"""
        from core.mcp_algorithms import run_mcp_algorithm
        if self._target_speed is None or self._ref_speed is None:
            return
        self._results.clear()
        for alg_short in self._selected_algorithms():
            result = run_mcp_algorithm(alg_short,
                                       self._ref_speed,
                                       self._target_speed)
            if result is not None:
                self._results[alg_short] = result
        self._update_results_table()

    def _update_results_table(self):
        """更新回归参数表（每行一个算法）。"""
        algorithms = sorted(self._results.keys())
        self.tbl_reg.setRowCount(len(algorithms))
        for r, alg in enumerate(algorithms):
            res = self._results[alg]
            n = res.get('n', 0)
            slope = res.get('slope', None)
            intercept = res.get('intercept', None)
            r2 = res.get('r2', None)
            self.tbl_reg.setItem(r, 0, QTableWidgetItem(f'{n:,}'))
            self.tbl_reg.setItem(r, 1, QTableWidgetItem(
                f'{intercept:.3f}' if intercept is not None else '—'))
            self.tbl_reg.setItem(r, 2, QTableWidgetItem(
                f'{slope:.3f}' if slope is not None else '—'))
            self.tbl_reg.setItem(r, 3, QTableWidgetItem(
                f'{r2:.3f}' if r2 is not None else '—'))

    def refresh(self):
        self.compute()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        left = QVBoxLayout()

        alg_gb = QGroupBox(tr('Algorithms'))
        alg_v = QVBoxLayout(alg_gb)
        self.lst_algs = QListWidget()
        for a in self.ALGORITHMS:
            self.lst_algs.addItem(a)
        self.lst_algs.setCurrentRow(0)
        alg_v.addWidget(self.lst_algs)
        h = QHBoxLayout()
        self.btn_add = QPushButton(tr('Add...'))
        self.btn_remove = QPushButton(tr('Remove'))
        h.addWidget(self.btn_add)
        h.addWidget(self.btn_remove)
        alg_v.addLayout(h)
        left.addWidget(alg_gb)

        perf_gb = QGroupBox(tr('Algorithm performance'))
        pv = QVBoxLayout(perf_gb)
        self.btn_test_perf = QPushButton(tr('Test Algorithm Performance'))
        self.btn_show_detail = QPushButton(tr('Show Detailed Results...'))
        pv.addWidget(self.btn_test_perf)
        pv.addWidget(self.btn_show_detail)
        self.cmb_test = QComboBox()
        self.cmb_test.addItems([
            'random half of concurrent period',
            'random half of concurrent period, 50x',
            'random half of concurrent period, 100x',
            'random half of concurrent period, 200x',
            'random half of concurrent period, 400x',
            'entire concurrent period',
        ])
        pv.addWidget(QLabel(tr('Test by synthesizing target data in')))
        pv.addWidget(self.cmb_test)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel(tr('Plot error in terms of')))
        self.rb_err_speed = QRadioButton(tr('speed'))
        self.rb_err_power = QRadioButton(tr('power'))
        self.rb_err_speed.setChecked(True)
        h2.addWidget(self.rb_err_speed)
        h2.addWidget(self.rb_err_power)
        pv.addLayout(h2)
        pv.addWidget(QLabel(tr('Convert speed to power using')))
        self.cmb_power = QComboBox()
        self.cmb_power.addItem('(select turbine)')
        pv.addWidget(self.cmb_power)
        left.addWidget(perf_gb)
        left.addStretch(1)
        root.addLayout(left)

        mid = QVBoxLayout()
        set_gb = QGroupBox(tr('Settings'))
        sv = QFormLayout(set_gb)
        self.ed_abbr = QComboBox()
        self.ed_abbr.setEditable(True)
        self.ed_abbr.addItem('LLS')
        sv.addRow('Abbreviation', self.ed_abbr)
        self.sp_dir_sectors = QSpinBox()
        self.sp_dir_sectors.setRange(1, 36)
        self.sp_dir_sectors.setValue(1)
        sv.addRow('Direction sectors', self.sp_dir_sectors)
        self.sp_year_div = QSpinBox()
        self.sp_year_div.setRange(1, 12)
        self.sp_year_div.setValue(1)
        sv.addRow('Yearly divisions', self.sp_year_div)
        self.chk_force_zero = QCheckBox(tr('Force zero intercept'))
        sv.addRow(self.chk_force_zero)
        self.chk_cutoff = QCheckBox(tr('Cutoff wind speed'))
        self.sp_cutoff = QDoubleSpinBox()
        self.sp_cutoff.setRange(0, 50)
        self.sp_cutoff.setValue(4)
        self.sp_cutoff.setSuffix(' m/s')
        h = QHBoxLayout()
        h.addWidget(self.chk_cutoff)
        h.addWidget(self.sp_cutoff)
        sv.addRow(h)
        mid.addWidget(set_gb)

        reg_gb = QGroupBox(tr('Regression parameters'))
        rg = QVBoxLayout(reg_gb)
        self.tbl_reg = QTableWidget()
        self.tbl_reg.setColumnCount(4)
        self.tbl_reg.setHorizontalHeaderLabels(
            ['Time Steps', 'Intercept (m/s)', 'Slope', 'R2'])
        self.tbl_reg.setRowCount(1)
        self.tbl_reg.setItem(0, 0, QTableWidgetItem('2,533'))
        self.tbl_reg.setItem(0, 1, QTableWidgetItem('2.116'))
        self.tbl_reg.setItem(0, 2, QTableWidgetItem('1.021'))
        self.tbl_reg.setItem(0, 3, QTableWidgetItem('0.407'))
        rg.addWidget(self.tbl_reg)
        mid.addWidget(reg_gb)
        mid.addStretch(1)
        root.addLayout(mid)

        right = QVBoxLayout()
        top_r = QHBoxLayout()
        top_r.addWidget(QLabel(tr('Curve fit by sector')))
        top_r.addWidget(QLabel(tr('Direction sector')))
        self.cmb_sector = QComboBox()
        self.cmb_sector.addItem('0\u00b0 - 360\u00b0')
        top_r.addWidget(self.cmb_sector)
        top_r.addWidget(QLabel(tr('Yearly division')))
        self.cmb_year = QComboBox()
        self.cmb_year.addItem(tr('Jan - Dec'))
        top_r.addWidget(self.cmb_year)
        top_r.addStretch(1)
        right.addLayout(top_r)

        self.plot_fit = PlotCanvas('Curve fit by sector')
        self.plot_fit.setMinimumHeight(400)
        right.addWidget(self.plot_fit, 1)
        root.addLayout(right, 1)

        self.btn_test_perf.clicked.connect(self.compute)
        self.btn_show_detail.clicked.connect(self.compute)


class _MCPCorrelateDirectionsTab(QWidget):
    """Correlate Directions Tab：风向相关性。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        left = QVBoxLayout()
        h = QHBoxLayout()
        h.addWidget(QLabel(tr('Direction sectors')))
        self.sp_sectors = QSpinBox()
        self.sp_sectors.setRange(1, 36)
        self.sp_sectors.setValue(1)
        h.addWidget(self.sp_sectors)
        left.addLayout(h)

        self.chk_cutoff = QCheckBox(tr('Cutoff wind speed'))
        self.sp_cutoff = QDoubleSpinBox()
        self.sp_cutoff.setRange(0, 50)
        self.sp_cutoff.setValue(4)
        self.sp_cutoff.setSuffix(' m/s')
        h2 = QHBoxLayout()
        h2.addWidget(self.chk_cutoff)
        h2.addWidget(self.sp_cutoff)
        left.addLayout(h2)

        self.lbl_r2 = QLabel(tr('Overall R2: 0.751'))
        left.addWidget(self.lbl_r2)

        self.tbl_sectors = QTableWidget()
        self.tbl_sectors.setColumnCount(4)
        self.tbl_sectors.setHorizontalHeaderLabels(
            ['Sector', 'Data Points', 'Mean Veer (?)', 'Mean Direction (?)'])
        self.tbl_sectors.setRowCount(2)
        self.tbl_sectors.setItem(0, 0, QTableWidgetItem('0? - 360?'))
        self.tbl_sectors.setItem(0, 1, QTableWidgetItem('2,533'))
        self.tbl_sectors.setItem(0, 2, QTableWidgetItem('16.719'))
        self.tbl_sectors.setItem(0, 3, QTableWidgetItem('16.719'))
        self.tbl_sectors.setItem(1, 0, QTableWidgetItem('All'))
        self.tbl_sectors.setItem(1, 1, QTableWidgetItem('2,533'))
        left.addWidget(self.tbl_sectors)
        left.addStretch(1)
        root.addLayout(left)

        right = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(QLabel(tr('Plot type')))
        self.cmb_plot = QComboBox()
        self.cmb_plot.addItems(['Direction vs. Direction', 'Veer vs. Direction'])
        top.addWidget(self.cmb_plot)
        top.addStretch(1)
        right.addLayout(top)

        self.plot_dir = PlotCanvas('Target vs. Reference Direction')
        self.plot_dir.setMinimumHeight(500)
        right.addWidget(self.plot_dir, 1)
        root.addLayout(right, 1)


class _MCPSynthesizeTab(QWidget):
    """Synthesize Data Tab：生成最终数据集。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr('Synthesize speeds using')))
        self.cmb_alg = QComboBox()
        self.cmb_alg.addItems([
            'Linear Least Squares (LLS)',
            'Total Least Squares (TLS)',
            'Variance Ratio (VR)',
            'Matrix Time Series (MTS)',
        ])
        top.addWidget(self.cmb_alg)

        top.addWidget(QLabel(tr('Create final data set starting')))
        self.dt_start = QDateTimeEdit(datetime(1990, 1, 1, 8, 0))
        top.addWidget(self.dt_start)
        top.addWidget(QLabel(tr('ending')))
        self.dt_end = QDateTimeEdit(datetime(2026, 6, 3, 8, 0))
        top.addWidget(self.dt_end)

        self.chk_overwrite = QCheckBox(tr('Overwrite measured target data with synthetic data'))
        top.addWidget(self.chk_overwrite)
        self.btn_create = QPushButton(tr('Create Final Data Set'))
        top.addWidget(self.btn_create)
        top.addStretch(1)
        root.addLayout(top)

        info = QHBoxLayout()
        info.addWidget(QLabel(tr('Direction sectors: 1')))
        info.addWidget(QLabel(tr('Yearly divisions: 1')))
        info.addWidget(QLabel(tr('Force zero intercept: No')))
        info.addStretch(1)
        root.addLayout(info)

        mid = QHBoxLayout()
        mid.addWidget(QLabel(tr('Display')))
        self.cmb_display = QComboBox()
        self.cmb_display.addItems(['summary', 'diurnal', 'monthly', 'frequency'])
        mid.addWidget(self.cmb_display)
        mid.addStretch(1)
        root.addLayout(mid)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.plots = []
        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for r, c in positions:
            p = PlotCanvas()
            p.setMinimumHeight(220)
            self.plots.append(p)
            grid.addWidget(p, r, c)
        root.addLayout(grid, 1)

        self.tbl_props = QTableWidget()
        self.tbl_props.setColumnCount(4)
        self.tbl_props.setHorizontalHeaderLabels(
            ['Property', 'Target Original', 'Target Processed', 'Final'])
        root.addWidget(self.tbl_props)


class MeasureCorrelatePredictDialog(QDialog):
    """MCP 主对话框：5 个 Tab。"""

    def __init__(self, datasets: list[Dataset], parent=None):
        super().__init__(parent)
        self.datasets = datasets or []
        self.setWindowTitle(tr('Measure Correlate Predict'))
        self.setMinimumSize(1300, 820)
        self.resize(1400, 900)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.tab_import = _MCPImportTab(self.datasets)
        self.tab_compare = _MCPCompareTab()
        self.tab_speeds = _MCPCorrelateSpeedsTab()
        self.tab_dirs = _MCPCorrelateDirectionsTab()
        self.tab_synth = _MCPSynthesizeTab()

        self.tabs.addTab(self.tab_import, tr('Import Data'))
        self.tabs.addTab(self.tab_compare, tr('Compare Sites'))
        self.tabs.addTab(self.tab_speeds, tr('Correlate Speeds'))
        self.tabs.addTab(self.tab_dirs, tr('Correlate Directions'))
        self.tabs.addTab(self.tab_synth, tr('Synthesize Data'))

        # 底部按钮
        btns = QHBoxLayout()
        self.btn_help = QPushButton(tr('Help'))
        self.btn_scale = QPushButton(tr('Scale Target Data Set...'))
        self.btn_export = QPushButton(tr('Export Final Data Set...'))
        self.btn_close = QPushButton(tr('Close'))
        self.btn_close.clicked.connect(self.reject)
        btns.addWidget(self.btn_help)
        btns.addStretch(1)
        btns.addWidget(self.btn_scale)
        btns.addWidget(self.btn_export)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)
