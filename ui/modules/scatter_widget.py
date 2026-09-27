"""散点图控件：左侧 Windographer 风格控制面板 + 散点图。

对齐原版 Scatter Plot 标签页：
- Plot（y 轴）/ versus（x 轴）下拉（含派生 TI/WPD 计算列）+ 交换按钮；
- Color code by：flag（按标记着色）/ data column（按数据列分档着色 +
  右侧色带图例）；
- Filter by：Flag、Date、Date range、Direction sector、Data column
  Min/Max（与 Diurnal/Histogram 同一套过滤）；
- Results：Number of / Mean x value / Mean y value / Show line of best fit。

配置经 Project.plot_settings['scatter'] 随项目文件持久化。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractSpinBox, QButtonGroup, QCheckBox,
                               QComboBox, QDateEdit, QDoubleSpinBox,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QRadioButton, QScrollArea, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget)

from core.dataset import KIND_DIR, KIND_SPEED, Dataset
from core.diurnal import ti_series, wpd_series
from core.project import Project
from ui.modules.diurnal_widget import (_SECTOR_ALL, _TI_SUFFIX,
                                               _WPD_SUFFIX)
from ui.modules.plot import PlotCanvas
from ui.modules.wind_rose_widget import _SilentComboBox
from core.i18n import tr

_UNFLAGGED_COLOR = '#58595b'   # Color code by flag 时未标记点颜色（深灰）
# 数据列分档着色 10 档（自低到高，jet 风）
_JET10 = ['#443983', '#2c7be5', '#17a2b8', '#27ae60', '#a0d05a',
          '#f5e353', '#f6a632', '#ef7621', '#e33d3d', '#b1182b']
_COLOR_BANDS = 10


def _swap_icon() -> QToolButton:
    """Plot/versus 交换按钮（上下双箭头样式）。"""
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QFont
    px = QPixmap(16, 16)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor('#4a5460'), 1.5))
    f = QFont('Microsoft YaHei', 8, QFont.Bold)
    p.setFont(f)
    p.drawText(0, 0, 16, 9, Qt.AlignCenter, '⇅')
    p.end()
    btn = QToolButton()
    btn.setIcon(QIcon(px))
    btn.setFixedSize(26, 26)
    btn.setToolTip('Swap Plot / versus')
    return btn


class ScatterWidget(QWidget):
    """散点图控件：左侧控制面板 + 右侧散点图。"""

    CFG_KEY = 'scatter'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Project | None = None

        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(4)

        # ---- 左侧控制面板 ----
        self._panel = QWidget(self)
        self._panel.setMinimumWidth(270)
        self._panel.setMaximumWidth(356)
        panel_v = QVBoxLayout(self._panel)
        panel_v.setSpacing(6)
        panel_v.setContentsMargins(4, 4, 4, 4)

        # ---- Plot / versus / Color code by（三行下拉框对齐同一列）----
        self.cmb_y = _SilentComboBox()
        self.cmb_x = _SilentComboBox()
        self.chk_color = QCheckBox(tr('Color code by'))
        self.rb_flag = QRadioButton(tr('flag'))
        self.rb_col = QRadioButton(tr('data column'))
        self.rb_flag.setChecked(True)
        self.btn_swap = _swap_icon()
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setColumnStretch(1, 1)
        lbl_plot = QLabel(tr('Plot'))
        lbl_plot.setFixedWidth(44)
        grid.addWidget(lbl_plot, 0, 0)
        grid.addWidget(self.cmb_y, 0, 1)
        lbl_vs = QLabel(tr('versus'))
        lbl_vs.setFixedWidth(44)
        grid.addWidget(lbl_vs, 1, 0)
        grid.addWidget(self.cmb_x, 1, 1)
        # 交换按钮：竖跨 Plot/versus 两行、右侧居中（原版位置）
        grid.addWidget(self.btn_swap, 0, 2, 2, 1)
        panel_v.addLayout(grid)

        # ---- Color code by ----
        cc_row = QHBoxLayout()
        cc_row.setSpacing(6)
        cc_row.addWidget(self.chk_color)
        cc_row.addWidget(self.rb_flag)
        cc_row.addWidget(self.rb_col)
        cc_row.addStretch(1)
        panel_v.addLayout(cc_row)
        self._color_group = QButtonGroup(self)
        self._color_group.addButton(self.rb_flag)
        self._color_group.addButton(self.rb_col)
        self._color_group.setExclusive(True)

        cc2_row = QHBoxLayout()
        cc2_row.setContentsMargins(48, 0, 0, 0)   # 与上方下拉框左缘对齐
        self.cmb_color_col = _SilentComboBox()
        cc2_row.addWidget(self.cmb_color_col, 1)
        panel_v.addLayout(cc2_row)

        # ---- Filter by 分组（与 Diurnal/Histogram 同一套）----
        filter_group = QGroupBox(tr('Filter by'))
        filter_v = QVBoxLayout(filter_group)
        filter_v.setSpacing(5)
        filter_v.setContentsMargins(4, 4, 4, 4)

        h_flag = QHBoxLayout()
        self.chk_flag = QCheckBox(tr('Flag'))
        self.lbl_include = QLabel(tr('Include'))
        self.chk_unflagged = QCheckBox(tr('<Unflagged data>'))
        self.chk_unflagged.setChecked(True)
        h_flag.addWidget(self.chk_flag)
        h_flag.addWidget(self.lbl_include)
        h_flag.addWidget(self.chk_unflagged)
        h_flag.addStretch(1)
        filter_v.addLayout(h_flag)

        h_date = QHBoxLayout()
        self.chk_date = QCheckBox(tr('Date'))
        self.cmb_year = _SilentComboBox()
        self.cmb_month = _SilentComboBox()
        h_date.addWidget(self.chk_date)
        h_date.addWidget(QLabel(tr('Year')))
        h_date.addWidget(self.cmb_year)
        h_date.addWidget(QLabel(tr('Month')))
        h_date.addWidget(self.cmb_month, 1)
        filter_v.addLayout(h_date)

        h_range = QHBoxLayout()
        self.chk_range = QCheckBox(tr('Date range'))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat('yyyy/M/d')
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat('yyyy/M/d')
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)
        h_range.addWidget(self.chk_range)
        h_range.addWidget(self.date_from)
        h_range.addWidget(self.date_to, 1)
        filter_v.addLayout(h_range)

        h_sector = QHBoxLayout()
        self.chk_sector = QCheckBox(tr('Direction sector'))
        self.cmb_sector = _SilentComboBox()
        self.cmb_sector.setMaximumWidth(70)
        self.lbl_sectors = QLabel(tr('Sectors'))
        self.spin_sectors = QSpinBox()
        self.spin_sectors.setRange(4, 72)
        self.spin_sectors.setValue(16)
        self.spin_sectors.setMaximumWidth(76)
        h_sector.addWidget(self.chk_sector)
        h_sector.addWidget(self.cmb_sector)
        h_sector.addWidget(self.lbl_sectors)
        h_sector.addWidget(self.spin_sectors)
        h_sector.addStretch(1)
        filter_v.addLayout(h_sector)

        h_sensor = QHBoxLayout()
        h_sensor.setContentsMargins(12, 0, 0, 0)
        self.lbl_sensor = QLabel(tr('Direction sensor'))
        self.cmb_sensor = _SilentComboBox()
        self.cmb_sensor.setMinimumWidth(90)
        self.lbl_sensor.setEnabled(False)
        self.cmb_sensor.setEnabled(False)
        h_sensor.addWidget(self.lbl_sensor)
        h_sensor.addWidget(self.cmb_sensor, 1)
        filter_v.addLayout(h_sensor)

        h_dcol = QHBoxLayout()
        self.chk_dcol = QCheckBox(tr('Data column'))
        self.cmb_filter_data = _SilentComboBox()
        h_dcol.addWidget(self.chk_dcol)
        h_dcol.addWidget(self.cmb_filter_data, 1)
        filter_v.addLayout(h_dcol)

        h_limit = QHBoxLayout()
        h_limit.setContentsMargins(8, 0, 0, 0)
        h_limit.setSpacing(5)
        self.chk_min = QCheckBox(tr('Min'))
        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(-1e6, 1e6)
        self.spin_min.setDecimals(1)
        self.spin_min.setValue(0.0)
        self.spin_min.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.chk_max = QCheckBox(tr('Max'))
        self.spin_max = QDoubleSpinBox()
        self.spin_max.setRange(-1e6, 1e6)
        self.spin_max.setDecimals(1)
        self.spin_max.setValue(50.0)
        self.spin_max.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        h_limit.addWidget(self.chk_min)
        h_limit.addWidget(self.spin_min)
        h_limit.addWidget(self.chk_max)
        h_limit.addWidget(self.spin_max, 1)
        filter_v.addLayout(h_limit)

        panel_v.addWidget(filter_group)

        # ---- Results ----
        results_group = QGroupBox(tr('Results'))
        res_v = QVBoxLayout(results_group)
        res_v.setSpacing(4)
        res_v.setContentsMargins(4, 4, 4, 4)
        grid = QHBoxLayout()
        grid.setSpacing(6)
        self.lbl_count = QLabel(tr('Number of'))
        self.val_count = QLabel('—')
        grid.addWidget(self.lbl_count)
        grid.addWidget(self.val_count, 1)
        res_v.addLayout(grid)
        gx = QHBoxLayout()
        gx.setSpacing(6)
        gx.addWidget(QLabel(tr('Mean x value :')))
        self.val_x = QLabel('—')
        gx.addWidget(self.val_x, 1)
        res_v.addLayout(gx)
        gy = QHBoxLayout()
        gy.setSpacing(6)
        gy.addWidget(QLabel(tr('Mean y value :')))
        self.val_y = QLabel('—')
        gy.addWidget(self.val_y, 1)
        res_v.addLayout(gy)
        self.chk_best = QCheckBox(tr('Show line of best fit'))
        res_v.addWidget(self.chk_best)
        panel_v.addWidget(results_group)
        panel_v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(self._panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        self.canvas = PlotCanvas('Scatter Plot')
        self.canvas.export_header = 'Scatter Plot'

        main_h.addWidget(scroll)
        main_h.addWidget(self.canvas, 1)

        # ---- 信号 ----
        self.cmb_y.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_x.currentIndexChanged.connect(self._on_cfg_changed)
        self.btn_swap.clicked.connect(self._on_swap)
        self.chk_color.stateChanged.connect(self._on_cfg_changed)
        self.rb_flag.toggled.connect(self._on_cfg_changed)
        self.rb_col.toggled.connect(self._on_cfg_changed)
        self.cmb_color_col.currentIndexChanged.connect(self._on_cfg_changed)
        self.chk_best.stateChanged.connect(self._on_cfg_changed)

        self.chk_flag.stateChanged.connect(self._on_cfg_changed)
        self.chk_unflagged.stateChanged.connect(self._on_cfg_changed)
        self.chk_date.stateChanged.connect(self._on_cfg_changed)
        self.cmb_year.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_month.currentIndexChanged.connect(self._on_cfg_changed)
        self.chk_range.stateChanged.connect(self._on_range_check_changed)
        self.date_from.dateChanged.connect(self._on_cfg_changed)
        self.date_to.dateChanged.connect(self._on_cfg_changed)
        self.chk_sector.stateChanged.connect(self._on_sector_check_changed)
        self.cmb_sector.currentIndexChanged.connect(self._on_cfg_changed)
        self.spin_sectors.valueChanged.connect(self._on_sectors_changed)
        self.cmb_sensor.currentIndexChanged.connect(self._on_cfg_changed)
        self.chk_dcol.stateChanged.connect(self._on_cfg_changed)
        self.cmb_filter_data.currentIndexChanged.connect(self._on_dcol_changed)
        self.chk_min.stateChanged.connect(self._on_cfg_changed)
        self.spin_min.valueChanged.connect(self._on_cfg_changed)
        self.chk_max.stateChanged.connect(self._on_cfg_changed)
        self.spin_max.valueChanged.connect(self._on_cfg_changed)

        self._update_filter_enabled()

    # ------------------------------------------------------------------
    # 项目注入与配置读写
    # ------------------------------------------------------------------
    def set_project(self, project: Project | None):
        self.project = project
        self._block_cfg_signals(True)
        try:
            ds = self._active_dataset()
            if ds is not None and not ds.df.empty:
                self._refresh_col_lists()
                self._refresh_year_month_lists()
                self._refresh_sensor_list()
                self._refresh_filter_data_list()
                self._init_date_range()
                self._load_project_cfg()
                self.refresh()
        finally:
            self._block_cfg_signals(False)

    def _active_dataset(self) -> Dataset | None:
        if self.project is None:
            return None
        return self.project.active_dataset

    def _block_cfg_signals(self, block: bool):
        widgets = [
            self.cmb_y, self.cmb_x, self.chk_color, self.rb_flag,
            self.rb_col, self.cmb_color_col, self.chk_best,
            self.chk_flag, self.chk_unflagged,
            self.chk_date, self.cmb_year, self.cmb_month,
            self.chk_range, self.date_from, self.date_to,
            self.chk_sector, self.cmb_sector, self.spin_sectors,
            self.cmb_sensor,
            self.chk_dcol, self.cmb_filter_data,
            self.chk_min, self.spin_min, self.chk_max, self.spin_max,
        ]
        for w in widgets:
            w.blockSignals(block)

    def _current_cfg(self) -> dict:
        if self.project is None:
            return {}
        return self.project.plot_setting(self.CFG_KEY)

    def _load_project_cfg(self):
        cfg = self._current_cfg()
        self.cmb_y.setCurrentIndexByData(cfg.get('y_col'))
        self.cmb_x.setCurrentIndexByData(cfg.get('x_col'))
        # 未保存过时给一组合理默认：y/x 取前两个风速 Avg 通道
        if self.cmb_y.currentIndex() < 0:
            self.cmb_y.setCurrentIndex(0)
        if self.cmb_x.currentIndex() < 0 and self.cmb_y.count() > 1:
            self.cmb_x.setCurrentIndex(1)
        elif self.cmb_x.currentIndex() < 0:
            self.cmb_x.setCurrentIndex(0)
        self.chk_color.setChecked(cfg.get('color_code', False))
        (self.rb_flag if cfg.get('color_mode', 'flag') == 'flag'
         else self.rb_col).setChecked(True)
        cc = cfg.get('color_col')
        if cc and self.cmb_color_col.findData(cc) >= 0:
            self.cmb_color_col.setCurrentIndexByData(cc)
        self.chk_best.setChecked(cfg.get('best_fit', False))

        f = cfg.get('filter', {})
        self.chk_flag.setChecked(f.get('use_flag', False))
        self.chk_unflagged.setChecked(f.get('unflagged', True))
        self.chk_date.setChecked(f.get('use_date', False))
        self.cmb_year.setCurrentIndexByData(f.get('year', ''))
        self.cmb_month.setCurrentIndexByData(f.get('month', ''))
        self.chk_range.setChecked(f.get('use_range', False))
        self.chk_sector.setChecked(f.get('use_sector', False))
        self.spin_sectors.setValue(int(f.get('sectors', 16)))
        self._rebuild_sector_combo()
        self.cmb_sector.setCurrentIndexByData(f.get('sector', _SECTOR_ALL))
        self.cmb_sensor.setCurrentIndexByData(f.get('dir_sensor', ''))
        self.chk_dcol.setChecked(f.get('use_dcol', False))
        self.cmb_filter_data.setCurrentIndexByData(f.get('dcol', ''))
        self.chk_min.setChecked(f.get('use_min', True))
        self.spin_min.setValue(float(f.get('min', 0.0)))
        self.chk_max.setChecked(f.get('use_max', True))
        self.spin_max.setValue(float(f.get('max', 50.0)))
        self._sync_limit_suffix()

        dr = cfg.get('date_range', {})
        try:
            if dr.get('from'):
                self.date_from.setDate(
                    pd.Timestamp(dr['from']).to_pydatetime())
            if dr.get('to'):
                self.date_to.setDate(pd.Timestamp(dr['to']).to_pydatetime())
        except Exception:
            pass
        self._update_filter_enabled()

    def _save_project_cfg(self):
        if self.project is None:
            return
        cfg = {
            'y_col': self.cmb_y.currentData() or '',
            'x_col': self.cmb_x.currentData() or '',
            'color_code': self.chk_color.isChecked(),
            'color_mode': 'flag' if self.rb_flag.isChecked() else 'column',
            'color_col': self.cmb_color_col.currentData() or '',
            'best_fit': self.chk_best.isChecked(),
            'filter': {
                'use_flag': self.chk_flag.isChecked(),
                'unflagged': self.chk_unflagged.isChecked(),
                'use_date': self.chk_date.isChecked(),
                'year': self.cmb_year.currentData() or '',
                'month': self.cmb_month.currentData() or '',
                'use_range': self.chk_range.isChecked(),
                'use_sector': self.chk_sector.isChecked(),
                'sector': self.cmb_sector.currentData() or _SECTOR_ALL,
                'sectors': self.spin_sectors.value(),
                'dir_sensor': self.cmb_sensor.currentData() or '',
                'use_dcol': self.chk_dcol.isChecked(),
                'dcol': self.cmb_filter_data.currentData() or '',
                'use_min': self.chk_min.isChecked(),
                'min': self.spin_min.value(),
                'use_max': self.chk_max.isChecked(),
                'max': self.spin_max.value(),
            },
            'date_range': {
                'from': self.date_from.date().toString('yyyy/MM/dd'),
                'to': self.date_to.date().toString('yyyy/MM/dd'),
            },
        }
        self.project.set_plot_setting(self.CFG_KEY, cfg)

    # ------------------------------------------------------------------
    # 下拉列表填充
    # ------------------------------------------------------------------
    def _sd_partner(self, ds: Dataset, avg_name: str) -> str | None:
        """找风速 Avg 通道配对的 SD 通道（注册关联优先，命名约定兜底）。"""
        ch = ds.channels.get(avg_name)
        cand = getattr(ch, 'sd_col', '') if ch is not None else ''
        if cand and cand in ds.df.columns:
            return cand
        guess = avg_name.rsplit(' Avg', 1)
        guess = guess[0] + ' SD' if len(guess) == 2 else ''
        return guess if guess in ds.df.columns else None

    def _computed_entries(self, ds: Dataset) -> list[str]:
        """派生计算列名（与 Diurnal/Histogram 一致：先 TI 后 WPD）。"""
        ti_names: list[str] = []
        wpd_names: list[str] = []
        for n, ch in ds.channels.items():
            if (ch.kind != KIND_SPEED
                    or getattr(ch, 'role', 'Avg') != 'Avg'
                    or n not in ds.df.columns):
                continue
            if self._sd_partner(ds, n):
                ti_names.append(n + _TI_SUFFIX)
            wpd_names.append(n + _WPD_SUFFIX)
        return ti_names + wpd_names

    def _refresh_col_lists(self):
        ds = self._active_dataset()
        if ds is None:
            return
        names = list(ds.channels.keys()) + self._computed_entries(ds)
        # 默认 y/x：前两个风速 Avg 通道（对齐原版的两支风速仪对比）
        speeds = [n for n, ch in ds.channels.items()
                  if ch.kind == KIND_SPEED
                  and getattr(ch, 'role', 'Avg') == 'Avg'
                  and n in ds.df.columns]
        # 注意：此处不再自行 blockSignals(False)——外层 set_project 的
        # _block_cfg_signals(True) 负责屏蔽；内层解封会让 setCurrentIndex
        # 触发 _on_cfg_changed 用默认值覆盖已保存的 scatter 配置
        for cb in (self.cmb_y, self.cmb_x, self.cmb_color_col):
            cb.clear()
            for name in names:
                cb.addItem(name, name)
        if speeds:
            self.cmb_y.setCurrentIndexByData(speeds[0])
            if len(speeds) > 1:
                self.cmb_x.setCurrentIndexByData(speeds[1])
            else:
                self.cmb_x.setCurrentIndexByData(speeds[0])
            self.cmb_color_col.setCurrentIndexByData(speeds[0])

    def _refresh_year_month_lists(self):
        self.cmb_year.clear()
        self.cmb_year.addItem('<All>', '')
        self.cmb_month.clear()
        self.cmb_month.addItem('<All>', '')
        ds = self._active_dataset()
        if ds is None or ds.df.empty:
            return
        try:
            years = sorted(ds.df.index.year.unique())
        except (AttributeError, TypeError):
            return
        for y in years:
            self.cmb_year.addItem(str(y), str(y))
        for m in range(1, 13):
            self.cmb_month.addItem(str(m), str(m))

    def _refresh_sensor_list(self):
        self.cmb_sensor.clear()
        ds = self._active_dataset()
        if ds is None:
            return
        for n, ch in ds.channels.items():
            if (ch.kind == KIND_DIR
                    and getattr(ch, 'role', 'Avg') == 'Avg'
                    and n in ds.df.columns):
                self.cmb_sensor.addItem(n, n)

    def _refresh_filter_data_list(self):
        self.cmb_filter_data.clear()
        ds = self._active_dataset()
        if ds is None:
            return
        for n in ds.channels.keys():
            if n in ds.df.columns:
                self.cmb_filter_data.addItem(n, n)
        for n in ds.df.columns:
            if self.cmb_filter_data.findData(n) < 0:
                self.cmb_filter_data.addItem(n, n)

    def _rebuild_sector_combo(self):
        self.cmb_sector.blockSignals(True)
        self.cmb_sector.clear()
        self.cmb_sector.addItem(tr('All'), _SECTOR_ALL)
        n = self.spin_sectors.value()
        for i in range(1, n + 1):
            self.cmb_sector.addItem(str(i), i)
        self.cmb_sector.blockSignals(False)

    def _init_date_range(self):
        ds = self._active_dataset()
        if ds is None or ds.df.empty:
            return
        idx = ds.df.index
        if len(idx) == 0:
            return
        self.date_from.setDate(pd.Timestamp(idx[0]).to_pydatetime())
        self.date_to.setDate(pd.Timestamp(idx[-1]).to_pydatetime())

    def _sync_limit_suffix(self):
        ds = self._active_dataset()
        col = self.cmb_filter_data.currentData()
        unit = ''
        if ds is not None and col:
            ch = ds.channels.get(col)
            if ch is not None and ch.units:
                unit = f' {ch.units}'
        self.spin_min.setSuffix(unit)
        self.spin_max.setSuffix(unit)

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _on_cfg_changed(self, *args):
        self._update_filter_enabled()
        self._save_project_cfg()
        self.refresh()

    def _on_swap(self):
        y, x = self.cmb_y.currentData(), self.cmb_x.currentData()
        if not y or not x or y == x:
            return
        self._block_cfg_signals(True)
        self.cmb_y.setCurrentIndexByData(x)
        self.cmb_x.setCurrentIndexByData(y)
        self._block_cfg_signals(False)
        self._on_cfg_changed()

    def _on_range_check_changed(self, state: int):
        # stateChanged 传 int，不能与 Qt.Checked 枚举直接比较（恒 False）
        enabled = self.chk_range.isChecked()
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)
        self._on_cfg_changed()

    def _on_sector_check_changed(self, state: int):
        self._update_filter_enabled()
        self._on_cfg_changed()

    def _on_sectors_changed(self, value: int):
        self._rebuild_sector_combo()
        self._on_cfg_changed()

    def _on_dcol_changed(self):
        self._sync_limit_suffix()
        self._on_cfg_changed()

    def _update_filter_enabled(self):
        enabled = self.chk_flag.isChecked()
        self.lbl_include.setEnabled(enabled)
        self.chk_unflagged.setEnabled(enabled)
        enabled = self.chk_date.isChecked()
        self.cmb_year.setEnabled(enabled)
        self.cmb_month.setEnabled(enabled)
        enabled = self.chk_range.isChecked()
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)
        sector_on = self.chk_sector.isChecked()
        self.cmb_sector.setEnabled(sector_on)
        self.lbl_sectors.setEnabled(sector_on)
        self.spin_sectors.setEnabled(sector_on)
        sensor_on = sector_on and self.cmb_sector.currentData() != _SECTOR_ALL
        self.lbl_sensor.setEnabled(sensor_on)
        self.cmb_sensor.setEnabled(sensor_on)
        enabled = self.chk_dcol.isChecked()
        self.cmb_filter_data.setEnabled(enabled)
        self.chk_min.setEnabled(enabled)
        self.spin_min.setEnabled(enabled and self.chk_min.isChecked())
        self.chk_max.setEnabled(enabled)
        self.spin_max.setEnabled(enabled and self.chk_max.isChecked())
        # Color code by 联动
        cc_on = self.chk_color.isChecked()
        self.rb_flag.setEnabled(cc_on)
        self.rb_col.setEnabled(cc_on)
        self.cmb_color_col.setEnabled(cc_on and self.rb_col.isChecked())

    # ------------------------------------------------------------------
    # 过滤（与 Diurnal/Histogram 同一套）
    # ------------------------------------------------------------------
    def _build_filter_mask(self, ds: Dataset) -> pd.Series | None:
        if ds is None or ds.df.empty:
            return None
        cfg = self._current_cfg().get('filter', {})
        df = ds.df
        mask = pd.Series(True, index=df.index)
        has_filter = False

        if cfg.get('use_flag'):
            has_filter = True
            unflagged = cfg.get('unflagged', True)
            flags = getattr(ds, 'flags', None)
            if flags is not None and len(flags) == len(df):
                flags = flags.astype(bool)
                # 勾选 <Unflagged data> → 只画未标记数据；取消 → 只画已标记
                sel = ~flags if unflagged else flags
                mask &= sel

        if cfg.get('use_date'):
            has_filter = True
            year = cfg.get('year', '')
            month = cfg.get('month', '')
            if year:
                try:
                    mask &= df.index.year == int(year)
                except (TypeError, ValueError):
                    pass
            if month:
                try:
                    mask &= df.index.month == int(month)
                except (TypeError, ValueError):
                    pass

        if cfg.get('use_range'):
            has_filter = True
            dr = self._current_cfg().get('date_range', {})
            if dr.get('from'):
                mask &= df.index >= pd.Timestamp(dr['from'])
            if dr.get('to'):
                mask &= df.index <= pd.Timestamp(dr['to']) \
                    + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

        if cfg.get('use_sector') and cfg.get('sector', _SECTOR_ALL) != _SECTOR_ALL:
            sensor = cfg.get('dir_sensor') or self.cmb_sensor.currentData()
            if sensor and sensor in df.columns:
                has_filter = True
                n = int(cfg.get('sectors', 16))
                k = int(cfg.get('sector')) - 1        # 下拉为 1 基
                width = 360.0 / n
                d = pd.to_numeric(df[sensor], errors='coerce')
                mask &= ((d - k * width) % 360.0) < width

        if cfg.get('use_dcol'):
            dcol = cfg.get('dcol')
            if dcol and dcol in df.columns:
                has_filter = True
                s = pd.to_numeric(df[dcol], errors='coerce')
                if cfg.get('use_min', True):
                    mask &= s >= float(cfg.get('min', 0.0))
                if cfg.get('use_max', True):
                    mask &= s <= float(cfg.get('max', 50.0))

        return mask if has_filter else None

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------
    def _col_unit(self, col: str) -> str:
        if col.endswith(_TI_SUFFIX):
            return '%'
        if col.endswith(_WPD_SUFFIX):
            return 'W/m²'
        ds = self._active_dataset()
        ch = ds.channels.get(col) if ds else None
        if ch is not None and ch.units:
            return ch.units
        return 'm/s' if (ch is not None and ch.kind == KIND_SPEED) else ''

    def _materialize_extra(self, ds: Dataset, col: str):
        """TI/WPD 计算列 → (extra 项, None)；实列 → (None, col)。"""
        if col in ds.df.columns:
            return None, col
        if col.endswith(_TI_SUFFIX):
            base = col[:-len(_TI_SUFFIX)]
            sd = self._sd_partner(ds, base)
            if sd is None:
                return None, None
            return (col, ti_series(ds.df, base, sd)), None
        if col.endswith(_WPD_SUFFIX):
            base = col[:-len(_WPD_SUFFIX)]
            if base not in ds.df.columns:
                return None, None
            temp_col = (self.project.selection.get('temp')
                        if self.project else None)
            pres_col = (self.project.selection.get('pres')
                        if self.project else None)
            return ((col, wpd_series(ds.df, base, temp_col, pres_col)), None)
        return None, None

    def refresh(self):
        ds = self._active_dataset()
        if ds is None or ds.df.empty:
            self.canvas.clear(tr('未载入数据集'))
            return
        y_col = self.cmb_y.currentData()
        x_col = self.cmb_x.currentData()
        if not y_col or not x_col:
            self.canvas.clear(tr('请选择数据列'))
            return

        extra: dict[str, pd.Series] = {}
        for col in {y_col, x_col}:
            e, _real = self._materialize_extra(ds, col)
            if e:
                extra[e[0]] = e[1]
        if (y_col not in ds.df.columns and y_col not in extra) or \
                (x_col not in ds.df.columns and x_col not in extra):
            self.canvas.clear(tr('数据列不可用'))
            return

        work = ds.df
        if extra:
            work = ds.df.copy()
            for name, s in extra.items():
                work[name] = s

        xv = pd.to_numeric(work[x_col], errors='coerce')
        yv = pd.to_numeric(work[y_col], errors='coerce')
        mask = self._build_filter_mask(ds)
        if mask is not None:
            xv, yv = xv[mask], yv[mask]
        valid = xv.notna() & yv.notna()
        xv = xv[valid].astype(float)
        yv = yv[valid].astype(float)
        if len(xv) == 0:
            self.canvas.clear(tr('无有效数据点'))
            self.val_count.setText('0')
            self.val_x.setText('—')
            self.val_y.setText('—')
            return

        point_colors = None
        colorbar = None
        if self.chk_color.isChecked():
            if self.rb_col.isChecked():
                ccol = self.cmb_color_col.currentData()
                ce, creal = self._materialize_extra(ds, ccol)
                if ce:
                    cv = ce[1].reindex(xv.index)
                elif ccol and ccol in ds.df.columns:
                    cv = pd.to_numeric(ds.df[ccol], errors='coerce') \
                        .reindex(xv.index)
                else:
                    cv = None
                if cv is not None:
                    point_colors, colorbar = self._column_colors(cv)
            else:
                # 按 flag 着色：未标记点深灰，各命名标记用注册色
                colors = np.full(len(xv), _UNFLAGGED_COLOR, dtype=object)
                idx_positions = {t: i for i, t in enumerate(xv.index)}
                for fname, fm in getattr(ds, 'flag_masks', {}).items():
                    color = getattr(ds.flag_registry.get(fname), 'color',
                                    '#e74c3c')
                    for t in fm.index[fm.astype(bool)]:
                        i = idx_positions.get(t)
                        if i is not None:
                            colors[i] = color
                point_colors = colors

        unit = self._col_unit(x_col)
        title = f'{y_col} vs. {x_col}'
        self.canvas.set_title(title)
        self.canvas.plot_scatter(
            xv.to_numpy(), yv.to_numpy(),
            xlabel=f'{x_col} ({unit})' if unit else x_col,
            ylabel=f'{y_col} ({self._col_unit(y_col)})'
            if self._col_unit(y_col) else y_col,
            title=title,
            regression=self.chk_best.isChecked(),
            ymin=0,
            point_colors=point_colors,
            colorbar=colorbar)

        # Results
        self.val_count.setText(f'{len(xv):,}')
        self.val_x.setText(f'{float(xv.mean()):.2f} {unit}'.strip())
        self.val_y.setText(
            f'{float(yv.mean()):.2f} {self._col_unit(y_col)}'.strip())

    def _column_colors(self, cv: pd.Series):
        """数据列分档着色：0/缺测 → 黑色，其余按量程 10 等分 jet 色带。

        返回 (逐点颜色数组, 色带图例 [(label, color), ...])。"""
        v = pd.to_numeric(cv, errors='coerce')
        vmax = float(v.max()) if v.notna().any() else 1.0
        if vmax <= 0:
            vmax = 1.0
        bw = vmax / _COLOR_BANDS
        colors = np.full(len(v), '#000000', dtype=object)
        vals = v.to_numpy(dtype=float)
        finite = np.isfinite(vals) & (vals > 0)
        idx = np.full(len(vals), -1, dtype=int)
        idx[finite] = np.minimum((vals[finite] / bw).astype(int),
                                 _COLOR_BANDS - 1)
        for i in range(_COLOR_BANDS):
            colors[idx == i] = _JET10[i]
        colorbar = [(f'{(i + 1) * bw:.2f}'.rstrip('0').rstrip('.'),
                     _JET10[i])
                    for i in range(_COLOR_BANDS - 1, -1, -1)]
        colorbar.append(('0', '#000000'))
        return colors, colorbar
