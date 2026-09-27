"""advanced.py：见 _common 与 shim。"""
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

from ._common import (_numeric_cols, _speed_cols, _dir_cols, _to_num, _height_of, _CheckList, _AnalysisDialogBase)

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
