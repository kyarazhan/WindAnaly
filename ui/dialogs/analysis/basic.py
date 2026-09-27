"""basic.py：见 _common 与 shim。"""
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

from ._common import (_numeric_cols, _speed_cols, _dir_cols, _temp_cols, _height_of, _power_law_fit, _log_law_fit, _weibull_mle, _weibull_pdf, _CheckList, _AnalysisDialogBase)

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
