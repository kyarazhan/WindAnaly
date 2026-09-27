"""Analyze 菜单 16 个核心分析对话框（WindAnaly）。

按 Windographer 风格实现：左侧为控制/筛选面板，右侧为图表与结果表格。
计算层尽量复用 core/ 中已有的风资源方法，不在对话框内堆复杂算法。
"""
from __future__ import annotations

import math
import re
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDoubleSpinBox,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QRadioButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from core.dataset import KIND_DIR, KIND_SPEED, Dataset
from core import settings
from core.iec import (
    classify_ti, iec_categories, iec_edition_short, iec_ti_label,
    ti_value_for_classification,
)
from ui.modules.analysis_tabs import display_name
from ui.modules.plot import PlotCanvas
from core.i18n import tr


# ------------------------------------------------------------------ 工具函数
_NUMERIC_KINDS = {'speed', 'dir', 'temp', 'pres', 'rh', 'ti', 'synthetic'}


def _numeric_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind in _NUMERIC_KINDS]


def _speed_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind == KIND_SPEED]


def _dir_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind == KIND_DIR]


def _temp_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind == 'temp']


def _to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors='coerce')


def _height_of(name: str) -> float | None:
    """启发式从通道名中提取高度(m)。"""
    m = re.search(r'(\d+(?:\.\d+)?)\s*m', name, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r'(?<!\d)(\d{2,3})(?=[mM]|\b)', name)
    if m:
        v = float(m.group(1))
        if 5 <= v <= 500:
            return v
    return None


def _power_law_fit(heights: np.ndarray, values: np.ndarray):
    """幂律拟合 v = v_ref * (z/z_ref)^alpha；返回 (alpha, fit_values)。"""
    h = np.asarray(heights, dtype=float)
    v = np.asarray(values, dtype=float)
    valid = (h > 0) & (v > 0) & np.isfinite(h) & np.isfinite(v)
    h, v = h[valid], v[valid]
    if len(h) < 2:
        return None, None
    log_h, log_v = np.log(h), np.log(v)
    A = np.vstack([log_h, np.ones_like(log_h)]).T
    alpha, intercept = np.linalg.lstsq(A, log_v, rcond=None)[0]
    fit = np.exp(intercept) * h ** alpha
    return alpha, fit


def _log_law_fit(heights: np.ndarray, values: np.ndarray, z0: float = 0.03):
    """对数律拟合 u = (u_star/kappa)*ln(z/z0)；返回 (u_star, fit_values)。"""
    kappa = 0.4
    h = np.asarray(heights, dtype=float)
    v = np.asarray(values, dtype=float)
    valid = (h > z0) & np.isfinite(h) & np.isfinite(v)
    h, v = h[valid], v[valid]
    if len(h) < 2:
        return None, None
    y = np.log((h - z0) / z0)
    A = np.vstack([y, np.ones_like(y)]).T
    slope, intercept = np.linalg.lstsq(A, v, rcond=None)[0]
    fit = slope * y + intercept
    return slope * kappa, fit


def _weibull_mle(x: np.ndarray):
    """无 scipy 时的简化 Weibull 矩估计：返回 (k, c)。"""
    x = np.asarray(x, dtype=float)
    x = x[(x > 0) & np.isfinite(x)]
    if len(x) < 5:
        return None, None
    mean = x.mean()
    std = x.std(ddof=1)
    if std <= 0:
        return None, None
    # 经验近似：k = (mean/std)^(-1.086)
    k = (mean / std) ** (-1.086)
    if k <= 0:
        return None, None
    c = mean / math.gamma(1.0 + 1.0 / k)
    return k, c


def _weibull_pdf(x: np.ndarray, k: float, c: float) -> np.ndarray:
    return (k / c) * (x / c) ** (k - 1) * np.exp(-((x / c) ** k))


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


class _FilterSection(QGroupBox):
    """通用 Filter by 区域：Flag / Date / Date range / Direction / Data column min/max。"""

    def __init__(self, parent=None, with_date: bool = True,
                 with_direction: bool = True, with_data_col: bool = True):
        super().__init__('Filter by', parent)
        self.lay = QGridLayout(self)
        self.lay.setColumnStretch(1, 1)
        self.lay.setColumnStretch(3, 1)
        row = 0

        self.chk_flag = QCheckBox(tr('Flag'))
        self.cmb_flag = QComboBox()
        self.cmb_flag.addItems(['<Unflagged data>', 'Synthesized'])
        self.lay.addWidget(self.chk_flag, row, 0)
        self.lay.addWidget(self.cmb_flag, row, 1, 1, 3)
        row += 1

        if with_date:
            self.chk_date = QCheckBox(tr('Date'))
            self.cmb_year = QComboBox(); self.cmb_year.addItem('<All>')
            self.cmb_month = QComboBox(); self.cmb_month.addItem('<All>')
            self.lay.addWidget(self.chk_date, row, 0)
            self.lay.addWidget(QLabel(tr('Year')), row, 1)
            self.lay.addWidget(self.cmb_year, row, 2)
            self.lay.addWidget(QLabel(tr('Month')), row, 3)
            self.lay.addWidget(self.cmb_month, row, 4)
            row += 1

            self.chk_range = QCheckBox(tr('Date range'))
            self.dt_from = QDateTimeEdit(datetime.now())
            self.dt_to = QDateTimeEdit(datetime.now())
            self.dt_from.setCalendarPopup(True)
            self.dt_to.setCalendarPopup(True)
            self.lay.addWidget(self.chk_range, row, 0)
            self.lay.addWidget(self.dt_from, row, 1, 1, 2)
            self.lay.addWidget(self.dt_to, row, 3, 1, 2)
            row += 1
        else:
            self.chk_date = self.chk_range = None

        if with_direction:
            self.chk_sector = QCheckBox(tr('Direction sector'))
            self.cmb_sector = QComboBox(); self.cmb_sector.addItem(tr('All'))
            self.sp_sectors = QSpinBox(); self.sp_sectors.setRange(4, 36); self.sp_sectors.setValue(16)
            self.cmb_dir_sensor = QComboBox()
            self.lay.addWidget(self.chk_sector, row, 0)
            self.lay.addWidget(self.cmb_sector, row, 1)
            self.lay.addWidget(QLabel(tr('Sectors')), row, 2)
            self.lay.addWidget(self.sp_sectors, row, 3)
            self.lay.addWidget(self.cmb_dir_sensor, row, 4)
            row += 1
        else:
            self.chk_sector = None

        if with_data_col:
            self.chk_col = QCheckBox(tr('Data column'))
            self.cmb_data_col = QComboBox()
            self.sp_min = QDoubleSpinBox(); self.sp_min.setRange(-9999, 9999); self.sp_min.setValue(0)
            self.sp_max = QDoubleSpinBox(); self.sp_max.setRange(-9999, 9999); self.sp_max.setValue(50)
            self.lay.addWidget(self.chk_col, row, 0)
            self.lay.addWidget(self.cmb_data_col, row, 1)
            self.lay.addWidget(QLabel(tr('Min')), row, 2)
            self.lay.addWidget(self.sp_min, row, 3)
            self.lay.addWidget(QLabel(tr('Max')), row, 4)
            self.lay.addWidget(self.sp_max, row, 5)

    def populate_sensors(self, ds: Dataset):
        if hasattr(self, 'cmb_dir_sensor'):
            self.cmb_dir_sensor.clear()
            for n in _dir_cols(ds):
                self.cmb_dir_sensor.addItem(display_name(n), n)
        if hasattr(self, 'cmb_data_col'):
            self.cmb_data_col.clear()
            for n in _numeric_cols(ds):
                self.cmb_data_col.addItem(display_name(n), n)


