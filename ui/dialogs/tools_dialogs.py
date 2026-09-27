"""Tools 菜单对话框：风资源工程师常用独立计算工具。

按 Windographer 风格实现 UI 骨架与基础计算，复杂算法后续按真机反馈精调。
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
    QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from core import settings
from core.dataset import KIND_SPEED, KIND_DIR, Dataset
from ui.modules.analysis_tabs import display_name
from ui.modules.plot import PlotCanvas
from core.i18n import tr


# ------------------------------------------------------------------ 工具函数
def _load_turbines() -> list[dict]:
    """加载机型库 JSON（随包分发的只读资源）。"""
    from core.paths import resource_path
    path = resource_path('data', 'turbines.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _standard_atmosphere(elevation: float):
    """ISA：返回 (temperature_C, pressure_hPa, density_kg_m3)。"""
    # 海平面 T0=15C, p0=1013.25 hPa, 温度递减率 6.5C/km
    t = 15.0 - 0.0065 * elevation
    p = 1013.25 * (1 - 0.0065 * elevation / 288.15) ** 5.2551
    r = 287.05
    rho = (p * 100.0) / (r * (t + 273.15))
    return t, p, rho


def _air_density_dry(t: float, p_hpa: float = 1013.25) -> float:
    """干空气密度 kg/m3。"""
    return (p_hpa * 100.0) / (287.05 * (t + 273.15))


def _air_density_saturated(t: float, p_hpa: float = 1013.25) -> float:
    """饱和湿空气密度（简化 Magnus 公式）。"""
    es = 6.112 * math.exp(17.67 * t / (t + 243.5))
    pv = es * 0.62198
    pd = (p_hpa * 100.0) - es
    return pd / (287.05 * (t + 273.15)) + pv / (461.5 * (t + 273.15))


def _power_law(z: float, z0: float, v0: float, alpha: float) -> float:
    return v0 * (z / z0) ** alpha


def _log_law(z: float, z0: float, v0: float, z_ref: float) -> float:
    """对数律：z0 为粗糙长度(m)。"""
    if z0 <= 0:
        return float('nan')
    return v0 * math.log(z / z0) / math.log(z_ref / z0)


def _fit_power_law(heights: list[float], speeds: list[float]):
    """幂律拟合，返回 (alpha, r2) 或 (None,None)。"""
    arr = [(h, s) for h, s in zip(heights, speeds)
           if h > 0 and s > 0 and h > 0]
    if len(arr) < 2:
        return None, None
    hs, ss = zip(*arr)
    log_h = np.log(hs)
    log_s = np.log(ss)
    slope, intercept = np.polyfit(log_h, log_s, 1)
    alpha = slope
    pred = intercept + alpha * log_h
    ss_res = ((log_s - pred) ** 2).sum()
    ss_tot = ((np.array(log_s) - np.mean(log_s)) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return alpha, r2


def _fit_log_law(heights: list[float], speeds: list[float]):
    """对数律拟合粗糙长度 z0，返回 (z0, r2)。"""
    arr = [(h, s) for h, s in zip(heights, speeds) if h > 0 and s > 0]
    if len(arr) < 2:
        return None, None
    hs, ss = zip(*arr)
    # v/v_ref = ln(z/z0)/ln(z_ref/z0). 设 x=ln(z), y=v; 对固定参考点用最小二乘
    # 简化：直接拟合 v = a * ln(z) + b, 则 z0 = exp(-b/a)
    log_h = np.log(hs)
    a, b = np.polyfit(log_h, ss, 1)
    if a == 0:
        return None, None
    z0 = math.exp(-b / a)
    pred = a * log_h + b
    ss_res = ((np.array(ss) - pred) ** 2).sum()
    ss_tot = ((np.array(ss) - np.mean(ss)) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return z0, r2


def _weibull_pdf(x: np.ndarray, k: float, c: float) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.zeros_like(x)
    mask = x > 0
    out[mask] = (k / c) * (x[mask] / c) ** (k - 1) * np.exp(
        -(x[mask] / c) ** k)
    return out


def _gumbel_fit(peaks: list[float], method: str = 'simple'):
    """Gumbel 拟合，返回 (u, alpha, v50)。"""
    x = np.array(sorted([v for v in peaks if v > 0 and np.isfinite(v)]))
    n = len(x)
    if n < 2:
        return None, None, None
    # 排序后经验 F
    ranks = np.arange(1, n + 1)
    if method == 'harris1996':
        f = (ranks - 0.44) / (n + 0.12)
    elif method == 'harris1999':
        f = (ranks - 0.40) / (n + 0.20)
    else:  # simple / gringorten
        f = (ranks - 0.5) / n
    y = -np.log(-np.log(f))
    slope, intercept = np.polyfit(x, y, 1)
    alpha = slope
    u = intercept
    if alpha <= 0:
        return None, None, None
    v50 = u - (1.0 / alpha) * np.log(np.log(50 / 49.0))
    return u, alpha, v50


# ------------------------------------------------------------------ 可复用组件
class _ToolDialogBase(QDialog):
    """Tools 对话框统一基类：标题图标化、底部 Help / Close 按钮。"""

    def __init__(self, title: str = 'Tool', parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(720, 520)
        self._main = QVBoxLayout(self)
        self._main.setSpacing(8)
        self._main.setContentsMargins(10, 10, 10, 10)

        # 底部按钮
        self._btn_layout = QHBoxLayout()
        self._btn_layout.addStretch()
        self.btn_help = QPushButton(tr('Help'))
        self.btn_close = QPushButton(tr('Close'))
        self.btn_help.clicked.connect(self._on_help)
        self.btn_close.clicked.connect(self.reject)
        self._btn_layout.addWidget(self.btn_help)
        self._btn_layout.addWidget(self.btn_close)

    def _add_bottom_buttons(self):
        self._main.addLayout(self._btn_layout)

    def _on_help(self):
        QMessageBox.information(
            self, 'Help', f'{self.windowTitle()}\n\nSee Windographer docs.')


class _EditableTable(QTableWidget):
    """可编辑数值表，返回 (col0_values, col1_values, ...)。"""

    def __init__(self, headers: list[str], rows: int = 10, parent=None):
        super().__init__(rows, len(headers), parent)
        self.setHorizontalHeaderLabels(headers)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setVisible(True)
        for r in range(rows):
            for c in range(len(headers)):
                self.setItem(r, c, QTableWidgetItem(''))

    def col_values(self, c: int) -> list[float]:
        vals = []
        for r in range(self.rowCount()):
            it = self.item(r, c)
            try:
                vals.append(float(it.text()) if it and it.text() else float('nan'))
            except ValueError:
                vals.append(float('nan'))
        return vals


# ------------------------------------------------------------------ 1. Standard Atmosphere
class StandardAtmosphereDialog(_ToolDialogBase):
    def __init__(self, parent=None):
        super().__init__('Standard Atmosphere Tool', parent)
        splitter = QSplitter(Qt.Horizontal)

        left = QVBoxLayout()
        lbl = QLabel(
            tr('This window calculates temperature, pressure, and air density '
            'based on the International Standard Atmosphere.'))
        lbl.setWordWrap(True)
        left.addWidget(lbl)

        grp_plot = QGroupBox(tr('Plot'))
        self.rb_temp = QRadioButton(tr('Temperature'))
        self.rb_pres = QRadioButton(tr('Pressure'))
        self.rb_rho = QRadioButton(tr('Air density'))
        self.rb_temp.setChecked(True)
        v = QVBoxLayout(grp_plot)
        v.addWidget(self.rb_temp)
        v.addWidget(self.rb_pres)
        v.addWidget(self.rb_rho)
        left.addWidget(grp_plot)

        grp_calc = QGroupBox(tr('Calculate'))
        form = QFormLayout(grp_calc)
        self.spin_elev = QSpinBox()
        self.spin_elev.setRange(-500, 20000)
        self.spin_elev.setValue(0)
        self.spin_elev.setSuffix(' m')
        self.lbl_temp = QLabel('15.000 C')
        self.lbl_pres = QLabel('101.32 kPa')
        self.lbl_rho = QLabel('1.225 kg/m³')
        form.addRow('Elevation (m)', self.spin_elev)
        form.addRow('Temperature:', self.lbl_temp)
        form.addRow('Pressure:', self.lbl_pres)
        form.addRow('Air density:', self.lbl_rho)
        left.addWidget(grp_calc)
        left.addStretch()

        lw = QWidget()
        lw.setLayout(left)
        splitter.addWidget(lw)

        self.canvas = PlotCanvas('International Standard Atmosphere')
        splitter.addWidget(self.canvas)
        splitter.setSizes([260, 560])

        self._main.addWidget(splitter, 1)
        self._add_bottom_buttons()

        self.rb_temp.toggled.connect(self._update)
        self.rb_pres.toggled.connect(self._update)
        self.rb_rho.toggled.connect(self._update)
        self.spin_elev.valueChanged.connect(self._update)
        self._update()

    def _update(self):
        elev = self.spin_elev.value()
        t, p, rho = _standard_atmosphere(elev)
        self.lbl_temp.setText(f'{t:.3f} C')
        self.lbl_pres.setText(f'{p / 10:.2f} kPa')
        self.lbl_rho.setText(f'{rho:.3f} kg/m³')

        elevs = np.linspace(max(-500, elev - 5000), elev + 5000, 200)
        if self.rb_temp.isChecked():
            ys = [15.0 - 0.0065 * z for z in elevs]
            xl, yl = 'Air Temperature (C)', 'Elevation Above Mean Sea Level (m)'
        elif self.rb_pres.isChecked():
            ys = [1013.25 * (1 - 0.0065 * z / 288.15) ** 5.2551 / 10
                  for z in elevs]
            xl, yl = 'Pressure (kPa)', 'Elevation Above Mean Sea Level (m)'
        else:
            ys = []
            for z in elevs:
                tt, pp, rr = _standard_atmosphere(z)
                ys.append(rr)
            xl, yl = 'Air Density (kg/m³)', 'Elevation Above Mean Sea Level (m)'
        self.canvas.plot_line(ys, elevs, xlabel=xl, ylabel=yl)


# ------------------------------------------------------------------ 2. Air Density
class AirDensityDialog(_ToolDialogBase):
    def __init__(self, parent=None):
        super().__init__('Air Density Tool', parent)
        splitter = QSplitter(Qt.Horizontal)

        left = QVBoxLayout()
        grp = QGroupBox(tr('Plot'))
        self.rb_vs_temp = QRadioButton(tr('density vs. temperature'))
        self.rb_vs_rh = QRadioButton(tr('density vs. RH'))
        self.rb_vs_temp.setChecked(True)
        v = QVBoxLayout(grp)
        v.addWidget(self.rb_vs_temp)
        v.addWidget(self.rb_vs_rh)
        left.addWidget(grp)

        self.spin_temp = QSpinBox()
        self.spin_temp.setRange(-60, 60)
        self.spin_temp.setValue(15)
        self.spin_temp.setSuffix(' °C')
        left.addWidget(QLabel('Temperature (°C)'))
        left.addWidget(self.spin_temp)
        left.addStretch()

        lw = QWidget()
        lw.setLayout(left)
        splitter.addWidget(lw)

        self.canvas = PlotCanvas('Air Density vs. Temperature')
        splitter.addWidget(self.canvas)
        splitter.setSizes([220, 600])

        self._main.addWidget(splitter, 1)
        self._add_bottom_buttons()

        self.rb_vs_temp.toggled.connect(self._update)
        self.rb_vs_rh.toggled.connect(self._update)
        self.spin_temp.valueChanged.connect(self._update)
        self._update()

    def _update(self):
        t0 = self.spin_temp.value()
        if self.rb_vs_temp.isChecked():
            temps = np.linspace(-40, 40, 160)
            dry = [_air_density_dry(t) for t in temps]
            sat = [_air_density_saturated(t) for t in temps]
            diff = [s - d for s, d in zip(sat, dry)]
            self.canvas.plot_lines([
                ('Dry', temps, dry),
                ('Saturated', temps, sat),
                ('Density Difference', temps, diff),
            ], xlabel='Temperature (C)', ylabel='Air Density (kg/m³)',
                ymin=1.0)
        else:
            rh = np.linspace(0, 100, 100)
            rho = []
            for r in rh:
                es = 6.112 * math.exp(17.67 * t0 / (t0 + 243.5))
                e = es * r / 100.0
                p = 1013.25 * 100.0
                rho_d = (p - e) / (287.05 * (t0 + 273.15))
                rho_v = e / (461.5 * (t0 + 273.15))
                rho.append(rho_d + rho_v)
            self.canvas.plot_line(rh, rho, xlabel='Relative Humidity (%)',
                                  ylabel='Air Density (kg/m³)')


# ------------------------------------------------------------------ 3. Synthesize Wind Speed Data
class SynthesizeWindDataDialog(_ToolDialogBase):
    def __init__(self, parent=None):
        super().__init__('Synthesize Wind Speed Data Tool', parent)
        self._main.setSpacing(6)
        top = QHBoxLayout()

        self.cmb_level = QComboBox()
        self.cmb_level.addItems(['Simple', 'Intermediate', 'Advanced'])
        top.addWidget(QLabel(tr('Select level of detail')))
        top.addWidget(self.cmb_level)
        top.addSpacing(30)

        self.spin_timestep = QSpinBox()
        self.spin_timestep.setRange(1, 1440)
        self.spin_timestep.setValue(10)
        self.spin_timestep.setSuffix(' min')
        top.addWidget(QLabel(tr('Desired time step (minutes)')))
        top.addWidget(self.spin_timestep)
        top.addStretch()
        self._main.addLayout(top)

        mid = QHBoxLayout()
        self.tbl_months = QTableWidget(12, 2)
        self.tbl_months.setHorizontalHeaderLabels(
            ['Month', 'Wind Speed\n(m/s)'])
        self.tbl_months.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        for r, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']):
            self.tbl_months.setItem(r, 0, QTableWidgetItem(m))
            self.tbl_months.setItem(r, 1, QTableWidgetItem('5.000'))
            self.tbl_months.item(r, 0).setFlags(Qt.ItemIsEnabled)
        mid.addWidget(self.tbl_months)

        right = QVBoxLayout()
        form = QFormLayout()
        self.spin_k = QDoubleSpinBox()
        self.spin_k.setRange(0.1, 10)
        self.spin_k.setValue(2.0)
        self.spin_k.setDecimals(2)
        self.spin_auto = QDoubleSpinBox()
        self.spin_auto.setRange(-1, 1)
        self.spin_auto.setValue(0.85)
        self.spin_auto.setDecimals(2)
        self.spin_diurnal = QDoubleSpinBox()
        self.spin_diurnal.setRange(0, 1)
        self.spin_diurnal.setValue(0.25)
        self.spin_diurnal.setDecimals(2)
        self.spin_peak = QSpinBox()
        self.spin_peak.setRange(0, 23)
        self.spin_peak.setValue(15)
        form.addRow('Weibull k', self.spin_k)
        form.addRow('1-hr autocorrelation coefficient', self.spin_auto)
        form.addRow('Diurnal pattern strength', self.spin_diurnal)
        form.addRow('Hour of peak wind speed', self.spin_peak)
        right.addLayout(form)
        right.addStretch()
        mid.addLayout(right)
        self._main.addLayout(mid)

        btn_syn = QPushButton(tr('Synthesize Data...'))
        btn_syn.clicked.connect(self._synthesize)
        btn_export = QPushButton(tr('Export Data to Text File...'))
        btn_export.clicked.connect(self._export)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_syn)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_export)
        self._main.addLayout(btn_layout)

        self.canvas = PlotCanvas('Synthetic Wind Speed')
        self._main.addWidget(self.canvas, 1)
        self._add_bottom_buttons()

        self._synthesized: pd.Series | None = None
        self._synthesize()

    def _synthesize(self):
        ts_min = self.spin_timestep.value()
        n_steps = int(365 * 24 * 60 / ts_min)
        idx = pd.date_range('2001-01-01', periods=n_steps,
                            freq=f'{ts_min}min')
        months = idx.month
        base = np.array(
            [float(self.tbl_months.item(r, 1).text() or 5) for r in range(12)])
        base_speed = base[months - 1]
        k = self.spin_k.value()
        # 用 Weibull 形状生成随机风速
        u = np.random.rand(n_steps)
        speed = base_speed * (-np.log(1 - u)) ** (1.0 / k)
        # 日变化调制
        strength = self.spin_diurnal.value()
        peak = self.spin_peak.value()
        hour_angle = 2 * math.pi * (idx.hour + idx.minute / 60.0 - peak) / 24
        speed *= (1 + strength * np.cos(hour_angle))
        # 简单自相关平滑
        if self.spin_auto.value() > 0 and n_steps > 1:
            a = self.spin_auto.value()
            out = np.empty_like(speed)
            out[0] = speed[0]
            for i in range(1, n_steps):
                out[i] = a * out[i - 1] + (1 - a) * speed[i]
            speed = out
        self._synthesized = pd.Series(speed, index=idx)
        self.canvas.plot_line(idx, speed, xlabel='Time',
                              ylabel='Wind Speed (m/s)')

    def _export(self):
        if self._synthesized is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Synthetic Data', 'synthetic_wind.txt',
            'Text files (*.txt *.csv)')
        if not path:
            return
        self._synthesized.to_csv(path, header=['Wind Speed (m/s)'])


# ------------------------------------------------------------------ 4. Wind Shear Tool
class WindShearToolDialog(_ToolDialogBase):
    def __init__(self, parent=None):
        super().__init__('Wind Shear Tool', parent)
        self._main.addWidget(QLabel(
            tr('Enter the mean wind speed at two or more heights above the ground. '
            'Windographer will calculate the best-fit wind shear profile.')))

        splitter = QSplitter(Qt.Horizontal)
        left = QVBoxLayout()

        top = QHBoxLayout()
        top.addWidget(QLabel(tr('Height units')))
        self.cmb_units = QComboBox()
        self.cmb_units.addItems(['m', 'ft'])
        top.addWidget(self.cmb_units)
        top.addStretch()
        left.addLayout(top)

        self.tbl = _EditableTable(['Height\n(m)', 'Wind Speed\n(m/s)'], 20)
        left.addWidget(self.tbl)

        self.lbl_power = QLabel('Power law exponent: <n/a>')
        self.lbl_z0 = QLabel('Surface roughness: <n/a>')
        left.addWidget(self.lbl_power)
        left.addWidget(self.lbl_z0)

        est = QHBoxLayout()
        est.addWidget(QLabel(tr('Height (m)')))
        self.spin_est = QSpinBox()
        self.spin_est.setRange(1, 500)
        self.spin_est.setValue(80)
        est.addWidget(self.spin_est)
        self.lbl_est_power = QLabel('Calculated using power law: <n/a>')
        self.lbl_est_log = QLabel('Calculated using log law: <n/a>')
        left.addLayout(est)
        left.addWidget(self.lbl_est_power)
        left.addWidget(self.lbl_est_log)
        left.addStretch()

        lw = QWidget()
        lw.setLayout(left)
        splitter.addWidget(lw)

        self.canvas = PlotCanvas('Vertical Wind Shear Profile')
        splitter.addWidget(self.canvas)
        splitter.setSizes([320, 500])

        self._main.addWidget(splitter, 1)
        self._add_bottom_buttons()

        self.tbl.itemChanged.connect(self._update)
        self.spin_est.valueChanged.connect(self._update)
        self.cmb_units.currentIndexChanged.connect(self._update)
        self._update()

    def _update(self):
        hs = self.tbl.col_values(0)
        ss = self.tbl.col_values(1)
        factor = 0.3048 if self.cmb_units.currentText() == 'ft' else 1.0
        hs = [h * factor for h in hs]
        pairs = [(h, s) for h, s in zip(hs, ss)
                 if h > 0 and s > 0 and math.isfinite(h) and math.isfinite(s)]
        if len(pairs) >= 2:
            hh, vv = zip(*pairs)
            alpha, _ = _fit_power_law(hh, vv)
            z0, _ = _fit_log_law(hh, vv)
            self.lbl_power.setText(
                f'Power law exponent: {alpha:.4f}' if alpha is not None
                else 'Power law exponent: <n/a>')
            self.lbl_z0.setText(
                f'Surface roughness: {z0:.4f} m' if z0 is not None
                else 'urface roughness: <n/a>')
            z_max = max(hh) * 1.5
            z_line = np.linspace(min(hh) * 0.5, z_max, 100)
            if alpha is not None:
                v_power = [_power_law(z, hh[0], vv[0], alpha) for z in z_line]
            else:
                v_power = []
            if z0 is not None:
                v_log = [_log_law(z, z0, vv[0], hh[0]) for z in z_line]
            else:
                v_log = []
            series = [('Observed', hh, vv)]
            if v_power:
                series.append(('Power law', z_line, v_power))
            if v_log:
                series.append(('Log law', z_line, v_log))
            self.canvas.plot_lines(
                series, xlabel='Wind Speed (m/s)',
                ylabel='Height Above Ground (m)')

            z_est = self.spin_est.value() * factor
            if alpha is not None:
                self.lbl_est_power.setText(
                    f'Calculated using power law: '
                    f'{_power_law(z_est, hh[0], vv[0], alpha):.3f} m/s')
            else:
                self.lbl_est_power.setText(
                    'Calculated using power law: <n/a>')
            if z0 is not None:
                self.lbl_est_log.setText(
                    f'Calculated using log law: '
                    f'{_log_law(z_est, z0, vv[0], hh[0]):.3f} m/s')
            else:
                self.lbl_est_log.setText('Calculated using log law: <n/a>')
        else:
            self.lbl_power.setText('Power law exponent: <n/a>')
            self.lbl_z0.setText('Surface roughness: <n/a>')
            self.lbl_est_power.setText(
                'Calculated using power law: <n/a>')
            self.lbl_est_log.setText('Calculated using log law: <n/a>')
            self.canvas.clear()


# ------------------------------------------------------------------ 5. Extreme Wind Tool
class ExtremeWindToolDialog(_ToolDialogBase):
    def __init__(self, parent=None):
        super().__init__('Extreme Wind Tool', parent)
        splitter = QSplitter(Qt.Horizontal)

        left = QVBoxLayout()
        top = QHBoxLayout()
        self.rb_annual = QRadioButton(tr('annual maxima'))
        self.rb_cover = QRadioButton(tr('maxima covering'))
        self.rb_annual.setChecked(True)
        self.spin_years = QSpinBox()
        self.spin_years.setRange(1, 200)
        self.spin_years.setValue(1)
        self.spin_years.setSuffix(' yrs')
        top.addWidget(QLabel(tr('Values in table are:')))
        top.addWidget(self.rb_annual)
        top.addWidget(self.rb_cover)
        top.addWidget(self.spin_years)
        top.addStretch()
        left.addLayout(top)

        units = QHBoxLayout()
        units.addWidget(QLabel(tr('Units')))
        self.cmb_units = QComboBox()
        self.cmb_units.addItems(['m/s', 'mph', 'km/h', 'knots'])
        units.addWidget(self.cmb_units)
        left.addLayout(units)

        grp_pre = QGroupBox(tr('Preconditioning'))
        self.bg_pre = QButtonGroup(self)
        self.rb_pre_none = QRadioButton(tr('None'))
        self.rb_pre_sq = QRadioButton(tr('Square values'))
        self.rb_pre_exp = QRadioButton(tr('Custom exponent'))
        self.bg_pre.addButton(self.rb_pre_none)
        self.bg_pre.addButton(self.rb_pre_sq)
        self.bg_pre.addButton(self.rb_pre_exp)
        self.spin_exp = QDoubleSpinBox()
        self.spin_exp.setValue(1.0)
        self.spin_exp.setDecimals(1)
        self.rb_pre_none.setChecked(True)
        v = QVBoxLayout(grp_pre)
        v.addWidget(self.rb_pre_none)
        v.addWidget(self.rb_pre_sq)
        h = QHBoxLayout()
        h.addWidget(self.rb_pre_exp)
        h.addWidget(self.spin_exp)
        v.addLayout(h)
        left.addWidget(grp_pre)

        grp_gum = QGroupBox(tr('Gumbel fit method'))
        self.bg_gum = QButtonGroup(self)
        self.rb_gum_simple = QRadioButton(tr('Simple'))
        self.rb_gum_h96 = QRadioButton('Harris 1996')
        self.rb_gum_h99 = QRadioButton('Harris 1999')
        self.bg_gum.addButton(self.rb_gum_simple)
        self.bg_gum.addButton(self.rb_gum_h96)
        self.bg_gum.addButton(self.rb_gum_h99)
        self.rb_gum_simple.setChecked(True)
        v = QVBoxLayout(grp_gum)
        v.addWidget(self.rb_gum_simple)
        v.addWidget(self.rb_gum_h96)
        v.addWidget(self.rb_gum_h99)
        left.addWidget(grp_gum)

        self.tbl_peaks = _EditableTable(['Peak Value\n(m/s)'], 30)
        left.addWidget(self.tbl_peaks)

        lw = QWidget()
        lw.setLayout(left)
        splitter.addWidget(lw)

        right = QVBoxLayout()
        top_r = QHBoxLayout()
        top_r.addWidget(QLabel(tr('Display')))
        self.cmb_display = QComboBox()
        self.cmb_display.addItems(
            ['Linearized CDF', 'PDF', 'CDF', 'PDE', 'Return period'])
        top_r.addWidget(self.cmb_display)
        top_r.addStretch()
        right.addLayout(top_r)

        self.canvas = PlotCanvas('Linearized Cumulative Distribution Function')
        right.addWidget(self.canvas, 1)

        self.lbl_warn = QLabel(
            '⚠ Enter two or more values in the table to the left.')
        right.addWidget(self.lbl_warn)

        self.tbl_result = QTableWidget(4, 2)
        self.tbl_result.setHorizontalHeaderLabels(['Quantity', 'Value'])
        self.tbl_result.setVerticalHeaderLabels(
            ['50-yr extreme value', 'Gumbel scale parameter',
             'Gumbel mode parameter', ''])
        self.tbl_result.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        right.addWidget(self.tbl_result)

        rw = QWidget()
        rw.setLayout(right)
        splitter.addWidget(rw)
        splitter.setSizes([360, 460])

        self._main.addWidget(splitter, 1)
        self._add_bottom_buttons()

        for w in (self.rb_annual, self.rb_cover,
                  self.rb_pre_none, self.rb_pre_sq, self.rb_pre_exp,
                  self.rb_gum_simple, self.rb_gum_h96, self.rb_gum_h99):
            w.toggled.connect(self._update)
        self.spin_years.valueChanged.connect(self._update)
        self.cmb_units.currentIndexChanged.connect(self._update)
        self.spin_exp.valueChanged.connect(self._update)
        self.cmb_display.currentIndexChanged.connect(self._update)
        self.tbl_peaks.itemChanged.connect(self._update)
        self._update()

    def _update(self):
        vals = [v for v in self.tbl_peaks.col_values(0)
                if math.isfinite(v) and v > 0]
        if len(vals) < 2:
            self.lbl_warn.setVisible(True)
            self.canvas.clear()
            return
        self.lbl_warn.setVisible(False)
        method = 'simple'
        if self.rb_gum_h96.isChecked():
            method = 'harris1996'
        elif self.rb_gum_h99.isChecked():
            method = 'harris1999'

        # 预处理
        if self.rb_pre_sq.isChecked():
            x = [v ** 2 for v in vals]
        elif self.rb_pre_exp.isChecked():
            p = self.spin_exp.value()
            x = [v ** p for v in vals]
        else:
            x = vals

        u, alpha, v50 = _gumbel_fit(x, method)
        if u is None:
            self.canvas.clear()
            return

        display = self.cmb_display.currentText()
        x_sorted = np.array(sorted(x))
        if display == 'Linearized CDF':
            y = -np.log(-np.log(np.linspace(0.01, 0.99, len(x_sorted))))
            self.canvas.plot_scatter(x_sorted, y,
                                     xlabel='Annual Extreme Wind Speed '
                                            '(U*, m/s)',
                                     ylabel='Reduced Variable, '
                                            '-ln(-ln(F(U*)))')
            x_line = np.linspace(min(x_sorted), max(x_sorted), 50)
            y_line = u + alpha * x_line
            self.canvas.plot_lines([
                ('Fit', x_line, y_line)],
                xlabel='Annual Extreme Wind Speed (U*, m/s)',
                ylabel='Reduced Variable, -ln(-ln(F(U*)))')
        elif display == 'PDF':
            xs = np.linspace(0, max(x_sorted) * 1.5, 100)
            # 用核密度近似
            kde = np.zeros_like(xs)
            bw = max(np.std(x_sorted, ddof=1) * 1.06 * len(x_sorted) ** -0.2,
                     0.1)
            for v in x_sorted:
                kde += np.exp(-0.5 * ((xs - v) / bw) ** 2)
            kde /= (len(x_sorted) * bw * math.sqrt(2 * math.pi))
            self.canvas.plot_line(xs, kde, xlabel='Annual Extreme Wind Speed',
                                  ylabel='Probability Density')
        elif display == 'CDF':
            xs = np.linspace(0, max(x_sorted) * 1.5, 100)
            cdf = np.array([np.mean(x_sorted <= v) for v in xs])
            self.canvas.plot_line(xs, cdf, xlabel='Annual Extreme Wind Speed',
                                  ylabel='Cumulative Distribution')
        elif display == 'PDE':
            xs = np.linspace(0, max(x_sorted) * 1.5, 100)
            pde = 1 - np.exp(-np.exp(-(alpha * (xs - v50))))
            self.canvas.plot_line(xs, pde,
                                  xlabel='Annual Extreme Wind Speed',
                                  ylabel='Probability of Exceedance')
        else:  # Return period
            rp = np.linspace(2, 100, 100)
            # Gumbel: F(V)=exp(-exp(-alpha*(V-u)))
            # 给定 return period T, F=1-1/T
            vals_rp = u - (1 / alpha) * np.log(-np.log(1 - 1 / rp))
            self.canvas.plot_line(rp, vals_rp, xlabel='Return Period (years)',
                                  ylabel='Extreme Wind Speed')

        self.tbl_result.setItem(0, 1, QTableWidgetItem(f'{v50:.3f}'))
        self.tbl_result.setItem(1, 1, QTableWidgetItem(f'{alpha:.5f}'))
        self.tbl_result.setItem(2, 1, QTableWidgetItem(f'{u:.5f}'))


# ------------------------------------------------------------------ 6. Wind Turbine Output Estimator
class WindTurbineOutputEstimatorDialog(_ToolDialogBase):
    def __init__(self, parent=None):
        super().__init__('Wind Turbine Output Estimator Tool', parent)
        splitter = QSplitter(Qt.Horizontal)

        left = QVBoxLayout()
        grp_res = QGroupBox(tr('Wind resource data'))
        self.bg_res = QButtonGroup(self)
        self.rb_annual = QRadioButton(tr('Annual mean'))
        self.rb_monthly = QRadioButton(tr('Monthly means'))
        self.rb_hist = QRadioButton(tr('Frequency histogram'))
        self.bg_res.addButton(self.rb_annual)
        self.bg_res.addButton(self.rb_monthly)
        self.bg_res.addButton(self.rb_hist)
        self.rb_annual.setChecked(True)
        v = QVBoxLayout(grp_res)
        v.addWidget(self.rb_annual)
        v.addWidget(self.rb_monthly)
        v.addWidget(self.rb_hist)
        left.addWidget(grp_res)

        # 共享参数（所有模式都显示）
        shared = QFormLayout()
        self.spin_anem_h = QSpinBox()
        self.spin_anem_h.setRange(1, 300)
        self.spin_anem_h.setValue(50)
        self.spin_alpha = QDoubleSpinBox()
        self.spin_alpha.setRange(0, 1)
        self.spin_alpha.setValue(0.14)
        self.spin_alpha.setDecimals(3)
        shared.addRow('Anemometer height (m)', self.spin_anem_h)
        shared.addRow('Power law exponent', self.spin_alpha)
        left.addLayout(shared)

        self.stack = QTabWidget()
        self.stack.setTabPosition(QTabWidget.West)
        self.stack.tabBar().setVisible(False)

        # Annual mean page
        page_annual = QWidget()
        fa = QFormLayout(page_annual)
        self.spin_mean_spd = QDoubleSpinBox()
        self.spin_mean_spd.setRange(0, 50)
        self.spin_mean_spd.setValue(6)
        self.spin_mean_spd.setDecimals(2)
        self.spin_weibull_k = QDoubleSpinBox()
        self.spin_weibull_k.setRange(0.1, 10)
        self.spin_weibull_k.setValue(2)
        self.spin_rho_res = QDoubleSpinBox()
        self.spin_rho_res.setRange(0.5, 2)
        self.spin_rho_res.setValue(1.225)
        self.spin_rho_res.setDecimals(3)
        fa.addRow('Mean wind speed (m/s)', self.spin_mean_spd)
        fa.addRow('Weibull k', self.spin_weibull_k)
        fa.addRow('Air density (kg/m3)', self.spin_rho_res)
        self.stack.addTab(page_annual, tr('annual'))

        # Monthly means page
        page_monthly = QWidget()
        fm = QVBoxLayout(page_monthly)
        self.tbl_months = QTableWidget(12, 4)
        self.tbl_months.setHorizontalHeaderLabels(
            ['Month', 'Speed (m/s)', 'Weibull k', 'Air Density (kg/m3)'])
        for r, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']):
            self.tbl_months.setItem(r, 0, QTableWidgetItem(m))
            self.tbl_months.setItem(r, 1, QTableWidgetItem('6.00'))
            self.tbl_months.setItem(r, 2, QTableWidgetItem('2.00'))
            self.tbl_months.setItem(r, 3, QTableWidgetItem('1.225'))
            self.tbl_months.item(r, 0).setFlags(Qt.ItemIsEnabled)
        self.tbl_months.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        fm.addWidget(self.tbl_months)
        self.stack.addTab(page_monthly, tr('monthly'))

        # Histogram page
        page_hist = QWidget()
        fh = QFormLayout(page_hist)
        self.spin_rho_hist = QDoubleSpinBox()
        self.spin_rho_hist.setRange(0.5, 2)
        self.spin_rho_hist.setValue(1.225)
        self.spin_rho_hist.setDecimals(3)
        self.spin_bin = QDoubleSpinBox()
        self.spin_bin.setRange(0.1, 5)
        self.spin_bin.setValue(1)
        self.spin_bin.setDecimals(1)
        self.tbl_hist = QTableWidget(20, 2)
        self.tbl_hist.setHorizontalHeaderLabels(
            ['Speed Range (m/s)', 'Frequency (%)'])
        for r in range(20):
            self.tbl_hist.setItem(
                r, 0, QTableWidgetItem(f'{r}-{r + 1}'))
            self.tbl_hist.setItem(r, 1, QTableWidgetItem('0.000'))
            self.tbl_hist.item(r, 0).setFlags(Qt.ItemIsEnabled)
        self.tbl_hist.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        fh.addRow('Air density (kg/m3)', self.spin_rho_hist)
        fh.addRow('Histogram bin size (m/s)', self.spin_bin)
        fh.addRow(self.tbl_hist)
        self.stack.addTab(page_hist, tr('hist'))

        left.addWidget(self.stack)

        self.cmb_group = QComboBox()
        self.cmb_group.addItem('<All turbines>')
        self.cmb_turbine = QComboBox()
        self._load_turbines()
        left.addWidget(QLabel(tr('Turbine group')))
        left.addWidget(self.cmb_group)
        left.addWidget(QLabel(tr('Wind turbine')))
        left.addWidget(self.cmb_turbine)

        grp_prop = QGroupBox(tr('Properties'))
        form_prop = QFormLayout(grp_prop)
        self.lbl_manuf = QLabel('')
        self.lbl_web = QLabel('')
        self.lbl_diam = QLabel('')
        self.lbl_rated = QLabel('')
        self.lbl_reg = QLabel('')
        form_prop.addRow('Manufacturer:', self.lbl_manuf)
        form_prop.addRow('Website:', self.lbl_web)
        form_prop.addRow('Rotor diameter:', self.lbl_diam)
        form_prop.addRow('Rated power:', self.lbl_rated)
        form_prop.addRow('Power regulation:', self.lbl_reg)
        left.addWidget(grp_prop)

        grp_loss = QGroupBox(tr('Losses'))
        form_loss = QFormLayout(grp_loss)
        self.spin_loss = QDoubleSpinBox()
        self.spin_loss.setRange(0, 100)
        self.spin_loss.setValue(17.7011)
        self.spin_loss.setDecimals(4)
        form_loss.addRow('Overall loss factor (%)', self.spin_loss)
        left.addWidget(grp_loss)

        btn_calc = QPushButton(tr('Calculate Output'))
        btn_calc.clicked.connect(self._calculate)
        left.addWidget(btn_calc)
        left.addStretch()

        lw = QWidget()
        lw.setLayout(left)
        splitter.addWidget(lw)

        right = QVBoxLayout()
        hub = QHBoxLayout()
        self.rb_hub_default = QRadioButton(tr('Default'))
        self.rb_hub_other = QRadioButton(tr('Other'))
        self.rb_hub_default.setChecked(True)
        self.spin_hub = QSpinBox()
        self.spin_hub.setRange(1, 300)
        self.spin_hub.setValue(70)
        hub.addWidget(QLabel(tr('Hub height')))
        hub.addWidget(self.rb_hub_default)
        hub.addWidget(self.rb_hub_other)
        hub.addWidget(self.spin_hub)
        hub.addStretch()
        right.addLayout(hub)

        self.canvas = PlotCanvas('Power Output')
        right.addWidget(self.canvas, 1)

        self.tbl_result = QTableWidget(3, 4)
        self.tbl_result.setHorizontalHeaderLabels(
            ['Variable', 'Before Losses', 'After Losses', 'Units'])
        self.tbl_result.setVerticalHeaderLabels(
            ['Mean power output', 'Annual energy output', 'Capacity factor'])
        self.tbl_result.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        right.addWidget(self.tbl_result)

        self.tbl_height = QTableWidget(2, 2)
        self.tbl_height.setHorizontalHeaderLabels(['Height', 'Mean Speed (m/s)'])
        self.tbl_height.setVerticalHeaderLabels(
            ['Anemometer height', 'Hub height'])
        self.tbl_height.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        right.addWidget(self.tbl_height)

        rw = QWidget()
        rw.setLayout(right)
        splitter.addWidget(rw)
        splitter.setSizes([420, 400])

        self._main.addWidget(splitter, 1)
        self._add_bottom_buttons()

        for rb in (self.rb_annual, self.rb_monthly, self.rb_hist):
            rb.toggled.connect(self._change_mode)
        self.cmb_turbine.currentIndexChanged.connect(self._show_turbine)
        self._change_mode()
        self._show_turbine()

    def _load_turbines(self):
        self._turbines = _load_turbines()
        self.cmb_turbine.clear()
        for t in self._turbines:
            self.cmb_turbine.addItem(t.get('model', 'Unknown'), t)
        if not self._turbines:
            self.cmb_turbine.addItem(tr('No turbines loaded'))

    def _change_mode(self):
        if self.rb_annual.isChecked():
            self.stack.setCurrentIndex(0)
        elif self.rb_monthly.isChecked():
            self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(2)

    def _show_turbine(self):
        t = self.cmb_turbine.currentData()
        if not t:
            return
        self.lbl_manuf.setText(t.get('manufacturer', ''))
        self.lbl_web.setText(t.get('website', ''))
        self.lbl_diam.setText(str(t.get('rotor_diameter_m', '')))
        self.lbl_rated.setText(str(t.get('rated_power_kw', '')))
        self.lbl_reg.setText(t.get('regulation', ''))
        if t.get('hub_height_m'):
            self.spin_hub.setValue(int(t['hub_height_m']))

    def _power_curve(self, t: dict):
        """返回 (speeds, powers)。"""
        curve = t.get('power_curve', [])
        if curve:
            return [c[0] for c in curve], [c[1] for c in curve]
        # 简易近似：使用源 Excel 公式
        rated = float(t.get('rated_power_kw', 2000))
        diam = float(t.get('rotor_diameter_m', 80))
        cut_in = float(t.get('cut_in_speed_ms', 3))
        cut_out = float(t.get('cut_out_speed_ms', 20))
        rated_v = float(t.get('rated_wind_speed_ms', 12))
        rho = 1.225
        speeds = np.linspace(0, 25, 250)
        powers = []
        a = math.pi * (diam / 2) ** 2
        for v in speeds:
            if v < cut_in or v > cut_out:
                powers.append(0)
            elif v < rated_v:
                p = 0.5 * rho * a * v ** 3 / 1000
                powers.append(min(p, rated))
            else:
                powers.append(rated)
        return speeds.tolist(), powers

    def _calculate(self):
        t = self.cmb_turbine.currentData()
        if not t:
            return
        speeds, powers = self._power_curve(t)
        self.canvas.plot_line(speeds, powers, xlabel='Wind Speed (m/s)',
                              ylabel='Power Output', ymin=0)

        anem_h = self.spin_anem_h.value()
        hub_h = self.spin_hub.value()
        alpha = self.spin_alpha.value()
        ratio = (hub_h / anem_h) ** alpha if anem_h > 0 else 1.0

        if self.rb_annual.isChecked():
            mean_spd = self.spin_mean_spd.value()
            k = self.spin_weibull_k.value()
            c = mean_spd / math.gamma(1 + 1 / k)
            rho = self.spin_rho_res.value()
            spd_bins = np.arange(0, 30.5, 0.5)
            pdf = _weibull_pdf(spd_bins, k, c)
            p_curve = np.interp(spd_bins, speeds, powers)
            aep = (pdf * p_curve * 8760 * 0.5).sum() / 1000  # MWh
            mean_p = (pdf * p_curve * 0.5).sum()
        else:
            aep = 0
            mean_p = 0

        loss = self.spin_loss.value() / 100.0
        aep_after = aep * (1 - loss)
        mean_p_after = mean_p * (1 - loss)
        rated = float(t.get('rated_power_kw', 1))
        cf = aep_after * 1000 / (rated * 8760) * 100 if rated else 0

        self.tbl_result.setItem(0, 1, QTableWidgetItem(f'{mean_p:.1f}'))
        self.tbl_result.setItem(0, 2, QTableWidgetItem(f'{mean_p_after:.1f}'))
        self.tbl_result.setItem(0, 3, QTableWidgetItem('kW'))
        self.tbl_result.setItem(1, 1, QTableWidgetItem(f'{aep:.0f}'))
        self.tbl_result.setItem(1, 2, QTableWidgetItem(f'{aep_after:.0f}'))
        self.tbl_result.setItem(1, 3, QTableWidgetItem('kWh/yr'))
        self.tbl_result.setItem(2, 1, QTableWidgetItem(''))
        self.tbl_result.setItem(2, 2, QTableWidgetItem(f'{cf:.1f}'))
        self.tbl_result.setItem(2, 3, QTableWidgetItem('%'))

        self.tbl_height.setItem(0, 0, QTableWidgetItem(f'{anem_h}'))
        self.tbl_height.setItem(1, 0, QTableWidgetItem(f'{hub_h}'))
        self.tbl_height.setItem(0, 1, QTableWidgetItem(''))
        self.tbl_height.setItem(1, 1, QTableWidgetItem(''))


# ------------------------------------------------------------------ 7. Wind Turbine Library
class WindTurbineLibraryDialog(_ToolDialogBase):
    def __init__(self, parent=None):
        super().__init__('Wind Turbine Library', parent)
        splitter = QSplitter(Qt.Horizontal)

        left = QVBoxLayout()
        left.addWidget(QLabel(tr('Turbines')))
        toolbar = QHBoxLayout()
        self.btn_new = QPushButton(tr('New...'))
        self.btn_edit = QPushButton(tr('Edit...'))
        self.btn_delete = QPushButton(tr('Delete...'))
        self.btn_import = QPushButton(tr('Import'))
        self.btn_compare = QPushButton(tr('Compare Selected Turbines...'))
        toolbar.addWidget(self.btn_new)
        toolbar.addWidget(self.btn_edit)
        toolbar.addWidget(self.btn_delete)
        toolbar.addWidget(self.btn_import)
        toolbar.addStretch()
        left.addLayout(toolbar)
        left.addWidget(self.btn_compare)

        self.tbl_turbines = QTableWidget(0, 6)
        self.tbl_turbines.setHorizontalHeaderLabels(
            ['Name', 'Manufacturer', 'Rotor Diameter (m)',
             'Rated Power (kW)', 'Source', 'Folder'])
        self.tbl_turbines.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.tbl_turbines.setSelectionBehavior(
            QAbstractItemView.SelectRows)
        left.addWidget(self.tbl_turbines)

        lw = QWidget()
        lw.setLayout(left)
        splitter.addWidget(lw)

        right = QVBoxLayout()
        right.addWidget(QLabel(tr('Turbine Groups')))
        tb2 = QHBoxLayout()
        self.btn_new_group = QPushButton(tr('New Group...'))
        self.btn_rename_group = QPushButton(tr('Rename Group...'))
        self.btn_delete_group = QPushButton(tr('Delete Group...'))
        tb2.addWidget(self.btn_new_group)
        tb2.addWidget(self.btn_rename_group)
        tb2.addWidget(self.btn_delete_group)
        right.addLayout(tb2)

        right.addWidget(QLabel(tr('Group name')))
        self.cmb_group = QComboBox()
        right.addWidget(self.cmb_group)
        self.lst_group = QListWidget()
        right.addWidget(self.lst_group)

        rw = QWidget()
        rw.setLayout(right)
        splitter.addWidget(rw)
        splitter.setSizes([600, 260])

        self._main.addWidget(splitter, 1)
        self._add_bottom_buttons()

        self._load_turbines()

    def _load_turbines(self):
        turbines = _load_turbines()
        self.tbl_turbines.setRowCount(len(turbines))
        for r, t in enumerate(turbines):
            self.tbl_turbines.setItem(
                r, 0, QTableWidgetItem(t.get('model', '')))
            self.tbl_turbines.setItem(
                r, 1, QTableWidgetItem(t.get('manufacturer', '')))
            self.tbl_turbines.setItem(
                r, 2, QTableWidgetItem(str(t.get('rotor_diameter_m', ''))))
            self.tbl_turbines.setItem(
                r, 3, QTableWidgetItem(str(t.get('rated_power_kw', ''))))
            self.tbl_turbines.setItem(r, 4, QTableWidgetItem('User'))
            self.tbl_turbines.setItem(r, 5, QTableWidgetItem(''))


# ------------------------------------------------------------------ 8. Options
class OptionsDialog(_ToolDialogBase):
    def __init__(self, parent=None):
        super().__init__('Options', parent)
        self.tabs = QTabWidget()
        self._main.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_general(), tr('General'))
        self.tabs.addTab(self._build_colors(), tr('Colors'))
        self.tabs.addTab(self._build_graphs(), tr('Graphs'))
        self.tabs.addTab(self._build_formatting(), tr('Formatting'))
        self.tabs.addTab(self._build_averaging(), tr('Averaging'))
        self.tabs.addTab(self._build_folders(), tr('Folders'))
        self.tabs.addTab(self._build_wind_rose(), tr('Wind Rose'))
        self.tabs.addTab(self._build_advanced(), tr('Advanced'))

        btn_ok = QPushButton('OK')
        btn_ok.clicked.connect(self._on_ok)
        btn_cancel = QPushButton(tr('Cancel'))
        btn_cancel.clicked.connect(self.reject)
        self._btn_layout.insertWidget(1, btn_cancel)
        self._btn_layout.insertWidget(2, btn_ok)
        self._add_bottom_buttons()

    def _build_general(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)

        grp = QGroupBox(tr('Basic settings'))
        form = QFormLayout(grp)
        self.chk_open_recent = QCheckBox(
            tr('Open most recently used document when Windographer starts'))
        self.chk_open_recent.setChecked(
            settings.get('options_open_recent', False))
        self.edit_user = QLineEdit(settings.get('options_username', ''))
        self.chk_db_user = QCheckBox(
            tr('Use the database username when connected to a database'))
        self.chk_db_user.setChecked(
            settings.get('options_db_username', True))
        form.addRow(self.chk_open_recent)
        h = QHBoxLayout()
        h.addWidget(QLabel(tr('User name')))
        h.addWidget(self.edit_user)
        h.addWidget(QLabel(
            '(to identify your changes in the Document History window)'))
        h.addStretch()
        form.addRow(h)
        form.addRow(self.chk_db_user)
        v.addWidget(grp)

        grp2 = QGroupBox(tr('Preferred wind shear'))
        h2 = QHBoxLayout(grp2)
        self.rb_shear_log = QRadioButton(tr('Logarithmic law'))
        self.rb_shear_power = QRadioButton(tr('Power law'))
        pref = settings.get('preferred_wind_shear', 'power')
        self.rb_shear_power.setChecked(pref == 'power')
        self.rb_shear_log.setChecked(pref == 'log')
        h2.addWidget(self.rb_shear_log)
        h2.addWidget(self.rb_shear_power)
        h2.addStretch()
        v.addWidget(grp2)

        grp3 = QGroupBox(tr('Preferred edition of IEC standard 61400-1 for'))
        h3 = QHBoxLayout(grp3)
        self.rb_iec_2 = QRadioButton('2nd edition (1999)')
        self.rb_iec_3 = QRadioButton('3rd edition (2005)')
        self.rb_iec_4 = QRadioButton('4th edition (2019)')
        self.rb_iec_41 = QRadioButton('4.1 edition (AMD1:2025)')
        iec = settings.get('preferred_iec', '3rd')
        self.rb_iec_2.setChecked(iec == '2nd')
        self.rb_iec_3.setChecked(iec == '3rd')
        self.rb_iec_4.setChecked(iec == '4th')
        self.rb_iec_41.setChecked(iec == '4.1')
        h3.addWidget(self.rb_iec_2)
        h3.addWidget(self.rb_iec_3)
        h3.addWidget(self.rb_iec_4)
        h3.addWidget(self.rb_iec_41)
        h3.addStretch()
        v.addWidget(grp3)

        grp4 = QGroupBox(tr('Sensor colocation'))
        h4 = QHBoxLayout(grp4)
        h4.addWidget(QLabel(tr('Consider sensors colocated if within')))
        self.spin_coloc = QSpinBox()
        self.spin_coloc.setRange(0, 100)
        self.spin_coloc.setValue(settings.get('colocation_m', 1))
        self.spin_coloc.setSuffix(' vertical metres of each other')
        h4.addWidget(self.spin_coloc)
        h4.addStretch()
        v.addWidget(grp4)

        v.addStretch()
        return w

    def _build_colors(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(tr('Default color scheme')))
        self.tbl_colors = QTableWidget(11, 3)
        self.tbl_colors.setHorizontalHeaderLabels(
            ['Data column type', 'Highest', 'Lowest'])
        rows = [
            'Wind speed - mean', 'Wind speed - std. dev.',
            'Wind speed - max.', 'Wind speed - min.',
            'Turbulence intensity', 'Wind power density',
            'Vertical wind speed', 'Wind direction',
            'Wind direction - std. dev.', 'Quality factor', 'Temperature']
        default_high = [
            '#12457f', '#d35400', '#7b1f4b', '#7a6a2d',
            '#1e8449', '#0000ff', '#311b92', '#1b5e20',
            '#004d40', '#9e7d27', '#c62828']
        default_low = [
            '#9ec6f0', '#f5bca9', '#f4a4bf', '#e6e0c5',
            '#82e0aa', '#9fa8da', '#b39ddb', '#a5d6a7',
            '#b2dfdb', '#e6ce9e', '#ef9a9a']
        for r, name in enumerate(rows):
            self.tbl_colors.setItem(r, 0, QTableWidgetItem(name))
            hi = settings.get(f'color_high_{r}', default_high[r])
            lo = settings.get(f'color_low_{r}', default_low[r])
            self.tbl_colors.setItem(r, 1, QTableWidgetItem(hi))
            self.tbl_colors.setItem(r, 2, QTableWidgetItem(lo))
        self.tbl_colors.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        v.addWidget(self.tbl_colors)
        v.addStretch()
        return w

    def _build_graphs(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)

        h1 = QHBoxLayout()
        h1.addWidget(QLabel(tr('Default number of direction sectors in wind rose')))
        self.cmb_sectors = QComboBox()
        self.cmb_sectors.addItems(
            ['4', '8', '12', '16', '18', '24', '36', '48', '72', '120',
             '180', '360'])
        self.cmb_sectors.setCurrentText(
            str(settings.get('default_wind_rose_sectors', 16)))
        h1.addWidget(self.cmb_sectors)
        h1.addStretch()
        v.addLayout(h1)

        h2 = QHBoxLayout()
        h2.addWidget(QLabel(
            tr('Maximum height of vertical wind shear profile graph')))
        self.spin_shear_height = QSpinBox()
        self.spin_shear_height.setRange(10, 500)
        self.spin_shear_height.setValue(
            settings.get('max_shear_profile_height', 100))
        h2.addWidget(self.spin_shear_height)
        h2.addStretch()
        v.addLayout(h2)

        self.chk_watermark = QCheckBox(
            tr('Hide watermarks in graphs (Professional and Enterprise editions only)'))
        self.chk_watermark.setChecked(
            settings.get('hide_watermarks', False))
        v.addWidget(self.chk_watermark)
        v.addStretch()
        return w

    def _build_formatting(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(tr('Desired decimal places')))
        self.tbl_decimals = QTableWidget(8, 2)
        self.tbl_decimals.setHorizontalHeaderLabels(['Data Type', 'Decimals'])
        rows = [
            'Wind speed', 'Max. wind speed', 'Vertical wind speed',
            'Wind direction', 'Temperature', 'Air pressure',
            'Turbulence intensity', 'Relative humidity']
        defaults = [3, 3, 3, 1, 1, 1, 2, 1]
        for r, name in enumerate(rows):
            self.tbl_decimals.setItem(r, 0, QTableWidgetItem(name))
            self.tbl_decimals.setItem(
                r, 1, QTableWidgetItem(
                    str(settings.get(f'decimals_{name}', defaults[r]))))
        self.tbl_decimals.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        v.addWidget(self.tbl_decimals)
        v.addStretch()
        return w

    def _build_averaging(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            tr('Average from sub-hourly to daily (or longer) time steps in two '
            'stages, first to hourly time steps.')))

        grp = QGroupBox(tr('Minimum data coverage rate'))
        form = QFormLayout(grp)
        labels = ['Three hours or less', 'One day or less',
                  'One week or less', 'One month or less',
                  'Greater than one month']
        keys = ['coverage_3h', 'coverage_1d', 'coverage_1w',
                'coverage_1m', 'coverage_gt1m']
        defaults = [50, 75, 80, 80, 90]
        self.spin_coverage = []
        for label, key, default in zip(labels, keys, defaults):
            s = QSpinBox()
            s.setRange(0, 100)
            s.setSuffix(' %')
            s.setValue(settings.get(key, default))
            self.spin_coverage.append((key, s))
            form.addRow(f'When averaging to time steps {label}', s)
        v.addWidget(grp)

        grp2 = QGroupBox(tr('Averaging of standard deviation data'))
        h = QHBoxLayout(grp2)
        self.bg_sd = QButtonGroup(self)
        self.rb_sd_mean = QRadioButton(tr('Calculate simple mean'))
        self.rb_sd_rms = QRadioButton(tr('Calculate root mean square'))
        self.rb_sd_both = QRadioButton(tr('Consider both means and standard deviation'))
        self.bg_sd.addButton(self.rb_sd_mean)
        self.bg_sd.addButton(self.rb_sd_rms)
        self.bg_sd.addButton(self.rb_sd_both)
        sd_method = settings.get('sd_averaging_method', 'rms')
        self.rb_sd_rms.setChecked(sd_method == 'rms')
        self.rb_sd_mean.setChecked(sd_method == 'mean')
        self.rb_sd_both.setChecked(sd_method == 'both')
        h.addWidget(self.rb_sd_mean)
        h.addWidget(self.rb_sd_rms)
        h.addWidget(self.rb_sd_both)
        h.addStretch()
        v.addWidget(grp2)
        v.addStretch()
        return w

    def _build_folders(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        grp = QGroupBox(tr('Folders Windographer uses to store:'))
        form = QFormLayout(grp)
        self.edit_flags = QLineEdit(
            settings.get('folder_favorite_flags',
                         r'C:\ProgramData\Windographer\Favorites\Flags'))
        self.edit_rules = QLineEdit(
            settings.get('folder_favorite_rules',
                         r'C:\ProgramData\Windographer\Favorites\FlagRules'))
        self.edit_turbines = QLineEdit(
            settings.get('folder_user_turbines',
                         r'C:\ProgramData\Windographer\WindTurbines\User'))
        form.addRow('Favorite flags', self.edit_flags)
        form.addRow('Favorite flag rules', self.edit_rules)
        form.addRow('User-created wind turbines', self.edit_turbines)
        form.addRow(QLabel(
            '(If you change this folder, move all your WTP files too so '
            'Windographer can still find them.)'))
        v.addWidget(grp)

        grp2 = QGroupBox(tr('Other software'))
        form2 = QFormLayout(grp2)
        self.edit_symdr = QLineEdit(
            settings.get('symphonie_data_retriever',
                         r'C:\NRG\SymDR\SDR.exe'))
        self.chk_ignore_site = QCheckBox(
            tr('Ignore site files when importing RWD files'))
        self.chk_ignore_site.setChecked(
            settings.get('ignore_rwd_site_files', True))
        self.edit_sympro = QLineEdit(
            settings.get('symphoniepro_desktop',
                         'C:\\Program Files (x86)\\Renewable NRG Systems\\'
                         'SymPRO Desktop\\SymPRODesktop.exe'))
        form2.addRow('Symphonie Data Retriever', self.edit_symdr)
        form2.addRow(self.chk_ignore_site)
        form2.addRow('SymphoniePRO Desktop', self.edit_sympro)
        v.addWidget(grp2)
        v.addStretch()
        return w

    def _build_advanced(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        h1 = QHBoxLayout()
        h1.addWidget(QLabel(
            tr('Default width of sector to flag for tower shading')))
        self.spin_tower_sector = QSpinBox()
        self.spin_tower_sector.setRange(1, 90)
        self.spin_tower_sector.setValue(
            settings.get('tower_shading_sector_width', 30))
        h1.addWidget(self.spin_tower_sector)
        h1.addStretch()
        v.addLayout(h1)

        self.chk_momm = QCheckBox(
            tr('Calculate fractional monthly completeness factors in MoMM calculation'))
        self.chk_momm.setChecked(
            settings.get('momm_fractional_completeness', True))
        v.addWidget(self.chk_momm)

        self.chk_latlon = QCheckBox(
            tr('Include latitude, longitude, and elevation when saving template files'))
        self.chk_latlon.setChecked(
            settings.get('save_latlon_elevation', False))
        v.addWidget(self.chk_latlon)

        self.chk_flag_manual = QCheckBox(
            tr('Set initial state of Flag Manually window from the Time Series tab'))
        self.chk_flag_manual.setChecked(
            settings.get('flag_manual_from_timeseries', False))
        v.addWidget(self.chk_flag_manual)

        self.chk_two_step = QCheckBox(
            tr('Save windog files in two steps to ensure success before overwriting '
            'original file'))
        self.chk_two_step.setChecked(
            settings.get('save_two_step', False))
        v.addWidget(self.chk_two_step)

        self.chk_subfolders = QCheckBox(
            tr('Search subfolders when opening or appending a folder'))
        self.chk_subfolders.setChecked(
            settings.get('search_subfolders', True))
        v.addWidget(self.chk_subfolders)

        grp = QGroupBox(tr('Default append overwrite settings'))
        form = QFormLayout(grp)
        self.bg_overwrite = QButtonGroup(self)
        self.rb_ow_never = QRadioButton(tr('Never'))
        self.rb_ow_missing = QRadioButton(
            tr('Only in time steps for which existing data are missing'))
        self.rb_ow_except = QRadioButton(
            tr('In all time steps except those in which new data are missing'))
        self.rb_ow_always = QRadioButton(tr('Always'))
        self.bg_overwrite.addButton(self.rb_ow_never)
        self.bg_overwrite.addButton(self.rb_ow_missing)
        self.bg_overwrite.addButton(self.rb_ow_except)
        self.bg_overwrite.addButton(self.rb_ow_always)
        ow = settings.get('append_overwrite', 'except')
        self.rb_ow_never.setChecked(ow == 'never')
        self.rb_ow_missing.setChecked(ow == 'missing')
        self.rb_ow_except.setChecked(ow == 'except')
        self.rb_ow_always.setChecked(ow == 'always')
        form.addRow(QLabel(
            tr('When new data overlaps existing data, overwrite existing data:')))
        form.addRow(self.rb_ow_never)
        form.addRow(self.rb_ow_missing)
        form.addRow(self.rb_ow_except)
        form.addRow(self.rb_ow_always)
        v.addWidget(grp)

        grp2 = QGroupBox(tr('Database connection settings'))
        form2 = QFormLayout(grp2)
        self.spin_db_timeout = QSpinBox()
        self.spin_db_timeout.setRange(1, 600)
        self.spin_db_timeout.setValue(
            settings.get('database_command_timeout', 30))
        form2.addRow('Database command timeout (seconds)', self.spin_db_timeout)
        v.addWidget(grp2)
        v.addStretch()
        return w

    def _build_wind_rose(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)

        defaults = settings.get_wind_rose_defaults()

        grp = QGroupBox(tr('Default wind rose settings'))
        form = QFormLayout(grp)

        self.spin_wr_sectors = QSpinBox()
        self.spin_wr_sectors.setRange(4, 72)
        self.spin_wr_sectors.setSingleStep(4)
        self.spin_wr_sectors.setValue(defaults.get('sectors', 16))

        self.cmb_wr_display = QComboBox()
        for key, label in [
            ('frequency', 'Frequency'),
            ('occurrences', 'Occurrences'),
            ('mean', 'Mean'),
            ('max', 'Maximum'),
            ('std_dev', 'Std. dev.'),
            ('total_energy', 'Total energy'),
            ('scatter_plot', 'Scatter plot'),
        ]:
            self.cmb_wr_display.addItem(label, key)
        idx = self.cmb_wr_display.findData(defaults.get('display', 'frequency'))
        self.cmb_wr_display.setCurrentIndex(max(0, idx))

        self.cmb_wr_versus = QComboBox()
        for key, label in [
            ('direction', 'Direction'),
            ('direction_and_month', 'Direction and month'),
            ('direction_and_hour', 'Direction and hour'),
            ('direction_and_bin', 'Direction and bin'),
        ]:
            self.cmb_wr_versus.addItem(label, key)
        idx = self.cmb_wr_versus.findData(defaults.get('versus', 'direction'))
        self.cmb_wr_versus.setCurrentIndex(max(0, idx))

        self.spin_wr_inner = QSpinBox()
        self.spin_wr_inner.setRange(0, 100)
        self.spin_wr_inner.setSuffix('%')
        self.spin_wr_inner.setValue(int(defaults.get('inner_circle_pct', 0.0)))

        self.spin_wr_fill = QSpinBox()
        self.spin_wr_fill.setRange(10, 100)
        self.spin_wr_fill.setSuffix('%')
        self.spin_wr_fill.setValue(int(defaults.get('fill_factor', 0.85) * 100))

        form.addRow('Default sectors', self.spin_wr_sectors)
        form.addRow('Default display', self.cmb_wr_display)
        form.addRow('Default versus', self.cmb_wr_versus)
        form.addRow('Inner circle radius', self.spin_wr_inner)
        form.addRow('Fill factor', self.spin_wr_fill)
        v.addWidget(grp)
        v.addStretch()
        return w

    def _on_ok(self):
        settings.set('options_open_recent', self.chk_open_recent.isChecked())
        settings.set('options_username', self.edit_user.text())
        settings.set('options_db_username', self.chk_db_user.isChecked())
        settings.set('preferred_wind_shear',
                     'power' if self.rb_shear_power.isChecked() else 'log')
        if self.rb_iec_41.isChecked():
            iec_val = '4.1'
        elif self.rb_iec_4.isChecked():
            iec_val = '4th'
        elif self.rb_iec_2.isChecked():
            iec_val = '2nd'
        else:
            iec_val = '3rd'
        settings.set('preferred_iec', iec_val)
        settings.set('colocation_m', self.spin_coloc.value())
        settings.set('default_wind_rose_sectors',
                     int(self.cmb_sectors.currentText()))
        # 新版风玫瑰默认设置（与 Wind Rose 属性对话框共用）
        wr_defaults = settings.get_wind_rose_defaults()
        wr_defaults.update({
            'sectors': self.spin_wr_sectors.value(),
            'display': self.cmb_wr_display.currentData(),
            'versus': self.cmb_wr_versus.currentData(),
            'inner_circle_pct': self.spin_wr_inner.value(),
            'fill_factor': self.spin_wr_fill.value() / 100.0,
        })
        settings.set_wind_rose_defaults(wr_defaults)
        settings.set('max_shear_profile_height',
                     self.spin_shear_height.value())
        settings.set('hide_watermarks', self.chk_watermark.isChecked())
        settings.set('tower_shading_sector_width',
                     self.spin_tower_sector.value())
        settings.set('momm_fractional_completeness',
                     self.chk_momm.isChecked())
        settings.set('save_latlon_elevation', self.chk_latlon.isChecked())
        settings.set('flag_manual_from_timeseries',
                     self.chk_flag_manual.isChecked())
        settings.set('save_two_step', self.chk_two_step.isChecked())
        settings.set('search_subfolders', self.chk_subfolders.isChecked())
        settings.set('database_command_timeout',
                     self.spin_db_timeout.value())
        settings.set('folder_favorite_flags', self.edit_flags.text())
        settings.set('folder_favorite_rules', self.edit_rules.text())
        settings.set('folder_user_turbines', self.edit_turbines.text())
        settings.set('symphonie_data_retriever', self.edit_symdr.text())
        settings.set('ignore_rwd_site_files',
                     self.chk_ignore_site.isChecked())
        settings.set('symphoniepro_desktop', self.edit_sympro.text())

        for key, s in self.spin_coverage:
            settings.set(key, s.value())

        if self.rb_sd_mean.isChecked():
            settings.set('sd_averaging_method', 'mean')
        elif self.rb_sd_both.isChecked():
            settings.set('sd_averaging_method', 'both')
        else:
            settings.set('sd_averaging_method', 'rms')

        if self.rb_ow_never.isChecked():
            settings.set('append_overwrite', 'never')
        elif self.rb_ow_missing.isChecked():
            settings.set('append_overwrite', 'missing')
        elif self.rb_ow_always.isChecked():
            settings.set('append_overwrite', 'always')
        else:
            settings.set('append_overwrite', 'except')

        rows = ['Wind speed', 'Max. wind speed', 'Vertical wind speed',
                'Wind direction', 'Temperature', 'Air pressure',
                'Turbulence intensity', 'Relative humidity']
        for r, name in enumerate(rows):
            it = self.tbl_decimals.item(r, 1)
            try:
                settings.set(f'decimals_{name}', int(it.text()))
            except Exception:
                pass

        for r in range(self.tbl_colors.rowCount()):
            hi = self.tbl_colors.item(r, 1)
            lo = self.tbl_colors.item(r, 2)
            if hi:
                settings.set(f'color_high_{r}', hi.text())
            if lo:
                settings.set(f'color_low_{r}', lo.text())

        self.accept()
