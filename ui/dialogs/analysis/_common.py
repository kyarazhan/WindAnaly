"""本包各对话框共享的助手与基类（S2 拆分聚集）。"""
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