# ------------------------------------------------------------------ 基类
class _AnalysisDialogBase(QDialog):
    """Analyze 对话框通用骨架：左控制 / 右结果，底部 Help/Close。"""

    TITLE = 'Analysis'
    MIN_W = 960
    MIN_H = 680

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.setWindowTitle(self.TITLE)
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self.resize(1100, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # 左侧面板
        self.left = QWidget()
        self.left_lay = QVBoxLayout(self.left)
        self.left_lay.setContentsMargins(0, 0, 0, 0)
        self.left_lay.setSpacing(8)
        splitter.addWidget(self.left)

        # 右侧面板
        self.right = QWidget()
        self.right_lay = QVBoxLayout(self.right)
        self.right_lay.setContentsMargins(0, 0, 0, 0)
        self.right_lay.setSpacing(8)
        splitter.addWidget(self.right)

        splitter.setSizes([340, 760])

        # 底部按钮
        btns = QHBoxLayout()
        self.btn_help = QPushButton(tr('Help'))
        self.btn_close = QPushButton(tr('Close'))
        self.btn_close.clicked.connect(self.reject)
        btns.addWidget(self.btn_help)
        btns.addStretch(1)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        self._build_controls()
        self._build_right()
        self.refresh()

    def _build_controls(self):
        """子类覆写：在 self.left_lay 中添加控制项。"""
        pass

    def _build_right(self):
        """子类覆写：在 self.right_lay 中添加图表/表格。"""
        pass

    def refresh(self):
        """子类覆写：根据控件状态刷新结果。"""
        pass

    def _mask(self) -> pd.Series | None:
        """基于 Flag 勾选返回基础掩码（未实现复杂筛选，仅保留未标记）。"""
        if self.ds is None or self.ds.df.empty:
            return None
        return ~self.ds.flagged_mask()

    def _series(self, col: str) -> pd.Series:
        return _to_num(self.ds.df[col])

    def _add_filter(self, with_date: bool = True, with_direction: bool = True,
                    with_data_col: bool = True) -> _FilterSection:
        sec = _FilterSection(self.left, with_date, with_direction, with_data_col)
        sec.populate_sensors(self.ds)
        self.left_lay.addWidget(sec)
        return sec


# ------------------------------------------------------------------ 1. Data Recovery Analysis
class DataRecoveryDialog(_AnalysisDialogBase):
    TITLE = '% Data Recovery Analysis'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_display = QComboBox()
        self.cmb_display.addItems(['height'])
        form.addRow('Display versus', self.cmb_display)

        self.cmb_bin_col = QComboBox()
        form.addRow('Bin data column', self.cmb_bin_col)

        self.cmb_dir_sensor = QComboBox()
        form.addRow('Direction sensor', self.cmb_dir_sensor)

        self.sp_sectors = QSpinBox(); self.sp_sectors.setRange(4, 36); self.sp_sectors.setValue(16)
        form.addRow('Direction sectors', self.sp_sectors)

        self.chk_unflagged = QCheckBox(tr('<Unflagged data>')); self.chk_unflagged.setChecked(True)
        self.chk_synth = QCheckBox(tr('Synthesized')); self.chk_synth.setChecked(True)
        form.addRow('Valid if flagged as:', self.chk_unflagged)
        form.addRow('', self.chk_synth)

        self.left_lay.addLayout(form)

        self.col_list = _CheckList('Data columns to consider')
        self.left_lay.addWidget(self.col_list, 1)

        self.filter = self._add_filter()

        # 填充数据列
        for n in _numeric_cols(self.ds):
            self.cmb_bin_col.addItem(display_name(n), n)
        self.col_list.set_items([display_name(c) for c in _numeric_cols(self.ds)])
        for n in _dir_cols(self.ds):
            self.cmb_dir_sensor.addItem(display_name(n), n)

    def _build_right(self):
        self.canvas = PlotCanvas('Data Recovery By Height')
        self.right_lay.addWidget(self.canvas, 1)

    def refresh(self):
        cols = self.col_list.checked_data()
        if not cols or self.ds is None or self.ds.df.empty:
            self.canvas.clear(tr('请选择数据列'))
            return
        heights, rates = [], []
        for disp in cols:
            col = disp  # display_name is not reversible simply here; use heuristic
            for c in self.ds.channels:
                if display_name(c) == disp:
                    col = c
                    break
            h = _height_of(col)
            if h is None:
                continue
            s = self._series(col)
            rate = s.notna().mean() * 100
            heights.append(h)
            rates.append(rate)
        if not heights:
            self.canvas.clear(tr('无法从列名识别高度'))
            return
        order = np.argsort(heights)
        x = np.array(heights)[order]
        y = np.array(rates)[order]
        self.canvas.plot_line(x, y, xlabel='Height Above Ground (m)',
                              ylabel='Data Recovery Rate (%)', ymin=0)


# ------------------------------------------------------------------ 2. Turbulence Analysis
class TurbulenceDialog(_AnalysisDialogBase):
    TITLE = 'Turbulence Analysis'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_display = QComboBox()
        self.cmb_display.addItems(['height'])
        form.addRow('Display turbulence vs', self.cmb_display)

        self.cmb_speed = QComboBox()
        form.addRow('Wind speed sensor', self.cmb_speed)

        self.cmb_dir = QComboBox()
        form.addRow('Direction sensor', self.cmb_dir)

        self.sp_sectors = QSpinBox(); self.sp_sectors.setRange(4, 36); self.sp_sectors.setValue(16)
        form.addRow('Direction sectors', self.sp_sectors)

        self.chk_categories = QCheckBox(tr('Show turbulence categories in graph'))
        form.addRow(self.chk_categories)

        self.left_lay.addLayout(form)
        self.filter = self._add_filter()

        for n in _speed_cols(self.ds):
            self.cmb_speed.addItem(display_name(n), n)
        for n in _dir_cols(self.ds):
            self.cmb_dir.addItem(display_name(n), n)

        # 读取首选 IEC 版本，决定 TI 类型与类别表
        self.iec = settings.get('preferred_iec', '3rd')
        self.iec_short = iec_edition_short(self.iec)
        self.iec_ti_type_label = iec_ti_label(self.iec)
        cats = '/'.join(lbl for lbl, _ in iec_categories(self.iec))

        # 结果表格
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            'Height (m)', 'Data Points', 'Mean TI',
            'Standard\nDeviation of TI',
            f'{self.iec_ti_type_label}\n({self.iec_short} ed.)',
            'Peak\nTI', '15 m/s Speed Bin\nMean TI',
            f'IEC {self.iec_short} ed.\nTurbulence Category\n({cats})'])
        self.table.horizontalHeader().setStretchLastSection(True)

    def _build_right(self):
        self.canvas = PlotCanvas('Mean Turbulence Intensity vs Height')
        self.right_lay.addWidget(self.canvas, 2)
        self.right_lay.addWidget(self.table, 1)

    def refresh(self):
        if self.ds is None or self.ds.df.empty:
            self.canvas.clear(tr('未载入数据集'))
            return
        speeds = _speed_cols(self.ds)
        if not speeds:
            self.canvas.clear(tr('无风速通道'))
            return
        rows = []
        heights, tis = [], []
        for col in speeds:
            s = self._series(col)
            std_col = col.replace('_Avg', '_Std')
            if std_col in self.ds.df.columns:
                std = self._series(std_col)
            else:
                std = s * 0.15  # fallback
            ti = (std / s).replace([np.inf, -np.inf], np.nan)
            h = _height_of(col)
            if h is None:
                continue
            heights.append(h)
            mean_ti = ti.mean()
            tis.append(mean_ti)

            # 15 m/s 区间（14–16 m/s）的 TI，用于 IEC 类别判定
            bin_mask = s.between(14, 16)
            bin_ti = ti[bin_mask]
            if bin_ti.notna().any():
                ti_class_val = ti_value_for_classification(self.iec, bin_ti.values)
                bin15_mean = float(bin_ti.mean())
            else:
                # 该高度无 15 m/s 数据：退化为全样本 TI，并在单元格标注
                ti_class_val = ti_value_for_classification(self.iec, ti.values)
                bin15_mean = float('nan')
            category = classify_ti(self.iec, ti_class_val)

            rows.append([
                h, int(s.notna().sum()), mean_ti, ti.std(ddof=1),
                ti_class_val, ti.max(), bin15_mean, category
            ])
        if not heights:
            self.canvas.clear(tr('无法识别高度'))
            return
        order = np.argsort(heights)
        x = np.array(heights)[order]
        y = np.array(tis)[order]
        self.canvas.plot_line(x, y, xlabel='Height Above Ground (m)',
                              ylabel='Mean Turbulence Intensity', ymin=0)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                if isinstance(v, float):
                    txt = f'{v:.3f}' if np.isfinite(v) else '—'
                else:
                    txt = str(v)
                self.table.setItem(r, c, QTableWidgetItem(txt))


# ------------------------------------------------------------------ 3. Wind Shear Analysis
class WindShearDialog(_AnalysisDialogBase):
    TITLE = 'Wind Shear Analysis'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_display = QComboBox()
        self.cmb_display.addItems(['mean speed shear'])
        form.addRow('Display', self.cmb_display)

        self.cmb_versus = QComboBox()
        self.cmb_versus.addItems(['height'])
        form.addRow('versus', self.cmb_versus)

        self.left_lay.addLayout(form)

        grp = QGroupBox(tr('Shear profile'))
        g_lay = QHBoxLayout(grp)
        self.rb_log = QRadioButton(tr('log law'))
        self.rb_power = QRadioButton(tr('power law'))
        self.rb_power.setChecked(True)
        g_lay.addWidget(self.rb_log)
        g_lay.addWidget(self.rb_power)
        self.left_lay.addWidget(grp)

        self.chk_complete = QCheckBox(tr('Use only time steps containing data for all selected sensors'))
        self.left_lay.addWidget(self.chk_complete)

        self.col_list = _CheckList('Wind speed sensors to use in calculations')
        self.left_lay.addWidget(self.col_list, 1)
        self.col_list.set_items([display_name(c) for c in _speed_cols(self.ds)])

        self.filter = self._add_filter()

    def _build_right(self):
        self.canvas = PlotCanvas('Vertical Wind Shear Profile')
        self.right_lay.addWidget(self.canvas, 1)

    def refresh(self):
        cols = self.col_list.checked_data()
        if not cols or self.ds is None:
            self.canvas.clear(tr('请选择风速传感器'))
            return
        heights, means = [], []
        for disp in cols:
            col = disp
            for c in self.ds.channels:
                if display_name(c) == disp:
                    col = c
                    break
            h = _height_of(col)
            if h is None:
                continue
            s = self._series(col)
            heights.append(h)
            means.append(s.mean())
        if len(heights) < 2:
            self.canvas.clear(tr('至少需要两层风速'))
            return
        order = np.argsort(heights)
        h = np.array(heights)[order]
        v = np.array(means)[order]
        series = [('Measured data', h, v)]
        if self.rb_power.isChecked():
            alpha, fit = _power_law_fit(h, v)
            if fit is not None:
                series.append((f'Power law fit (alpha = {alpha:.3f})', h, fit))
        else:
            u_star, fit = _log_law_fit(h, v)
            if fit is not None:
                series.append((f'Log law fit (z0 = {u_star:.3f} m)', h, fit))
        self.canvas.plot_lines(series, xlabel='Mean Wind Speed (m/s)',
                               ylabel='Height Above Ground (m)', ymin=0)


