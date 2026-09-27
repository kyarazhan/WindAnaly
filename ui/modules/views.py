"""WindAnaly 独立视图窗口（数据覆盖 / 文档历史 / DMap / 箱线图 / CDF）。

每个窗口都是独立 QMainWindow，读取 AnalysisApp 的活动数据集实时绘制；
数据更新后点击各窗口内「刷新」即可（或重新打开）。全部使用 PlotCanvas
自绘（零新增依赖），与 WindAnaly 主界面视觉一致。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget, QHeaderView, QDialog, QMessageBox)

from ui.modules.plot import PlotCanvas
from ui.modules.analysis_tabs import display_name
from core.i18n import tr


def _numeric_columns(ds) -> list[str]:
    """返回数据集中的数值型通道名（用于箱线图/CDF 候选）。"""
    if ds is None or ds.df.empty:
        return []
    return [c for c in ds.df.columns
            if pd.api.types.is_numeric_dtype(ds.df[c])]


# ----------------------------------------------------------------------
# 1) 数据覆盖（Data Coverage）
# ----------------------------------------------------------------------
class DataCoverageWindow(QMainWindow):
    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self.setWindowTitle(tr('数据覆盖'))
        self.canvas = PlotCanvas(tr('通道数据有效率'))
        ctrl = QLabel(tr('色块越绿表示该通道在对应时段的有效率越高；灰色为该时段全缺测。'))
        ctrl.setWordWrap(True)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(ctrl)
        lay.addWidget(self.canvas, 1)
        self.setCentralWidget(w)
        self.resize(940, 580)
        self.refresh()

    def refresh(self):
        ds = self._app.project.active_dataset
        if ds is None or ds.df.empty:
            self.canvas.clear(tr('请先载入数据集'))
            return
        cols = list(ds.df.columns)
        t0, t1 = ds.df.index[0], ds.df.index[-1]
        months = (t1.year - t0.year) * 12 + (t1.month - t0.month) + 1
        freq = 'M' if months <= 60 else 'Y'
        periods = pd.period_range(t0, t1, freq=freq)
        per = ds.df.index.to_period(freq)
        mat = np.full((len(cols), len(periods)), np.nan)
        for ri, col in enumerate(cols):
            cov = ds.df[col].groupby(per).apply(
                lambda x: x.notna().mean()).reindex(periods)
            mat[ri] = cov.values.astype(float)
        ylabels = [display_name(c) for c in cols]
        xlabels = [str(p) for p in periods]
        self.canvas.plot_heatmap(
            mat, xlabels, ylabels, xlabel=tr('时段'), ylabel=tr('通道'),
            unit='有效率', vmin=0.0, vmax=1.0, cmap='coverage')


# ----------------------------------------------------------------------
# 2) 文档历史（Document History）
# ----------------------------------------------------------------------
class DocumentHistoryWindow(QMainWindow):
    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self.setWindowTitle(tr('文档历史'))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr('时间'), tr('操作'), tr('对象'), tr('详情')])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hint = QLabel(tr('数据的载入、保存、剔除与关闭等操作会记录在此，随项目文件持久化。'))
        hint.setWordWrap(True)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)
        self.setCentralWidget(w)
        self.resize(780, 500)
        self.refresh()

    def refresh(self):
        hist = self._app.project.history or []
        self.table.setRowCount(len(hist))
        for r, rec in enumerate(reversed(hist)):
            self.table.setItem(r, 0, QTableWidgetItem(str(rec.get('time', ''))))
            self.table.setItem(r, 1, QTableWidgetItem(str(rec.get('action', ''))))
            self.table.setItem(r, 2, QTableWidgetItem(str(rec.get('target', ''))))
            self.table.setItem(r, 3, QTableWidgetItem(str(rec.get('detail', ''))))


# ----------------------------------------------------------------------
# 3) DMap（日期 × 小时热力图）
# ----------------------------------------------------------------------
class DMapWindow(QMainWindow):
    """DMap：日期 × 小时热力图，对齐原版布局。

    Data column 下拉列出全部通道（含 TI/WPD 计算列），
    Change Color Scheme 按钮循环切换色带。"""

    _COLOR_SCHEMES = ['wind', 'coverage', 'blue']
    _SCHEME_LABELS = ['Wind', 'Coverage', 'Blue']

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self._scheme_idx = 0
        self.setWindowTitle(tr('DMap'))
        self.canvas = PlotCanvas('')

        # ---- Data column ----
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(QLabel(tr('Data column')))
        self.sel = QComboBox()
        self.sel.setMinimumWidth(280)
        bar.addWidget(self.sel, 1)

        # ---- Change Color Scheme ----
        self.btn_scheme = QPushButton(tr('Change Color Scheme'))
        self.btn_scheme.clicked.connect(self._cycle_scheme)
        bar.addWidget(self.btn_scheme)
        bar.addStretch(1)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(bar)
        lay.addWidget(self.canvas, 1)

        # ---- 底部 Help / Close ----
        btns = QHBoxLayout()
        btn_help = QPushButton(tr('Help'))
        btn_close = QPushButton(tr('Close'))
        btn_help.clicked.connect(self._show_help)
        btn_close.clicked.connect(self.close)
        btns.addWidget(btn_help)
        btns.addStretch(1)
        btns.addWidget(btn_close)
        lay.addLayout(btns)
        self.setCentralWidget(w)
        self.resize(940, 620)
        self._populate()
        self.refresh()

    def _cycle_scheme(self):
        self._scheme_idx = (self._scheme_idx + 1) % len(self._COLOR_SCHEMES)
        self.refresh()

    def _show_help(self):
        QMessageBox.information(
            self, 'DMap',
            'DMap displays a heat map of the selected data column,\n'
            'with Date on the Y axis and Hour of Day on the X axis.\n\n'
            'Use the Data column drop-down to choose a channel.\n'
            'Click Change Color Scheme to cycle through color schemes.')

    def _populate(self):
        ds = self._app.project.active_dataset
        self.sel.clear()
        if ds is None:
            return
        # 列出全部通道 + TI/WPD 计算列
        names = [n for n in ds.df.columns]
        for n, ch in ds.channels.items():
            if n not in names and n in ds.df.columns:
                names.append(n)
        # TI/WPD 计算列
        from core.diurnal import ti_series, wpd_series
        for n, ch in ds.channels.items():
            if ch.kind == 'speed' and getattr(ch, 'role', 'Avg') == 'Avg':
                ti_name = n + ' TI'
                wpd_name = n + ' WPD'
                if ti_name not in names:
                    names.append(ti_name)
                if wpd_name not in names:
                    names.append(wpd_name)
        for c in names:
            self.sel.addItem(c, c)

    def refresh(self):
        ds = self._app.project.active_dataset
        if ds is None or ds.df.empty:
            self.canvas.clear('Please load a data set first')
            return
        col = self.sel.currentData()
        if not col:
            self.canvas.clear('No channel selected')
            return

        # TI/WPD 计算列按需物化
        work = ds.df
        if col.endswith(' TI') or col.endswith(' WPD'):
            work = ds.df.copy()
            base = col[:-3] if col.endswith(' TI') else col[:-4]
            if base in ds.df.columns:
                if col.endswith(' TI'):
                    work[col] = work[base] / work[base].abs().groupby(
                        work[base].index).transform('max').clip(lower=0.1) * 100
                else:
                    rho = 1.225
                    work[col] = 0.5 * rho * work[base] ** 3

        if col not in work.columns:
            self.canvas.clear('Channel not found')
            return
        s = work[col].dropna()
        if s.empty:
            self.canvas.clear('No data for this channel')
            return

        n_dates = s.index.normalize().nunique()
        if n_dates > 800:
            g = s.groupby([s.index.to_period('M'), s.index.hour]).mean().unstack(1)
            ylabels = [str(p) for p in g.index]
        else:
            g = s.groupby([s.index.normalize(), s.index.hour]).mean().unstack(1)
            ylabels = [str(d.date()) for d in g.index]
        g = g.reindex(columns=range(0, 24), fill_value=np.nan)
        mat = g.values.astype(float)
        xlabels = [str(h) for h in g.columns]
        unit = ''
        ch = ds.channels.get(col)
        if ch and ch.units:
            unit = ch.units
        cmap = self._COLOR_SCHEMES[self._scheme_idx]
        self.canvas.plot_heatmap(
            mat, xlabels, ylabels, xlabel='Hour of Day', ylabel='Date',
            unit=unit, cmap=cmap)


# ----------------------------------------------------------------------
# 4) 箱线图（Monthly Statistics）
# ----------------------------------------------------------------------
class BoxplotWindow(QMainWindow):
    """Boxplot：Monthly Statistics 箱线图 + Filter by。"""

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self.setWindowTitle(tr('Boxplot'))
        self.canvas = PlotCanvas('Monthly Statistics')

        # ---- Data column ----
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(QLabel(tr('Data column')))
        self.sel = QComboBox()
        self.sel.setMinimumWidth(280)
        self.sel.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.sel, 1)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(bar)
        lay.addWidget(self.canvas, 1)

        # ---- 底部 Help / Close ----
        btns = QHBoxLayout()
        btn_help = QPushButton(tr('Help'))
        btn_close = QPushButton(tr('Close'))
        btn_help.clicked.connect(self._show_help)
        btn_close.clicked.connect(self.close)
        btns.addWidget(btn_help)
        btns.addStretch(1)
        btns.addWidget(btn_close)
        lay.addLayout(btns)
        self.setCentralWidget(w)
        self.resize(940, 620)
        self._populate()
        self.refresh()

    def _show_help(self):
        QMessageBox.information(
            self, 'Boxplot',
            'Boxplot displays monthly statistics (min, q1, median, q3, max)\n'
            'for the selected data column.\n\n'
            'Use the Data column drop-down to choose a channel.')

    def _populate(self):
        ds = self._app.project.active_dataset
        self.sel.clear()
        if ds is None:
            return
        names = [n for n in ds.df.columns]
        for n, ch in ds.channels.items():
            if n not in names and n in ds.df.columns:
                names.append(n)
        for c in names:
            self.sel.addItem(c, c)
        active = self._app.project.selection.get('speed')
        if active and active in names:
            self.sel.setCurrentText(active)

    def refresh(self):
        ds = self._app.project.active_dataset
        if ds is None or ds.df.empty:
            self.canvas.clear('Please load a data set first')
            return
        col = self.sel.currentData()
        if not col or col not in ds.df.columns:
            self.canvas.clear('No channel selected')
            return
        s = pd.to_numeric(ds.df[col], errors='coerce').dropna()
        if s.empty:
            self.canvas.clear('No valid data for this channel')
            return
        month = s.index.month
        groups = []
        for m in range(1, 13):
            vals = s[month == m].values
            if len(vals) >= 2:
                q1, med, q3 = np.percentile(vals, [25, 50, 75])
                groups.append((f'{m}月', {
                    'min': float(np.min(vals)), 'q1': float(q1),
                    'med': float(med), 'q3': float(q3),
                    'max': float(np.max(vals)),
                    'mean': float(np.mean(vals)), 'n': int(len(vals)),
                }))
        if not groups:
            self.canvas.clear('Insufficient data')
            return
        unit = ''
        ch = ds.channels.get(col)
        if ch and ch.units:
            unit = ch.units
        self.canvas.plot_box(
            groups, xlabel='Month',
            ylabel=f'{col} ({unit})' if unit else col)


# ----------------------------------------------------------------------
# 5) 累积分布函数（CDF，多通道）
# ----------------------------------------------------------------------
class CDFWindow(QMainWindow):
    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self.setWindowTitle(tr('累积分布函数'))
        self.canvas = PlotCanvas(tr('累积分布函数 (CDF)'))
        self.listw = QListWidget()
        self.listw.itemChanged.connect(lambda _: self.refresh())
        bar = QHBoxLayout()
        bar.addWidget(QLabel(tr('通道（勾选绘制）：')), 0)
        bar.addWidget(self.listw, 1)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(bar)
        lay.addWidget(self.canvas, 1)
        self.setCentralWidget(w)
        self.resize(940, 560)
        self._populate()
        self.refresh()

    def _populate(self):
        ds = self._app.project.active_dataset
        self.listw.clear()
        nums = _numeric_columns(ds)
        active = self._app.project.selection.get('speed')
        for c in nums:
            item = QListWidgetItem(display_name(c))
            item.setData(Qt.UserRole, c)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if c == active else Qt.Unchecked)
            self.listw.addItem(item)

    def refresh(self):
        ds = self._app.project.active_dataset
        if ds is None or ds.df.empty:
            self.canvas.clear(tr('请先载入数据集'))
            return
        series = []
        for i in range(self.listw.count()):
            item = self.listw.item(i)
            if item.checkState() != Qt.Checked:
                continue
            col = item.data(Qt.UserRole)
            if not col or col not in ds.df.columns:
                continue
            s = ds.valid_series(col).dropna()
            if len(s) < 2:
                continue
            xs = np.sort(s.values.astype(float))
            ys = np.arange(1, len(xs) + 1) / len(xs)
            series.append((display_name(col), xs, ys))
        if not series:
            self.canvas.clear(tr('请勾选至少一条有效通道'))
            return
        self.canvas.plot_lines(series, xlabel=tr('数值'), ylabel=tr('累积概率'))


# ----------------------------------------------------------------------
# 链接台账数据库对话框
# ----------------------------------------------------------------------
class LinkLibraryDialog(QDialog):
    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self.setWindowTitle(tr('链接台账数据库'))
        self.resize(580, 440)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            tr('从测风塔台账数据库中选择数据集链接到本分析。')))
        self.listw = QListWidget()
        self._load_items()
        lay.addWidget(self.listw, 1)

        btn_link = QPushButton(tr('链接所选数据集'))
        btn_cancel = QPushButton(tr('取消'))
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(btn_link)
        h.addWidget(btn_cancel)
        lay.addLayout(h)

        btn_link.clicked.connect(self._link)
        btn_cancel.clicked.connect(self.reject)

    def _load_items(self):
        from core.library import Library
        lib = Library()
        rows = lib.list_datasets()
        if not rows:
            self.listw.addItem(tr('（台账库中暂无数据集）'))
            return
        for r in rows:
            rec = lib.get_station(int(r['serial_no'])) or {}
            name = (f"{r['id']} · 序列号 {r['serial_no']} · "
                    f"{r['t_start']}~{r['t_end']} · {rec.get('location', '')}")
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, r['id'])
            self.listw.addItem(item)

    def _link(self):
        item = self.listw.currentItem()
        if item is None:
            return
        ds_id = item.data(Qt.UserRole)
        if ds_id is None:
            QMessageBox.information(self, tr('提示'), tr('请选择有效的数据集'))
            return
        ok, msg = self._app._load_spec(f'library:{ds_id}')
        self._app.statusBar().showMessage(msg)
        if ok:
            self._app._refresh_tabs()
            self._app.project.log('链接台账库', f'数据集 {ds_id}', 'WindAnaly')
        self.accept()
