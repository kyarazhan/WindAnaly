"""energy.py：见 _common 与 shim。"""
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

from ._common import (_speed_cols, _to_num, _height_of, _AnalysisDialogBase)

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