# ------------------------------------------------------------------ 4. Wind Speed Distribution Analysis
class WindSpeedDistributionDialog(_AnalysisDialogBase):
    TITLE = 'Wind Speed Distribution Analysis'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_speed = QComboBox()
        form.addRow('Wind speed sensor', self.cmb_speed)
        self.left_lay.addLayout(form)

        grp = QGroupBox(tr('Bin settings'))
        g_lay = QFormLayout(grp)
        self.sp_width = QDoubleSpinBox(); self.sp_width.setRange(0.1, 5); self.sp_width.setValue(0.5); self.sp_width.setDecimals(2)
        g_lay.addRow('Width (m/s)', self.sp_width)
        self.sp_start = QDoubleSpinBox(); self.sp_start.setRange(0, 50); self.sp_start.setValue(0)
        g_lay.addRow('Start at (m/s)', self.sp_start)
        self.chk_half = QCheckBox(tr('Make first bin half this width'))
        g_lay.addRow(self.chk_half)
        self.left_lay.addWidget(grp)

        self.filter = self._add_filter(with_direction=False, with_data_col=False)

        for n in _speed_cols(self.ds):
            self.cmb_speed.addItem(display_name(n), n)

    def _build_right(self):
        self.canvas = PlotCanvas('Wind Speed Frequency Distribution')
        self.right_lay.addWidget(self.canvas, 2)
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ['', 'Weibull k', 'Weibull c\n(m/s)', 'Mean\n(m/s)',
             'Proportion\nAbove', 'Power\nDensity\n(W/m2)', 'R\nSquared'])
        self.right_lay.addWidget(self.table, 1)

    def refresh(self):
        col = self.cmb_speed.currentData()
        if col is None or self.ds is None:
            self.canvas.clear(tr('请选择风速传感器'))
            return
        s = self._series(col).dropna()
        if len(s) == 0:
            self.canvas.clear(tr('无有效数据'))
            return
        width = self.sp_width.value()
        start = self.sp_start.value()
        if self.chk_half.isChecked():
            edges = [start, start + width / 2]
            edges += [start + width / 2 + i * width for i in range(1, 50)]
        else:
            edges = [start + i * width for i in range(50)]
        edges = [e for e in edges if e <= s.max() + width]
        counts, edges = np.histogram(s, bins=edges)
        freq = counts / counts.sum() * 100
        x = edges[:-1] + np.diff(edges) / 2

        series = [('Actual data', x, freq)]
        rows = [['Actual data', len(s), '', s.mean(), (s > s.mean()).mean(),
                 0.5 * 1.225 * (s ** 3).mean(), '']]
        for label, k, c in [('Maximum likelihood', *_weibull_mle(s.values)),
                            ('Least squares', *_weibull_mle(s.values)),
                            ('WAsP', *_weibull_mle(s.values))]:
            if k is None:
                rows.append([label, '', '', '', '', '', ''])
                continue
            pdf = _weibull_pdf(x, k, c) * width * 100
            series.append((label, x, pdf))
            mean = c * math.gamma(1 + 1 / k)
            rows.append([label, f'{k:.3f}', f'{c:.3f}', f'{mean:.3f}',
                         '', f'{0.5 * 1.225 * c ** 3 * math.gamma(1 + 3 / k):.1f}', ''])

        self.canvas.plot_lines(series, xlabel='Wind Speed (m/s)',
                               ylabel='Frequency (%)', ymin=0)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))


# ------------------------------------------------------------------ 5. Wind Speed Ratios
class WindSpeedRatiosDialog(_AnalysisDialogBase):
    TITLE = 'Wind Speed Ratios'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_num = QComboBox()
        self.cmb_den = QComboBox()
        form.addRow('Show ratio of', self.cmb_num)
        form.addRow('to', self.cmb_den)

        self.cmb_interval = QComboBox()
        self.cmb_interval.addItems(['Monthly', 'Daily', 'Annual', 'Raw'])
        form.addRow('Averaging interval', self.cmb_interval)
        self.left_lay.addLayout(form)

        self.filter = self._add_filter()

        for n in _speed_cols(self.ds):
            self.cmb_num.addItem(display_name(n), n)
            self.cmb_den.addItem(display_name(n), n)

    def _build_right(self):
        self.canvas = PlotCanvas('Speed Ratio')
        self.right_lay.addWidget(self.canvas, 1)

    def refresh(self):
        num = self.cmb_num.currentData()
        den = self.cmb_den.currentData()
        if not num or not den or self.ds is None:
            self.canvas.clear(tr('请选择分子/分母风速'))
            return
        s1 = self._series(num)
        s2 = self._series(den)
        ratio = (s1 / s2).replace([np.inf, -np.inf], np.nan)
        interval = self.cmb_interval.currentText()
        if interval == 'Monthly':
            r = ratio.resample('MS').mean()
        elif interval == 'Daily':
            r = ratio.resample('D').mean()
        elif interval == 'Annual':
            r = ratio.resample('YS').mean()
        else:
            r = ratio
        r = r.dropna()
        if len(r) == 0:
            self.canvas.clear(tr('无有效比值'))
            return
        x = r.index
        y = r.values
        title = f'Ratio of {display_name(num)} to {display_name(den)}'
        self.canvas.set_title(title)
        self.canvas.plot_line(x, y, xlabel='Time', ylabel='Ratio')


# ------------------------------------------------------------------ 6. Tower Distortion Analysis
class TowerDistortionDialog(_AnalysisDialogBase):
    TITLE = 'Tower Distortion Analysis'

    def _build_controls(self):
        form = QFormLayout()
        self.sp_vert = QSpinBox(); self.sp_vert.setRange(1, 100); self.sp_vert.setValue(1)
        form.addRow('Analyze sensors within', self.sp_vert)
        self.sp_vert.setSuffix(' vertical metres of each other')

        self.cmb_pair = QComboBox(); self.cmb_pair.addItem(tr('All'))
        form.addRow('Sensor pair:', self.cmb_pair)

        self.cmb_dir = QComboBox()
        form.addRow('Direction sensor', self.cmb_dir)
        self.left_lay.addLayout(form)

        grp = QGroupBox(tr('Show'))
        g_lay = QVBoxLayout(grp)
        self.rb_ratio = QRadioButton(tr('ratio of wind speeds')); self.rb_ratio.setChecked(True)
        self.rb_diff = QRadioButton(tr('difference between wind speeds'))
        g_lay.addWidget(self.rb_ratio); g_lay.addWidget(self.rb_diff)
        self.left_lay.addWidget(grp)

        self.filter = self._add_filter()

        speeds = _speed_cols(self.ds)
        for i, a in enumerate(speeds):
            for b in speeds[i + 1:]:
                h_a, h_b = _height_of(a), _height_of(b)
                if h_a is not None and h_b is not None and abs(h_a - h_b) <= self.sp_vert.value():
                    self.cmb_pair.addItem(f'{display_name(a)} / {display_name(b)}', (a, b))
        for n in _dir_cols(self.ds):
            self.cmb_dir.addItem(display_name(n), n)

    def _build_right(self):
        self.canvas = PlotCanvas('Median Ratio of Wind Speed Sensors')
        self.right_lay.addWidget(self.canvas, 2)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ['Wind Speed Sensor Ratio', 'Total\nOccurrences', 'Tower\nDistortion\nFactor', 'Scatter\nFactor'])
        self.right_lay.addWidget(self.table, 1)

    def refresh(self):
        pair = self.cmb_pair.currentData()
        dir_col = self.cmb_dir.currentData()
        if pair is None or dir_col is None or self.ds is None:
            self.canvas.clear(tr('请选择传感器对与风向'))
            return
        a, b = pair
        s1 = self._series(a)
        s2 = self._series(b)
        d = self._series(dir_col)
        if self.rb_ratio.isChecked():
            val = (s1 / s2).replace([np.inf, -np.inf], np.nan)
        else:
            val = s1 - s2
        valid = val.notna() & d.notna()
        val, d = val[valid], d[valid]
        if len(val) == 0:
            self.canvas.clear(tr('无有效数据'))
            return
        sectors = 36
        bins = np.linspace(0, 360, sectors + 1)
        mids = (bins[:-1] + bins[1:]) / 2
        medians = []
        for lo, hi in zip(bins[:-1], bins[1:]):
            mask = (d >= lo) & (d < hi)
            medians.append(val[mask].median() if mask.any() else np.nan)
        medians = np.array(medians)
        self.canvas.plot_line(mids, medians, xlabel='Sector Midpoint (deg)',
                              ylabel='Median Ratio of Wind Speed Sensors')
        self.table.setRowCount(1)
        self.table.setItem(0, 0, QTableWidgetItem(f'{display_name(a)} / {display_name(b)}'))
        self.table.setItem(0, 1, QTableWidgetItem(str(int(valid.sum()))))
        self.table.setItem(0, 2, QTableWidgetItem(f'{np.nanmedian(np.abs(medians - 1)):.3f}'))
        self.table.setItem(0, 3, QTableWidgetItem(f'{np.nanstd(medians):.3f}'))


# ------------------------------------------------------------------ 7. Temperature Profile Analysis
class TemperatureProfileDialog(_AnalysisDialogBase):
    TITLE = 'Temperature Profile Analysis'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_display = QComboBox(); self.cmb_display.addItems(['mean temperature gradient'])
        self.cmb_versus = QComboBox(); self.cmb_versus.addItems(['height'])
        form.addRow('Display', self.cmb_display)
        form.addRow('versus', self.cmb_versus)
        self.left_lay.addLayout(form)

        self.chk_complete = QCheckBox(tr('Use only time steps containing data for all selected sensors'))
        self.left_lay.addWidget(self.chk_complete)

        self.col_list = _CheckList('Temperature sensors to use in calculations')
        self.col_list.set_items([display_name(c) for c in _temp_cols(self.ds)])
        self.left_lay.addWidget(self.col_list, 1)

        self.filter = self._add_filter()

    def _build_right(self):
        self.canvas = PlotCanvas('Vertical Temperature Profile')
        self.right_lay.addWidget(self.canvas, 1)

    def refresh(self):
        cols = self.col_list.checked_data()
        if not cols or self.ds is None:
            self.canvas.clear(tr('请选择温度传感器'))
            return
        heights, temps = [], []
        for disp in cols:
            col = disp
            for c in self.ds.channels:
                if display_name(c) == disp:
                    col = c
                    break
            h = _height_of(col)
            if h is None:
                continue
            s = self._series(col)
            heights.append(h)
            temps.append(s.mean())
        if len(heights) < 2:
            self.canvas.clear(tr('至少需要两层温度'))
            return
        order = np.argsort(heights)
        h = np.array(heights)[order]
        t = np.array(temps)[order]
        series = [('Measured data', h, t)]
        # 线性拟合
        A = np.vstack([h, np.ones_like(h)]).T
        k, b = np.linalg.lstsq(A, t, rcond=None)[0]
        fit = k * h + b
        series.append((f'Best fit (gradient = {k * 100:.2f} C/100m)', h, fit))
        self.canvas.plot_lines(series, xlabel='Mean Temperature (C)',
                               ylabel='Height Above Ground (m)')


# ------------------------------------------------------------------ 8. Wind Turbine Output
class WindTurbineOutputDialog(_AnalysisDialogBase):
    """风机发电量：功率曲线 + 密度修正 + 轮毂高度外推 + AEP/NCF。"""

    TITLE = 'Wind Turbine Output'

    def _build_controls(self):
        import json
        import os

        form = QFormLayout()
        self.cmb_speed = QComboBox()
        form.addRow('Wind speed sensor', self.cmb_speed)

        self.sp_meas_h = QDoubleSpinBox()
        self.sp_meas_h.setRange(1, 1000)
        self.sp_meas_h.setValue(100.0)
        form.addRow('Measurement height (m)', self.sp_meas_h)
        self.sp_hub_h = QDoubleSpinBox()
        self.sp_hub_h.setRange(1, 1000)
        self.sp_hub_h.setValue(100.0)
        form.addRow('Hub height (m)', self.sp_hub_h)
        self.sp_alpha = QDoubleSpinBox()
        self.sp_alpha.setRange(0.0, 1.0)
        self.sp_alpha.setDecimals(3)
        self.sp_alpha.setValue(0.14)
        form.addRow('Power law exponent α', self.sp_alpha)

        self.cmb_model = QComboBox()
        from core.paths import resource_path
        turb_path = resource_path('data', 'turbines.json')
        self._turbines = []
        try:
            if os.path.exists(turb_path):
                with open(turb_path, encoding='utf-8') as f:
                    self._turbines = json.load(f)
        except (OSError, ValueError):
            self._turbines = []
        self.cmb_model.addItem('—', None)
        for t in self._turbines:
            self.cmb_model.addItem(f"{t.get('vendor', '')} {t.get('model', '')}"
                                   f" ({t.get('p', '?')} kW)", t.get('model'))
        form.addRow('Turbine model', self.cmb_model)

        self.sp_rating = QDoubleSpinBox()
        self.sp_rating.setRange(1, 100000)
        self.sp_rating.setValue(3000.0)
        form.addRow('Rated power (kW)', self.sp_rating)

        grp_reg = QGroupBox(tr('Power regulation'))
        rl = QHBoxLayout(grp_reg)
        self.rb_pitch = QRadioButton(tr('Pitch')); self.rb_pitch.setChecked(True)
        self.rb_stall = QRadioButton(tr('Stall'))
        rl.addWidget(self.rb_pitch); rl.addWidget(self.rb_stall)
        form.addRow(grp_reg)

        self.sp_rho = QDoubleSpinBox()
        self.sp_rho.setRange(0.3, 2.0)
        self.sp_rho.setDecimals(3)
        self.sp_rho.setValue(1.225)
        form.addRow('Air density (kg/m3)', self.sp_rho)
        self.sp_loss = QDoubleSpinBox()
        self.sp_loss.setRange(0, 100)
        self.sp_loss.setValue(10.0)
        self.sp_loss.setSuffix(' %')
        form.addRow('Overall loss factor', self.sp_loss)
        self.left_lay.addLayout(form)

        grp_curve = QGroupBox('Power curve (m/s → kW, editable)')
        cv = QVBoxLayout(grp_curve)
        self.tbl_curve = QTableWidget(0, 2)
        self.tbl_curve.setHorizontalHeaderLabels(['Speed (m/s)', 'Power (kW)'])
        self.tbl_curve.verticalHeader().setVisible(False)
        cv.addWidget(self.tbl_curve, 1)
        hb = QHBoxLayout()
        btn_example = QPushButton(tr('Fill example curve'))
        btn_example.clicked.connect(self._fill_example_curve)
        hb.addWidget(btn_example)
        hb.addStretch(1)
        cv.addLayout(hb)
        self.left_lay.addWidget(grp_curve, 2)

        self.btn_calc = QPushButton(tr('Calculate Results'))
        self.left_lay.addWidget(self.btn_calc)

        self.left_lay.addStretch(1)

        for n, ch in self.ds.channels.items():
            if ch.kind == KIND_SPEED and getattr(ch, 'role', 'Avg') == 'Avg':
                self.cmb_speed.addItem(display_name(n), n)

        self.cmb_speed.currentIndexChanged.connect(self._on_speed_changed)
        self.cmb_model.currentIndexChanged.connect(self._on_model_changed)
        self.btn_calc.clicked.connect(self.refresh)

        # 默认选择第一个风速通道并联动高度
        if self.cmb_speed.currentIndex() < 0 and self.cmb_speed.count():
            self.cmb_speed.setCurrentIndex(0)
        self._on_speed_changed()
        self._fill_example_curve()

    def _curve_data(self):
        """读取可编辑功率曲线表 → (curve_u, curve_p)。"""
        us, ps = [], []
        for r in range(self.tbl_curve.rowCount()):
            try:
                u = float(self.tbl_curve.item(r, 0).text())
                p = float(self.tbl_curve.item(r, 1).text())
            except (AttributeError, ValueError, TypeError):
                continue
            us.append(u)
            ps.append(max(p, 0.0))
        us = np.asarray(us, dtype=float)
        ps = np.asarray(ps, dtype=float)
        order = np.argsort(us)
        return us[order], ps[order]

    def _fill_example_curve(self):
        """按当前额定功率填充示例曲线（IEC 风格：3 m/s 切入、15 m/s 满发）。"""
        self.tbl_curve.setRowCount(0)
        rating = self.sp_rating.value()
        for v in range(1, 26):
            if v < 3:
                p = 0.0
            elif v < 15:
                p = rating * ((v - 3) / 12.0) ** 3
            else:
                p = rating
            r = self.tbl_curve.rowCount()
            self.tbl_curve.insertRow(r)
            self.tbl_curve.setItem(r, 0, QTableWidgetItem(f'{v}'))
            self.tbl_curve.setItem(r, 1, QTableWidgetItem(f'{p:.0f}'))

    def _on_speed_changed(self):
        col = self.cmb_speed.currentData()
        if col:
            h = _height_of(col)
            if h:
                self.sp_meas_h.setValue(h)
                self.sp_hub_h.setValue(h)

    def _on_model_changed(self):
        for t in self._turbines:
            if t.get('model') == self.cmb_model.currentData():
                if t.get('p'):
                    self.sp_rating.setValue(float(t['p']))
                break

    def _build_right(self):
        self.result_table = QTableWidget(4, 2)
        self.result_table.setHorizontalHeaderLabels(['Metric', 'Value'])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.right_lay.addWidget(self.result_table)

        self.tabs = QTabWidget()
        self.c_curve = PlotCanvas('Power Curve')
        self.c_monthly = PlotCanvas('Monthly Net Energy')
        self.c_series = PlotCanvas('Power Output Time Series')
        self.tabs.addTab(self.c_curve, tr('Power Curve'))
        self.tabs.addTab(self.c_monthly, tr('Monthly Energy'))
        self.tabs.addTab(self.c_series, tr('Time Series'))
        self.right_lay.addWidget(self.tabs, 1)

    def refresh(self):
        from core.turbine_power import (aep_kw_hours,
                                                effective_speed,
                                                hub_height_speed,
                                                monthly_energy,
                                                output_series,
                                                power_from_curve,
                                                rating_from_curve)
        col = self.cmb_speed.currentData()
        if not col or self.ds.df.empty:
            self.c_curve.clear('No data')
            return
        curve_u, curve_p = self._curve_data()
        if len(curve_u) < 2:
            self.c_curve.clear('Power curve requires at least 2 points')
            return
        rating = self.sp_rating.value() or rating_from_curve(curve_p)

        speed = _to_num(self.ds.df[col])
        speed = hub_height_speed(speed, self.sp_meas_h.value(),
                                 self.sp_hub_h.value(), self.sp_alpha.value())
        mask = self._mask()
        if mask is not None:
            speed = speed[mask.reindex(speed.index).fillna(False)]
        speed = speed.dropna()
        if speed.empty:
            self.c_curve.clear('No valid data')
            return

        # 空气密度：优先用数据集内的温度/气压通道均值计算
        temp = pres = None
        for n, ch in self.ds.channels.items():
            if ch.kind == 'temp' and temp is None and n in self.ds.df.columns:
                temp = n
            if ch.kind == 'pres' and pres is None and n in self.ds.df.columns:
                pres = n
        if temp and pres:
            t = pd.to_numeric(self.ds.df[temp], errors='coerce').mean()
            p = pd.to_numeric(self.ds.df[pres], errors='coerce').mean()
            if pd.notna(t) and pd.notna(p):
                self.sp_rho.setValue(round(float(p * 100.0)
                                           / (287.05 * (t + 273.15)), 3))
        rho = self.sp_rho.value()

        method = 'stall' if self.rb_stall.isChecked() else 'pitch'
        loss = 1.0 - self.sp_loss.value() / 100.0
        u_eff = effective_speed(speed.to_numpy(), rho, 1.225) \
            if method == 'pitch' else speed.to_numpy()
        if method == 'stall':
            gross = power_from_curve(curve_u, curve_p, speed.to_numpy()) \
                * rho / 1.225
        else:
            gross = power_from_curve(curve_u, curve_p, u_eff)
        gross = pd.Series(gross, index=speed.index) * loss

        p_gross = float(gross.mean()) if len(gross) else 0.0
        p_net = p_gross
        aep = aep_kw_hours(p_net)
        ncf = capacity_factor(p_net, rating)

        rows = [
            ('Mean gross power', f'{p_gross:,.0f} kW'),
            ('Mean net power', f'{p_net:,.0f} kW'),
            ('AEP (net)', f'{aep / 1000.0:,.0f} MWh/yr'),
            ('Net capacity factor', f'{ncf * 100.0:.1f} %'),
        ]
        self.result_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.result_table.setItem(r, 0, QTableWidgetItem(k))
            self.result_table.setItem(r, 1, QTableWidgetItem(v))

        # 功率曲线图
        self.c_curve.plot_line(curve_u, curve_p, xlabel='Wind speed (m/s)',
                               ylabel='Power (kW)', ymin=0)
        # 逐月电量
        me = monthly_energy(gross)
        if not me.empty:
            self.c_monthly.plot_bar(me['month'].to_numpy(),
                                    me['energy'].to_numpy(),
                                    xlabel='Month', ylabel='Energy (kWh)',
                                    ymin=0)
        # 时序（抽稀：最多 3000 点）
        ts = gross.dropna()
        if len(ts) > 3000:
            ts = ts.iloc[::max(1, len(ts) // 3000)]
        self.c_series.plot_line(ts.index, ts.to_numpy(),
                                xlabel='Time', ylabel='Net power (kW)',
                                ymin=0, xtick_fmt='date')


# ------------------------------------------------------------------ 9. Inflow Angle Analysis
class InflowAngleDialog(_AnalysisDialogBase):
    TITLE = 'Inflow Angle Analysis'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_display = QComboBox(); self.cmb_display.addItems(['mean inflow angle'])
        self.cmb_versus = QComboBox(); self.cmb_versus.addItems(['wind speed'])
        form.addRow('Display', self.cmb_display)
        form.addRow('versus', self.cmb_versus)

        self.sp_sectors = QSpinBox(); self.sp_sectors.setRange(4, 36); self.sp_sectors.setValue(16)
        form.addRow('Direction sectors', self.sp_sectors)

        self.cmb_pair = QComboBox()
        form.addRow('Wind speed sensor pairs', self.cmb_pair)
        self.left_lay.addLayout(form)

        self.filter = self._add_filter()

        speeds = _speed_cols(self.ds)
        for i, a in enumerate(speeds):
            for b in speeds[i + 1:]:
                self.cmb_pair.addItem(f'{display_name(a)} / {display_name(b)}', (a, b))

    def _build_right(self):
        self.canvas = PlotCanvas('Mean Inflow Angle')
        self.right_lay.addWidget(self.canvas, 1)

    def refresh(self):
        pair = self.cmb_pair.currentData()
        if pair is None or self.ds is None:
            self.canvas.clear(tr('请选择风速对'))
            return
        a, b = pair
        s1 = self._series(a)
        s2 = self._series(b)
        # 简化：把 a 当垂直分量，b 当水平分量
        angle = np.degrees(np.arctan2(s1, s2))
        # 按风速分 bin
        bins = np.arange(0, s2.max() + 2, 2)
        mids = (bins[:-1] + bins[1:]) / 2
        means = []
        for lo, hi in zip(bins[:-1], bins[1:]):
            mask = (s2 >= lo) & (s2 < hi)
            means.append(angle[mask].mean() if mask.any() else np.nan)
        self.canvas.plot_line(mids, np.array(means),
                              xlabel='Wind Speed (m/s)',
                              ylabel='Mean Inflow Angle (deg)')


# ------------------------------------------------------------------ 10. Wind Power Class Analysis
class WindPowerClassDialog(_AnalysisDialogBase):
    TITLE = 'Wind Power Class Analysis'

    def _build_controls(self):
        self.filter = self._add_filter(with_direction=True, with_data_col=True)

        grp = QGroupBox(tr('Plot type'))
        g_lay = QHBoxLayout(grp)
        self.rb_linear = QRadioButton(tr('Linear')); self.rb_linear.setChecked(True)
        self.rb_log = QRadioButton(tr('Logarithmic'))
        g_lay.addWidget(self.rb_linear); g_lay.addWidget(self.rb_log)
        self.left_lay.addWidget(grp)

    def _build_right(self):
        self.canvas = PlotCanvas('Mean of Monthly Means of Wind Power Density vs. Height')
        self.right_lay.addWidget(self.canvas, 2)
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(['Height (m)', 'MoMM of Wind Power Density (W/m2)'])
        self.right_lay.addWidget(self.table, 1)

    def refresh(self):
        if self.ds is None:
            self.canvas.clear(tr('未载入数据集'))
            return
        rows = []
        heights, densities = [], []
        rho = 1.225
        for col in _speed_cols(self.ds):
            h = _height_of(col)
            if h is None:
                continue
            s = self._series(col)
            momm = s.resample('MS').mean().groupby(lambda t: t.month).mean().mean()
            p = 0.5 * rho * momm ** 3
            heights.append(h)
            densities.append(p)
            rows.append([h, f'{p:.0f}'])
        if not heights:
            self.canvas.clear(tr('无法识别高度'))
            return
        order = np.argsort(heights)
        h = np.array(heights)[order]
        p = np.array(densities)[order]
        # 线性/对数轴用现有 plot_line；对数刻度暂以数值近似
        self.canvas.plot_line(h, p, xlabel='Height Above Ground (m)',
                              ylabel='MoMM of Wind Power Density (W/m2)', ymin=0)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))


# ------------------------------------------------------------------ 11. Short Time Interval Analysis
class ShortTimeIntervalDialog(_AnalysisDialogBase):
    """短时间间隔分析：逐区间查看廓线 / 矢量平均方向 / 时间序列。"""

    TITLE = 'Short Time Interval Analysis'

    def _build_controls(self):
        form = QFormLayout()
        self.sp_avg = QSpinBox(); self.sp_avg.setRange(1, 10000); self.sp_avg.setValue(6)
        self.sp_jump = QSpinBox(); self.sp_jump.setRange(1, 10000); self.sp_jump.setValue(6)
        form.addRow('Averaging interval (time steps)', self.sp_avg)
        form.addRow('Jump size (time steps)', self.sp_jump)
        self.left_lay.addLayout(form)

        h_step = QHBoxLayout()
        self.btn_prev = QPushButton('\u25c0 Prev')
        self.btn_next = QPushButton('Next \u25b6')
        h_step.addWidget(self.btn_prev)
        h_step.addWidget(self.btn_next)
        self.left_lay.addLayout(h_step)

        self.left_lay.addWidget(QLabel(tr('Display interval')))
        h = QHBoxLayout()
        self.lbl_start = QLabel(tr('Start'))
        self.lbl_end = QLabel(tr('End'))
        h.addWidget(self.lbl_start); h.addWidget(self.lbl_end)
        self.left_lay.addLayout(h)

        self.col_list = _CheckList('Columns')
        self.col_list.set_items([display_name(c) for c in _numeric_cols(self.ds)])
        self.left_lay.addWidget(self.col_list, 1)

        self.filter = self._add_filter()

        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.btn_next.clicked.connect(lambda: self._step(1))
        self.sp_avg.valueChanged.connect(self._step)
        self.sp_jump.valueChanged.connect(self._step)

    def _build_right(self):
        self.c_ts = PlotCanvas('Time Series')
        self.c_shear = PlotCanvas('Vertical Wind Shear Profile')
        self.c_rose = PlotCanvas('Mean Speed and Direction')
        self.tbl_shear = QTableWidget(0, 4)
        self.tbl_shear.setHorizontalHeaderLabels(
            ['Sensor', 'Height (m)', 'Valid Steps', 'Mean Speed (m/s)'])
        self.tbl_shear.verticalHeader().setVisible(False)
        right = QVBoxLayout()
        right.addWidget(self.c_ts, 1)
        right.addWidget(self.c_shear, 1)
        right.addWidget(self.tbl_shear, 1)
        holder = QWidget()
        holder.setLayout(right)
        self.right_lay.addWidget(holder, 1)
        self.right_lay.addWidget(self.c_rose, 1)

    def _subset(self) -> pd.DataFrame:
        df = self.ds.df
        mask = self._mask()
        if mask is not None:
            df = df[mask.reindex(df.index).fillna(False)]
        return df

    def _speed_sensors(self):
        out = []
        for n, ch in self.ds.channels.items():
            if (ch.kind == 'speed' and getattr(ch, 'role', 'Avg') == 'Avg'
                    and n in self.ds.df.columns):
                h = _height_of(n)
                out.append((n, h if h else 0.0))
        out.sort(key=lambda t: t[1])
        return out

    def _dir_sensors(self):
        out = []
        for n, ch in self.ds.channels.items():
            if (ch.kind == 'dir' and getattr(ch, 'role', 'Avg') == 'Avg'
                    and n in self.ds.df.columns):
                h = _height_of(n)
                out.append((n, h if h else 0.0))
        out.sort(key=lambda t: t[1])
        return out

    def _nearest_speed(self, h_dir):
        best, bh = None, 1e9
        for n, h in self._speed_sensors():
            if abs(h - h_dir) < bh:
                best, bh = n, abs(h - h_dir)
        return best

    def _step(self, direction: int):
        jump = max(self.sp_jump.value(), 1)
        df = self._subset()
        self._pos = int(getattr(self, '_pos', 0)) + direction * jump
        n = len(df)
        avg = max(self.sp_avg.value(), 1)
        self._pos = max(0, min(self._pos, max(n - avg, 0)))
        self.refresh()

    def refresh(self):
        df = self._subset()
        if df.empty:
            for c in (self.c_ts, self.c_shear, self.c_rose):
                c.clear('No data')
            self.tbl_shear.setRowCount(0)
            return
        avg = max(self.sp_avg.value(), 1)
        pos = int(getattr(self, '_pos', 0))
        pos = max(0, min(pos, max(len(df) - avg, 0)))
        seg = df.iloc[pos: pos + avg]

        self.lbl_start.setText(str(seg.index[0]))
        self.lbl_end.setText(str(seg.index[-1]))

        # ---- 廓线 + 表 ----
        sensors = self._speed_sensors()
        hs, vs, counts = [], [], []
        for name, h in sensors:
            v = _to_num(seg[name]) if name in seg.columns else None
            if v is None or v.notna().sum() == 0:
                continue
            hs.append(h)
            vs.append(float(v.mean()))
            counts.append(int(v.notna().sum()))
        mean_by_h = dict(zip(hs, vs))
        rows = [(name, h, mean_by_h.get(h), cnt)
                for (name, h), cnt in zip(sensors, counts)
                if h in mean_by_h]
        if len(hs) >= 2:
            b, a = np.polyfit(np.log(np.asarray(hs)), np.log(np.asarray(vs)), 1)
            h_fit = np.linspace(min(hs), max(hs), 40)
            v_fit = np.exp(a + b * np.log(h_fit))
            series = [('Measured', np.asarray(hs, dtype=float),
                       np.asarray(vs, dtype=float), 'o'),
                      (f'Power law (\u03b1={b:.3f})', h_fit, v_fit)]
            self.c_shear.plot_lines(series, xlabel='Wind speed (m/s)',
                                    ylabel='Height (m)', xtick_step=1.0)
        else:
            self.c_shear.clear(tr('\u9700\u8981\u81f3\u5c11\u4e24\u4e2a\u9ad8\u5ea6\u7684\u98ce\u901f\u4f20\u611f\u5668'))
        self.tbl_shear.setRowCount(len(rows))
        for i, (name, h, mean, cnt) in enumerate(rows):
            for c, val in enumerate((name, f'{h:g}', str(cnt),
                                     f'{mean:.2f}' if mean is not None
                                     and not np.isnan(mean) else '')):
                self.tbl_shear.setItem(i, c, QTableWidgetItem(str(val)))

        # ---- 矢量平均方向 + 玫瑰散点 ----
        dir_rows = []
        for name, h in self._dir_sensors():
            sp_col = self._nearest_speed(h)
            if not sp_col or sp_col not in seg.columns:
                continue
            d = _to_num(seg[name])
            v = _to_num(seg[sp_col])
            ok = d.notna() & v.notna() & (d >= 0) & (d < 360)
            if ok.sum() == 0:
                continue
            rad = np.deg2rad(d[ok])
            u = float((v[ok] * np.sin(rad)).mean())
            w = float((v[ok] * np.cos(rad)).mean())
            d_mean = math.degrees(math.atan2(u, w)) % 360.0
            dir_rows.append((name, h, float(v[ok].mean()),
                             d_mean, int(ok.sum())))
        if dir_rows:
            pts = np.array([[r[3], r[2]] for r in dir_rows], dtype=float)
            self.c_rose.plot_polar(sectors=36, freq=pts,
                                   display_type='scatter_plot',
                                   labels=[r[0] for r in dir_rows])
        else:
            self.c_rose.clear(tr('\u65e0\u98ce\u5411\u6570\u636e'))

        # ---- 时间序列（最高层风速 + 区间高亮）----
        if speeds := self._speed_sensors():
            primary = speeds[-1][0]        # 最高层风速
            full = _to_num(df[primary]).dropna()
            step = max(1, len(full) // 3000)
            fs = full.iloc[::step]
            series = [(display_name(primary), fs.index.to_numpy(),
                       fs.to_numpy())]
            if primary in seg.columns:
                series.append(('Interval', seg.index.to_numpy(),
                               _to_num(seg[primary]).to_numpy()))
            self.c_ts.plot_lines(series, xlabel='Time', ymin=0,
                                 xtick_fmt='date')

# ------------------------------------------------------------------ 12. Long Term Analysis
class LongTermAnalysisDialog(_AnalysisDialogBase):
    """长期分析：年际变化 / 逐月逐时轮廓 / 频率玫瑰 / 累计 IAV（手册 11.11）。"""

    TITLE = 'Long Term Analysis'
    DISPLAYS = [
        'Annual means',
        'Histogram of Annual Means',
        'Frequency Rose by Year',
        'Monthly Profile by Year',
        'Diurnal Profile by Year',
        'Frequency Histogram by Year',
        'Inter-Annual Variation',
    ]

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_display = QComboBox(); self.cmb_display.addItems(self.DISPLAYS)
        self.cmb_col = QComboBox()
        form.addRow('Display', self.cmb_display)
        form.addRow('Data column', self.cmb_col)
        h_dir = QHBoxLayout()
        self.cmb_dir = QComboBox(); self.cmb_dir.setEnabled(False)
        self.sp_sectors = QSpinBox(); self.sp_sectors.setRange(4, 36)
        self.sp_sectors.setValue(16); self.sp_sectors.setEnabled(False)
        h_dir.addWidget(self.cmb_dir)
        h_dir.addWidget(QLabel(tr('Sectors')))
        h_dir.addWidget(self.sp_sectors)
        form.addRow('Direction sensor', h_dir)
        self.left_lay.addLayout(form)
        self.filter = self._add_filter(with_direction=False)

        for n in _numeric_cols(self.ds):
            self.cmb_col.addItem(display_name(n), n)
        for n, ch in self.ds.channels.items():
            if ch.kind == 'dir' and getattr(ch, 'role', 'Avg') == 'Avg':
                self.cmb_dir.addItem(display_name(n), n)

        self.cmb_display.currentIndexChanged.connect(self._on_display_changed)
        self.cmb_col.currentIndexChanged.connect(self.refresh)
        self.cmb_dir.currentIndexChanged.connect(self.refresh)
        self.sp_sectors.valueChanged.connect(self.refresh)

    def _on_display_changed(self):
        rose = self.cmb_display.currentText() == 'Frequency Rose by Year'
        self.cmb_dir.setEnabled(rose)
        self.sp_sectors.setEnabled(rose)
        self.refresh()

    def _annual_frame(self, s: pd.Series) -> pd.DataFrame:
        g = s.groupby(s.index.year)
        return pd.DataFrame({'count': g.count(), 'mean': g.mean()})

    def _iav(self, annual_means: pd.Series) -> float:
        """年际变化 IAV（%）= 年均值标准差 / 年均值均值 × 100。"""
        if len(annual_means) < 2 or annual_means.mean() == 0:
            return float('nan')
        return float(annual_means.std(ddof=1) / annual_means.mean() * 100.0)

    def _build_right(self):
        self.canvas = PlotCanvas('Long Term Analysis')
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Year', 'Mean', 'Valid Points'])
        self.table.verticalHeader().setVisible(False)
        self.right_lay.addWidget(self.canvas, 1)
        self.right_lay.addWidget(self.table, 1)

    def refresh(self):
        from core.wind_rose import compute_rose
        col = self.cmb_col.currentData()
        if col is None or self.ds is None:
            self.canvas.clear(tr('请选择数据列'))
            return
        s = self._series(col).dropna()
        if s.empty:
            self.canvas.clear('No data')
            return
        disp = self.cmb_display.currentText()
        annual = s.groupby(s.index.year)

        if disp == 'Annual means':
            means = annual.mean()
            self.canvas.plot_bar(means.index.values, means.values,
                                 xlabel='Year', ylabel='Mean', ymin=0)
            self._fill_table(means.index, means.values, annual.count())
        elif disp == 'Histogram of Annual Means':
            means = annual.mean()
            counts, edges = np.histogram(means.values,
                                         bins=min(10, max(4, len(means))))
            centers = (edges[:-1] + edges[1:]) / 2
            self.canvas.plot_bar(centers, counts, xlabel='Annual mean',
                                 ylabel='Years', ymin=0)
            self._fill_table(centers, counts, None)
        elif disp == 'Inter-Annual Variation':
            means = annual.mean().sort_index()          # 年升序
            iavs = []
            # 累计 IAV：从最近一年开始，逐年向前扩展后重算
            for n_back in range(1, len(means) + 1):
                sub = means.iloc[len(means) - n_back:]
                iav = self._iav(sub) if n_back >= 2 else float('nan')
                iavs.append((sub.index[0], iav))
            xs = [x[0] for x in iavs]
            ys = [x[1] for x in iavs]
            self.canvas.plot_line(xs, ys, xlabel='Year',
                                  ylabel='Cumulative IAV (%)', ymin=0)
            self._fill_table(xs, ys, None)
        elif disp == 'Frequency Rose by Year':
            dir_col = self.cmb_dir.currentData()
            if not dir_col:
                self.canvas.clear('Requires direction sensor')
                return
            sectors = self.sp_sectors.value()
            mids = [(i + 0.5) * 360.0 / sectors for i in range(sectors)]
            series = []
            for y, g in s.groupby(s.index.year):
                r = compute_rose(self.ds.df.loc[g.index], dir_col,
                                 sectors=sectors, display='frequency',
                                 versus='direction')
                if r is not None:
                    series.append((str(y), mids, r.values[:, 0]))
            if not series:
                self.canvas.clear('No rose data')
                return
            self.canvas.plot_lines(series, xlabel='Direction (°)',
                                   ylabel='Frequency (%)', ymin=0)
            self._fill_table(None, None, None)
        elif disp == 'Monthly Profile by Year':
            series = [(str(y), g.groupby(g.index.month).mean().index.to_numpy(),
                       g.groupby(g.index.month).mean().to_numpy())
                      for y, g in s.groupby(s.index.year)]
            self.canvas.plot_lines(series, xlabel='Month', ylabel='Mean',
                                   ymin=0, xtick_fmt='month')
            self._fill_table(None, None, None)
        elif disp == 'Diurnal Profile by Year':
            series = [(str(y), g.groupby(g.index.hour).mean().index.to_numpy(),
                       g.groupby(g.index.hour).mean().to_numpy())
                      for y, g in s.groupby(s.index.year)]
            self.canvas.plot_lines(series, xlabel='Hour of Day', ylabel='Mean',
                                   ymin=0, xtick_fmt='hour')
            self._fill_table(None, None, None)
        elif disp == 'Frequency Histogram by Year':
            vmin, vmax = float(s.min()), float(s.max())
            width = max((vmax - vmin) / 25.0, 0.1)
            edges = np.arange(np.floor(vmin), np.ceil(vmax) + width, width)
            centers = (edges[:-1] + edges[1:]) / 2
            series = []
            for y, g in s.groupby(s.index.year):
                counts, _ = np.histogram(g.to_numpy(), bins=edges)
                freq = counts / max(counts.sum(), 1) * 100.0
                series.append((str(y), centers, freq))
            self.canvas.plot_lines(series, xlabel='Wind speed bin',
                                   ylabel='Frequency (%)', ymin=0)
            self._fill_table(None, None, None)
        else:
            self.canvas.clear()

    def _fill_table(self, keys, values, counts):
        """Annual means / IAV 等表格视图（keys=None 时清空）。"""
        if keys is None:
            self.table.setRowCount(0)
            return
        self.table.setRowCount(len(keys))
        self.table.setHorizontalHeaderLabels(['Year', 'Mean', 'Valid Points'])
        for i, k in enumerate(keys):
            mean = values[i] if values is not None and i < len(values) else None
            cnt = counts[i] if counts is not None and i < len(counts) else None
            mean_bad = (mean is None or (isinstance(mean, float)
                                         and np.isnan(mean)))
            cnt_bad = (cnt is None or (isinstance(cnt, float)
                                       and np.isnan(cnt)))
            self.table.setItem(i, 0, QTableWidgetItem(str(k)))
            self.table.setItem(i, 1, QTableWidgetItem(
                f'{mean:.3f}' if not mean_bad else ''))
            self.table.setItem(i, 2, QTableWidgetItem(
                f'{int(cnt):,}' if not cnt_bad else ''))


# ------------------------------------------------------------------ 13. Probability of Exceedence
class ProbabilityOfExceedenceDialog(_AnalysisDialogBase):
    TITLE = 'Probability of Exceedence'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_col = QComboBox()
        self.sp_min_steps = QSpinBox(); self.sp_min_steps.setRange(1, 99999); self.sp_min_steps.setValue(5000)
        form.addRow('Data column', self.cmb_col)
        form.addRow('Minimum number of time steps', self.sp_min_steps)
        self.left_lay.addLayout(form)
        self.filter = self._add_filter(with_direction=False, with_data_col=False)

        for n in _speed_cols(self.ds):
            self.cmb_col.addItem(display_name(n), n)

    def _build_right(self):
        self.tbl_yearly = QTableWidget()
        self.tbl_yearly.setColumnCount(4)
        self.tbl_yearly.setHorizontalHeaderLabels(['Year', 'Time Steps', 'Data Coverage (%)', 'Mean (m/s)'])
        self.tbl_bins = QTableWidget()
        self.tbl_bins.setColumnCount(4)
        self.tbl_bins.setHorizontalHeaderLabels(['Bin', 'Bin Endpoints (m/s)', 'Occurrences', 'Frequency (%)'])
        self.canvas = PlotCanvas('Probability of Exceedence')
        self.right_lay.addWidget(self.tbl_yearly, 1)
        self.right_lay.addWidget(self.tbl_bins, 1)
        self.right_lay.addWidget(self.canvas, 2)

    def refresh(self):
        col = self.cmb_col.currentData()
        if col is None or self.ds is None:
            self.canvas.clear(tr('请选择数据列'))
            return
        s = self._series(col)
        # yearly table
        yearly = s.groupby(s.index.year).agg(['count', 'mean'])
        self.tbl_yearly.setRowCount(len(yearly))
        for r, (year, row) in enumerate(yearly.iterrows()):
            coverage = row['count'] / (8760 if pd.infer_freq(s.index) == 'H' else 52560) * 100
            self.tbl_yearly.setItem(r, 0, QTableWidgetItem(str(year)))
            self.tbl_yearly.setItem(r, 1, QTableWidgetItem(str(int(row['count']))))
            self.tbl_yearly.setItem(r, 2, QTableWidgetItem(f'{coverage:.2f}'))
            self.tbl_yearly.setItem(r, 3, QTableWidgetItem(f'{row["mean"]:.3f}'))
        # bins
        bins = np.arange(2, 13, 1)
        counts, _ = np.histogram(s.dropna(), bins=bins)
        self.tbl_bins.setRowCount(len(counts) + 1)
        total = counts.sum()
        for i, (lo, hi, cnt) in enumerate(zip(bins[:-1], bins[1:], counts)):
            self.tbl_bins.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.tbl_bins.setItem(i, 1, QTableWidgetItem(f'{lo:.0f} - {hi:.0f}'))
            self.tbl_bins.setItem(i, 2, QTableWidgetItem(str(cnt)))
            self.tbl_bins.setItem(i, 3, QTableWidgetItem(f'{cnt / total * 100:.3f}' if total else '0'))
        self.tbl_bins.setItem(len(counts), 0, QTableWidgetItem('All bins'))
        self.tbl_bins.setItem(len(counts), 2, QTableWidgetItem(str(total)))
        self.tbl_bins.setItem(len(counts), 3, QTableWidgetItem('100.000'))
        # POE plot
        sorted_vals = np.sort(s.dropna().values)
        poe = 1 - np.arange(1, len(sorted_vals) + 1) / (len(sorted_vals) + 1)
        self.canvas.plot_scatter(sorted_vals, poe * 100,
                                 xlabel='Annual Mean (m/s)', ylabel='Probability of Exceedence (%)')


# ------------------------------------------------------------------ 14. Extreme Wind Analysis
class ExtremeWindAnalysisDialog(_AnalysisDialogBase):
    """极端风分析：Periodic Maxima / Independent Storms / EWTS II 三算法。"""

    TITLE = 'Extreme Wind Analysis'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_speed = QComboBox()
        form.addRow('Wind speed sensor', self.cmb_speed)

        grp = QGroupBox(tr('Mode'))
        g_lay = QHBoxLayout(grp)
        self.rb_mean = QRadioButton(tr('Mean wind speeds')); self.rb_mean.setChecked(True)
        self.rb_gust = QRadioButton(tr('Gusts'))
        g_lay.addWidget(self.rb_mean); g_lay.addWidget(self.rb_gust)
        self.left_lay.addWidget(grp)

        self.cmb_period = QComboBox()
        self.cmb_period.addItems(['Year', 'Month'])
        form.addRow('Period', self.cmb_period)

        self.sp_recovery = QSpinBox()
        self.sp_recovery.setRange(0, 100)
        self.sp_recovery.setValue(60)
        form.addRow('Min recovery (%)', self.sp_recovery)

        grp_mos = QGroupBox(tr('Method of Independent Storms'))
        fm_ = QFormLayout(grp_mos)
        self.sp_threshold = QDoubleSpinBox()
        self.sp_threshold.setRange(0.0, 200.0)
        self.sp_threshold.setValue(12.0)
        self.btn_recommended = QPushButton(tr('Set Recommended'))
        h_rec = QHBoxLayout()
        h_rec.addWidget(self.sp_threshold)
        h_rec.addWidget(self.btn_recommended)
        fm_.addRow('Threshold (m/s)', h_rec)
        self.sp_indep = QDoubleSpinBox()
        self.sp_indep.setRange(1.0, 240.0)
        self.sp_indep.setValue(48.0)
        fm_.addRow('Independence (hours)', self.sp_indep)
        self.left_lay.addWidget(grp_mos)

        self.left_lay.addLayout(form)
        self.filter = self._add_filter(with_direction=False, with_data_col=False)

        for n in _speed_cols(self.ds):
            self.cmb_speed.addItem(display_name(n), n)

        self.cmb_speed.currentIndexChanged.connect(self.refresh)
        self.rb_mean.toggled.connect(self.refresh)
        self.rb_gust.toggled.connect(self.refresh)
        self.cmb_period.currentIndexChanged.connect(self.refresh)
        self.sp_recovery.valueChanged.connect(self.refresh)
        self.sp_threshold.valueChanged.connect(self.refresh)
        self.sp_indep.valueChanged.connect(self.refresh)
        self.btn_recommended.clicked.connect(self._set_recommended_threshold)

    def _build_right(self):
        self.result_table = QTableWidget(5, 2)
        self.result_table.setHorizontalHeaderLabels(
            ['Algorithm', '50-yr extreme (m/s)'])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.right_lay.addWidget(self.result_table)

        self.tabs = QTabWidget()
        self.tab1 = PlotCanvas('Periodic Maxima')
        self.tab2 = PlotCanvas('Method of Independent Storms')
        self.tab3 = PlotCanvas('EWTS II')
        self.tabs.addTab(self.tab1, tr('Periodic Maxima'))
        self.tabs.addTab(self.tab2, tr('Method of Independent Storms'))
        self.tabs.addTab(self.tab3, tr('EWTS II'))
        self.right_lay.addWidget(self.tabs, 1)

    def _active_series(self):
        """当前速度序列（Gusts 模式取关联 max 通道），已按标记过滤。"""
        col = self.cmb_speed.currentData()
        if col is None or self.ds.df.empty:
            return None
        s = _to_num(self.ds.df[col])
        mask = self._mask()
        if mask is not None:
            s = s[mask.reindex(s.index).fillna(False)]
        if self.rb_gust.isChecked():
            ch = self.ds.channels.get(col)
            max_col = getattr(ch, 'max_col', '') if ch is not None else ''
            if max_col and max_col in self.ds.df.columns:
                g = _to_num(self.ds.df[max_col])
                if mask is not None:
                    g = g[mask.reindex(g.index).fillna(False)]
                return g.dropna()
        return s.dropna()

    def _set_recommended_threshold(self):
        """Set Recommended：使风暴数 ≈ 每年 20 场的阈值（手册 11.13.2）。"""
        s = self._active_series()
        if s is None or s.empty:
            return
        years = max((s.index[-1] - s.index[0]).total_seconds()
                    / (365.25 * 86400.0), 0.1)
        n_target = max(min(int(20 * years), len(s) - 1), 1)
        vals = np.sort(s.to_numpy())
        self.sp_threshold.setValue(round(float(vals[-n_target]), 1))

    def _dt_minutes(self, s: pd.Series) -> float:
        try:
            d = np.diff(np.asarray(s.index).astype('datetime64[s]')
                        .astype('int64')) / 60.0
            return float(np.median(d)) if d.size else 10.0
        except (TypeError, ValueError):
            return 10.0

    def refresh(self):
        from core.extreme_wind import (ewts_ii, gumbel_fit_linearized,
                                               periodic_maxima_peaks,
                                               storm_peaks, weibull_k_moment)
        s = self._active_series()
        if s is None or len(s) < 10:
            for c in (self.tab1, self.tab2, self.tab3):
                c.clear('No data')
            self.result_table.setRowCount(0)
            return

        years = max((s.index[-1] - s.index[0]).total_seconds()
                    / (365.25 * 86400.0), 0.1)

        # 1) Periodic Maxima（Harris 1996：对 v² 线性化拟合）
        period = 'month' if self.cmb_period.currentText() == 'Month' else 'year'
        dt_min = self._dt_minutes(s)
        steps_per_period = (365.25 * 24 * 60 / dt_min if period == 'year'
                            else 30.44 * 24 * 60 / dt_min)
        peaks, _rec = periodic_maxima_peaks(
            s, period,
            min_recovery=self.sp_recovery.value() / 100.0 or None,
            steps_per_period=steps_per_period)
        fit_pm = gumbel_fit_linearized(peaks, years, fit_squared=True)
        v_pm = fit_pm['v50'] if fit_pm else None

        # 2) Method of Independent Storms（Harris 1999：原值拟合）
        threshold = self.sp_threshold.value()
        peaks_mos, storms_per_year = storm_peaks(
            s, threshold, self.sp_indep.value())
        fit_mos = gumbel_fit_linearized(peaks_mos, storms_per_year,
                                        fit_squared=False)
        v_mos = fit_mos['v50'] if fit_mos else None

        # 3) EWTS II（三变体）
        v_ave = float(s.mean())
        k = weibull_k_moment(s.to_numpy())
        v_ew = ewts_ii(v_ave, k) if k else None

        rows = [
            ('Periodic Maxima', v_pm),
            ('Method of Independent Storms', v_mos),
            ('EWTS II (Exact)', v_ew['exact'] if v_ew else None),
            ('EWTS II (Gumbel)', v_ew['gumbel'] if v_ew else None),
            ('EWTS II (Davenport)', v_ew['davenport'] if v_ew else None),
        ]
        self.result_table.setRowCount(len(rows))
        for r, (name, val) in enumerate(rows):
            self.result_table.setItem(r, 0, QTableWidgetItem(name))
            self.result_table.setItem(
                r, 1, QTableWidgetItem(f'{val:.2f}' if val else '—'))

        # 绘图
        if len(peaks):
            self.tab1.plot_bar(np.arange(1, len(peaks) + 1), peaks,
                               xlabel=f'{period} #',
                               ylabel='Peak wind speed (m/s)', ymin=0)
        else:
            self.tab1.clear('No peaks (try lower recovery)')
        if len(peaks_mos):
            self.tab2.plot_bar(np.arange(1, len(peaks_mos) + 1), peaks_mos,
                               xlabel='Storm #',
                               ylabel='Peak wind speed (m/s)', ymin=0)
        else:
            self.tab2.clear('No storms above threshold')
        if v_ew and k:
            ks = np.arange(1.5, 5.01, 0.1)
            series = []
            for name in ('exact', 'gumbel', 'davenport'):
                vals = [ewts_ii(v_ave, kk)['ratios'][name] * v_ave
                        for kk in ks]
                series.append((name.capitalize(), ks, np.asarray(vals)))
            self.tab3.plot_lines(series, xlabel='Weibull k',
                                 ylabel='50-yr extreme (m/s)', ymin=0)
            self.tab3.set_title('EWTS II (Exact / Gumbel / Davenport)')
        else:
            self.tab3.clear('Weibull k unavailable')


# ------------------------------------------------------------------ 15. Representative Year
class RepresentativeYearDialog(_AnalysisDialogBase):
    TITLE = 'Representative Year'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_col = QComboBox()
        self.cmb_display = QComboBox(); self.cmb_display.addItems(['summary'])
        form.addRow('Data column', self.cmb_col)
        form.addRow('Display', self.cmb_display)
        self.left_lay.addLayout(form)
        self.filter = self._add_filter(with_direction=False)

        self.btn_gen = QPushButton(tr('Generate Representative Year'))
        self.left_lay.addWidget(self.btn_gen)

        self.tbl_summary = QTableWidget()
        self.tbl_summary.setColumnCount(3)
        self.tbl_summary.setHorizontalHeaderLabels(['Property', 'Original Data', 'Representative Year'])
        self.left_lay.addWidget(self.tbl_summary, 1)

        for n in _numeric_cols(self.ds):
            self.cmb_col.addItem(display_name(n), n)
        self.btn_gen.clicked.connect(self.refresh)

    def _build_right(self):
        self.c_annual = PlotCanvas('Annual Profile')
        self.c_diurnal = PlotCanvas('Mean Diurnal Profile')
        self.c_hist = PlotCanvas('Frequency Histogram')
        self.c_heatmap = PlotCanvas('Representative Year')
        self.right_lay.addWidget(self.c_annual, 1)
        self.right_lay.addWidget(self.c_diurnal, 1)
        self.right_lay.addWidget(self.c_hist, 1)
        self.right_lay.addWidget(self.c_heatmap, 1)

    def refresh(self):
        col = self.cmb_col.currentData()
        if col is None or self.ds is None:
            for c in (self.c_annual, self.c_diurnal, self.c_hist, self.c_heatmap):
                c.clear(tr('请选择数据列'))
            return
        s = self._series(col)
        monthly = s.groupby(s.index.month).mean()
        self.c_annual.plot_line(monthly.index.values, monthly.values,
                                xlabel='Month', ylabel=f'Mean Value ({display_name(col)})', xtick_fmt='month')
        hourly = s.groupby(s.index.hour).mean().reindex(range(24))
        self.c_diurnal.plot_line(hourly.index.values, hourly.values,
                                 xlabel='Hour of Day', ylabel=f'Mean Value ({display_name(col)})', xtick_fmt='hour')
        self.c_hist.clear('Frequency histogram requires bin settings')
        self.c_heatmap.clear('Representative year heatmap requires generation')


# ------------------------------------------------------------------ 16. Forecast Error Analysis
class ForecastErrorAnalysisDialog(_AnalysisDialogBase):
    TITLE = 'Forecast Error Analysis'

    def _build_controls(self):
        form = QFormLayout()
        self.cmb_true = QComboBox()
        self.cmb_forecast = QComboBox()
        self.cmb_display = QComboBox(); self.cmb_display.addItems(['summary'])
        form.addRow('True values', self.cmb_true)
        form.addRow('Forecast values', self.cmb_forecast)
        form.addRow('Display', self.cmb_display)

        self.cmb_dir = QComboBox()
        self.sp_sectors = QSpinBox(); self.sp_sectors.setRange(4, 36); self.sp_sectors.setValue(16)
        form.addRow('Direction sensor', self.cmb_dir)
        form.addRow('Direction sectors', self.sp_sectors)

        self.cmb_bin = QComboBox()
        self.sp_bin_width = QDoubleSpinBox(); self.sp_bin_width.setRange(0.1, 10); self.sp_bin_width.setValue(2.5)
        form.addRow('Bin column', self.cmb_bin)
        form.addRow('Bin width', self.sp_bin_width)

        self.left_lay.addLayout(form)
        self.filter = self._add_filter()

        for n in _numeric_cols(self.ds):
            self.cmb_true.addItem(display_name(n), n)
            self.cmb_forecast.addItem(display_name(n), n)
            self.cmb_bin.addItem(display_name(n), n)
        for n in _dir_cols(self.ds):
            self.cmb_dir.addItem(display_name(n), n)

    def _build_right(self):
        self.c_month = PlotCanvas('Forecast Error')
        self.c_hour = PlotCanvas('Forecast Error')
        self.c_polar = PlotCanvas('Forecast Error')
        self.right_lay.addWidget(self.c_month, 1)
        self.right_lay.addWidget(self.c_hour, 1)
        self.right_lay.addWidget(self.c_polar, 1)

    def refresh(self):
        true_col = self.cmb_true.currentData()
        fc_col = self.cmb_forecast.currentData()
        if not true_col or not fc_col or self.ds is None:
            for c in (self.c_month, self.c_hour, self.c_polar):
                c.clear(tr('请选择真值与预测列'))
            return
        t = self._series(true_col)
        f = self._series(fc_col)
        err = f - t
        # monthly
        monthly = err.groupby(err.index.month).agg(['mean', 'median', lambda x: np.sqrt((x ** 2).mean())])
        monthly.columns = ['MBE', 'MAE', 'RMSE']
        self.c_month.plot_lines([
            ('MBE', monthly.index.values, monthly['MBE'].values),
            ('MAE', monthly.index.values, monthly['MAE'].values),
            ('RMSE', monthly.index.values, monthly['RMSE'].values),
        ], xlabel='Month', ylabel='Error (m/s)', xtick_fmt='month')
        # hourly
        hourly = err.groupby(err.index.hour).agg(['mean', 'median', lambda x: np.sqrt((x ** 2).mean())])
        hourly.columns = ['MBE', 'MAE', 'RMSE']
        self.c_hour.plot_lines([
            ('MBE', hourly.index.values, hourly['MBE'].values),
            ('MAE', hourly.index.values, hourly['MAE'].values),
            ('RMSE', hourly.index.values, hourly['RMSE'].values),
        ], xlabel='Hour of Day', ylabel='Error (m/s)', xtick_fmt='hour')
        # polar
        dir_col = self.cmb_dir.currentData()
        if dir_col:
            d = self._series(dir_col)
            sectors = self.sp_sectors.value()
            bins = np.linspace(0, 360, sectors + 1)
            mids = (bins[:-1] + bins[1:]) / 2
            mbe, mae, rmse = [], [], []
            for lo, hi in zip(bins[:-1], bins[1:]):
                mask = (d >= lo) & (d < hi)
                e = err[mask]
                mbe.append(e.mean() if mask.any() else np.nan)
                mae.append(e.abs().mean() if mask.any() else np.nan)
                rmse.append(np.sqrt((e ** 2).mean()) if mask.any() else np.nan)
            self.c_polar.plot_polar(sectors, np.array(mae), 'Forecast Error by Direction',
                                    labels=['MBE', 'MAE', 'RMSE'])
