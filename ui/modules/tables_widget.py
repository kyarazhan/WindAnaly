"""Tables 控件：左侧 Windographer 风格设置面板 + 右侧统计表格。

对齐原版 Tables 标签页：
- Table 下拉：Data Set Summary / Environmental Summary / Data Columns /
  Wind Speed Sensor Summary / Monthly·Annual·Directional Statistics /
  Occurrences·Mean·Min·Max·Std by (Month and Hour of Day | Year and Month |
  Month) / Statistics by Bin / Weibull Statistics by Month /
  Wind Speed Statistics for Synthesis；
- Settings：Data column / Bin column / Direction sensor / Direction sector /
  Combine years together / Bin settings（Width·Start at·Make first bin half）；
- Filter by：Flag（Include / <Unflagged data> 复选框）、Date、Date range、
  Direction sector、Data column Min/Max（与其它标签页同一套过滤）；
- Export Table... 按钮 + 表格右键 Copy/Export/Transposed 菜单。

配置经 Project.plot_settings['tables'] 随项目文件持久化。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox,
                               QDateEdit, QDialog, QDoubleSpinBox,
                               QFileDialog, QFrame, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QMenu,
                               QMessageBox, QPushButton,
                               QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from core import table_stats as ts
from core.dataset import KIND_DIR, KIND_SPEED, KIND_TEMP, Dataset
from core.diurnal import ti_series, wpd_series
from core.project import Project
from core.wind_power import wind_power_class
from ui.modules.diurnal_widget import (_SECTOR_ALL, _TI_SUFFIX,
                                               _WPD_SUFFIX)
from ui.modules.wind_rose_widget import _SilentComboBox
from core.i18n import tr

TABLE_TYPES = [
    'Data Set Summary',
    'Environmental Summary',
    'Data Columns',
    'Wind Speed Sensor Summary',
    'Monthly Statistics',
    'Annual Statistics',
    'Directional Statistics',
    'Occurrences by Month and Hour of Day',
    'Mean by Month and Hour of Day',
    'Min. by Month and Hour of Day',
    'Max. by Month and Hour of Day',
    'Std. Dev. by Month and Hour of Day',
    'Occurrences by Year and Month',
    'Mean by Year and Month',
    'Min. by Year and Month',
    'Max. by Year and Month',
    'Std. Dev. by Year and Month',
    'Occurrences by Month',
    'Mean by Month',
    'Min. by Month',
    'Max. by Month',
    'Std. Dev. by Month',
    'Statistics by Bin',
    'Weibull Statistics by Month',
    'Wind Speed Statistics for Synthesis',
]

_MONTH_AGG = {
    'Occurrences by Month': 'count',
    'Mean by Month': 'mean',
    'Min. by Month': 'min',
    'Max. by Month': 'max',
    'Std. Dev. by Month': 'std',
    'Occurrences by Month and Hour of Day': 'count',
    'Mean by Month and Hour of Day': 'mean',
    'Min. by Month and Hour of Day': 'min',
    'Max. by Month and Hour of Day': 'max',
    'Std. Dev. by Month and Hour of Day': 'std',
    'Occurrences by Year and Month': 'count',
    'Mean by Year and Month': 'mean',
    'Min. by Year and Month': 'min',
    'Max. by Year and Month': 'max',
    'Std. Dev. by Year and Month': 'std',
}


class TablesWidget(QWidget):
    """Tables 控件：左设置面板 + 右统计表格。"""

    CFG_KEY = 'tables'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Project | None = None

        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(4)

        # ---- 左侧设置面板 ----
        self._panel = QWidget(self)
        self._panel.setMinimumWidth(270)
        self._panel.setMaximumWidth(356)
        panel_v = QVBoxLayout(self._panel)
        panel_v.setSpacing(6)
        panel_v.setContentsMargins(4, 4, 4, 4)

        h_table = QHBoxLayout()
        h_table.setSpacing(6)
        h_table.addWidget(QLabel(tr('Table')))
        self.cmb_table = _SilentComboBox()
        for t in TABLE_TYPES:
            self.cmb_table.addItem(t, t)
        h_table.addWidget(self.cmb_table, 1)
        panel_v.addLayout(h_table)

        panel_v.addWidget(self._section_label('Settings'))

        h_col = QHBoxLayout()
        h_col.setSpacing(6)
        h_col.addWidget(QLabel(tr('Data column')))
        self.cmb_col = _SilentComboBox()
        h_col.addWidget(self.cmb_col, 1)
        panel_v.addLayout(h_col)

        h_bin = QHBoxLayout()
        h_bin.setSpacing(6)
        h_bin.addWidget(QLabel(tr('Bin column')))
        self.cmb_bin = _SilentComboBox()
        h_bin.addWidget(self.cmb_bin, 1)
        panel_v.addLayout(h_bin)

        h_sensor = QHBoxLayout()
        h_sensor.setSpacing(6)
        h_sensor.addWidget(QLabel(tr('Direction sensor')))
        self.cmb_sensor = _SilentComboBox()
        h_sensor.addWidget(self.cmb_sensor, 1)
        panel_v.addLayout(h_sensor)

        h_sec = QHBoxLayout()
        h_sec.setSpacing(6)
        h_sec.addWidget(QLabel(tr('Direction sector:')))
        self.spin_sectors = QSpinBox()
        self.spin_sectors.setRange(4, 72)
        self.spin_sectors.setValue(12)
        h_sec.addWidget(self.spin_sectors)
        h_sec.addStretch(1)
        panel_v.addLayout(h_sec)

        self.chk_combine = QCheckBox(tr('Combine years together'))
        panel_v.addWidget(self.chk_combine)

        panel_v.addWidget(self._section_label('Bin settings'))
        h_width = QHBoxLayout()
        h_width.setSpacing(6)
        self.chk_width = QCheckBox(tr('Width'))
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.0, 1e5)
        self.spin_width.setDecimals(1)
        self.spin_width.setValue(0.0)
        self.spin_width.setEnabled(False)
        self.lbl_width_unit = QLabel('m/s')
        h_width.addWidget(self.chk_width)
        h_width.addWidget(self.spin_width)
        h_width.addWidget(self.lbl_width_unit)
        h_width.addStretch(1)
        panel_v.addLayout(h_width)

        h_start = QHBoxLayout()
        h_start.setSpacing(6)
        self.chk_start = QCheckBox(tr('Start at'))
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setRange(-100, 1e5)
        self.spin_start.setDecimals(1)
        self.spin_start.setValue(0.0)
        self.spin_start.setEnabled(False)
        self.lbl_start_unit = QLabel('m/s')
        h_start.addWidget(self.chk_start)
        h_start.addWidget(self.spin_start)
        h_start.addWidget(self.lbl_start_unit)
        h_start.addStretch(1)
        panel_v.addLayout(h_start)

        # Make first bin half this width：位于 Start at 之下（原版顺序）；
        # 长文字两行折行（点文字等效点框）
        half_row = QHBoxLayout()
        half_row.setSpacing(6)
        half_row.setContentsMargins(0, 0, 0, 0)
        self.chk_half = QCheckBox()
        self.lbl_half = QLabel(tr('Make first bin half this width'))
        self.lbl_half.setWordWrap(True)
        self.lbl_half.mousePressEvent = lambda _evt: self.chk_half.toggle()
        half_row.addWidget(self.chk_half)
        half_row.addWidget(self.lbl_half, 1)
        panel_v.addLayout(half_row)

        # ---- Filter by 分组 ----
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
        self.spin_fsectors = QSpinBox()
        self.spin_fsectors.setRange(4, 72)
        self.spin_fsectors.setValue(16)
        self.spin_fsectors.setMaximumWidth(76)
        h_sector.addWidget(self.chk_sector)
        h_sector.addWidget(self.cmb_sector)
        h_sector.addWidget(self.lbl_sectors)
        h_sector.addWidget(self.spin_fsectors)
        h_sector.addStretch(1)
        filter_v.addLayout(h_sector)

        h_sensor2 = QHBoxLayout()
        h_sensor2.setContentsMargins(12, 0, 0, 0)
        self.lbl_sensor = QLabel(tr('Direction sensor'))
        self.cmb_fsensor = _SilentComboBox()
        self.cmb_fsensor.setMinimumWidth(90)
        self.lbl_sensor.setEnabled(False)
        self.cmb_fsensor.setEnabled(False)
        h_sensor2.addWidget(self.lbl_sensor)
        h_sensor2.addWidget(self.cmb_fsensor, 1)
        filter_v.addLayout(h_sensor2)

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
        panel_v.addStretch(1)

        self.btn_export = QPushButton(tr('Export Table...'))
        self.btn_export.setMaximumWidth(140)
        panel_v.addWidget(self.btn_export, 0, Qt.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidget(self._panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        # ---- 右侧表格 ----
        self.table = QTableWidget()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        # 序号只保留一列：隐藏行号列，数据里的 # 列即序号
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(
            self._on_table_context_menu)

        main_h.addWidget(scroll)
        main_h.addWidget(self.table, 1)

        # ---- 信号 ----
        self.cmb_table.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_col.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_bin.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_sensor.currentIndexChanged.connect(self._on_cfg_changed)
        self.spin_sectors.valueChanged.connect(self._on_cfg_changed)
        self.chk_combine.stateChanged.connect(self._on_cfg_changed)
        self.chk_width.stateChanged.connect(
            lambda s: (self.spin_width.setEnabled(s == Qt.Checked),
                       self._on_cfg_changed()))
        self.spin_width.valueChanged.connect(self._on_cfg_changed)
        self.chk_start.stateChanged.connect(
            lambda s: (self.spin_start.setEnabled(s == Qt.Checked),
                       self._on_cfg_changed()))
        self.spin_start.valueChanged.connect(self._on_cfg_changed)
        self.chk_half.stateChanged.connect(self._on_cfg_changed)

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
        self.spin_fsectors.valueChanged.connect(self._on_sectors_changed)
        self.cmb_fsensor.currentIndexChanged.connect(self._on_cfg_changed)
        self.chk_dcol.stateChanged.connect(self._on_cfg_changed)
        self.cmb_filter_data.currentIndexChanged.connect(self._on_dcol_changed)
        self.chk_min.stateChanged.connect(self._on_cfg_changed)
        self.spin_min.valueChanged.connect(self._on_cfg_changed)
        self.chk_max.stateChanged.connect(self._on_cfg_changed)
        self.spin_max.valueChanged.connect(self._on_cfg_changed)

        self._update_filter_enabled()

    # ------------------------------------------------------------------
    @staticmethod
    def _section_label(text: str) -> QWidget:
        """Settings/Bin settings 小节标题：粗体 + 下划分隔线（原版样式）。"""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 2, 0, 0)
        v.setSpacing(2)
        lbl = QLabel(text)
        lbl.setStyleSheet('font-weight: bold;')
        v.addWidget(lbl)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        v.addWidget(line)
        return w

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
                self._refresh_sensor_lists()
                self._refresh_filter_data_list()
                self._init_date_range()
                self._sync_units()
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
            self.cmb_table, self.cmb_col, self.cmb_bin, self.cmb_sensor,
            self.spin_sectors, self.chk_combine,
            self.chk_width, self.spin_width, self.chk_start, self.spin_start,
            self.chk_half,
            self.chk_flag, self.chk_unflagged,
            self.chk_date, self.cmb_year, self.cmb_month,
            self.chk_range, self.date_from, self.date_to,
            self.chk_sector, self.cmb_sector, self.spin_fsectors,
            self.cmb_fsensor,
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
        self.cmb_table.setCurrentIndexByData(cfg.get('table', 'Data Set Summary'))
        self.cmb_col.setCurrentIndexByData(cfg.get('col'))
        self.cmb_bin.setCurrentIndexByData(cfg.get('bin_col'))
        self.cmb_sensor.setCurrentIndexByData(cfg.get('dir_sensor'))
        self.spin_sectors.setValue(int(cfg.get('sectors', 12)))
        self.chk_combine.setChecked(cfg.get('combine_years', False))
        self.chk_width.setChecked(cfg.get('use_width', False))
        self.spin_width.setValue(float(cfg.get('width', 0.0)))
        self.chk_start.setChecked(cfg.get('use_start', False))
        self.spin_start.setValue(float(cfg.get('start', 0.0)))
        self.chk_half.setChecked(cfg.get('half_first', False))

        f = cfg.get('filter', {})
        self.chk_flag.setChecked(f.get('use_flag', False))
        self.chk_unflagged.setChecked(f.get('unflagged', True))
        self.chk_date.setChecked(f.get('use_date', False))
        self.cmb_year.setCurrentIndexByData(f.get('year', ''))
        self.cmb_month.setCurrentIndexByData(f.get('month', ''))
        self.chk_range.setChecked(f.get('use_range', False))
        self.chk_sector.setChecked(f.get('use_sector', False))
        self.spin_fsectors.setValue(int(f.get('fsectors', 16)))
        self._rebuild_sector_combo()
        self.cmb_sector.setCurrentIndexByData(f.get('sector', _SECTOR_ALL))
        self.cmb_fsensor.setCurrentIndexByData(f.get('dir_sensor', ''))
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
            'table': self.cmb_table.currentData() or 'Data Set Summary',
            'col': self.cmb_col.currentData() or '',
            'bin_col': self.cmb_bin.currentData() or '',
            'dir_sensor': self.cmb_sensor.currentData() or '',
            'sectors': self.spin_sectors.value(),
            'combine_years': self.chk_combine.isChecked(),
            'use_width': self.chk_width.isChecked(),
            'width': self.spin_width.value(),
            'use_start': self.chk_start.isChecked(),
            'start': self.spin_start.value(),
            'half_first': self.chk_half.isChecked(),
            'filter': {
                'use_flag': self.chk_flag.isChecked(),
                'unflagged': self.chk_unflagged.isChecked(),
                'use_date': self.chk_date.isChecked(),
                'year': self.cmb_year.currentData() or '',
                'month': self.cmb_month.currentData() or '',
                'use_range': self.chk_range.isChecked(),
                'use_sector': self.chk_sector.isChecked(),
                'sector': self.cmb_sector.currentData() or _SECTOR_ALL,
                'fsectors': self.spin_fsectors.value(),
                'dir_sensor': self.cmb_fsensor.currentData() or '',
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
        ch = ds.channels.get(avg_name)
        cand = getattr(ch, 'sd_col', '') if ch is not None else ''
        if cand and cand in ds.df.columns:
            return cand
        guess = avg_name.rsplit(' Avg', 1)
        guess = guess[0] + ' SD' if len(guess) == 2 else ''
        return guess if guess in ds.df.columns else None

    def _computed_entries(self, ds: Dataset) -> list[str]:
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
        speeds = [n for n, ch in ds.channels.items()
                  if ch.kind == KIND_SPEED
                  and getattr(ch, 'role', 'Avg') == 'Avg'
                  and n in ds.df.columns]
        for cb in (self.cmb_col, self.cmb_bin):
            cb.clear()
            for name in names:
                cb.addItem(name, name)
        if speeds:
            self.cmb_col.setCurrentIndexByData(speeds[0])
            self.cmb_bin.setCurrentIndexByData(speeds[0])

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

    def _refresh_sensor_lists(self):
        for cb in (self.cmb_sensor, self.cmb_fsensor):
            cb.clear()
        ds = self._active_dataset()
        if ds is None:
            return
        for n, ch in ds.channels.items():
            if (ch.kind == KIND_DIR
                    and getattr(ch, 'role', 'Avg') == 'Avg'
                    and n in ds.df.columns):
                self.cmb_sensor.addItem(n, n)
                self.cmb_fsensor.addItem(n, n)

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
        n = self.spin_fsectors.value()
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

    def _sync_units(self):
        ds = self._active_dataset()
        col = self.cmb_col.currentData()
        unit = 'm/s'
        if ds is not None and col:
            if col.endswith(_TI_SUFFIX):
                unit = '%'
            elif col.endswith(_WPD_SUFFIX):
                unit = 'W/m²'
            else:
                ch = ds.channels.get(col)
                if ch is not None and ch.units:
                    unit = ch.units
        self.lbl_width_unit.setText(unit)
        self.lbl_start_unit.setText(unit)

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

    def _on_range_check_changed(self, state: int):
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
        self.spin_fsectors.setEnabled(sector_on)
        sensor_on = sector_on and self.cmb_sector.currentData() != _SECTOR_ALL
        self.lbl_sensor.setEnabled(sensor_on)
        self.cmb_fsensor.setEnabled(sensor_on)
        enabled = self.chk_dcol.isChecked()
        self.cmb_filter_data.setEnabled(enabled)
        self.chk_min.setEnabled(enabled)
        self.spin_min.setEnabled(enabled and self.chk_min.isChecked())
        self.chk_max.setEnabled(enabled)
        self.spin_max.setEnabled(enabled and self.chk_max.isChecked())

    # ------------------------------------------------------------------
    # 过滤（与其它标签页同一套）
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
                # 勾选 <Unflagged data> → 只统计未标记数据；取消 → 只统计已标记
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
            sensor = cfg.get('dir_sensor') or self.cmb_fsensor.currentData()
            if sensor and sensor in df.columns:
                has_filter = True
                n = int(cfg.get('fsectors', 16))
                k = int(cfg.get('sector')) - 1
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
    # 数据准备
    # ------------------------------------------------------------------
    def _materialize_extra(self, ds: Dataset, col: str):
        """TI/WPD 计算列 → Series；实列 → None。"""
        if col in ds.df.columns:
            return None
        if col.endswith(_TI_SUFFIX):
            base = col[:-len(_TI_SUFFIX)]
            sd = self._sd_partner(ds, base)
            if sd is None:
                return None
            return ti_series(ds.df, base, sd)
        if col.endswith(_WPD_SUFFIX):
            base = col[:-len(_WPD_SUFFIX)]
            if base not in ds.df.columns:
                return None
            temp_col = (self.project.selection.get('temp')
                        if self.project else None)
            pres_col = (self.project.selection.get('pres')
                        if self.project else None)
            return wpd_series(ds.df, base, temp_col, pres_col)
        return None

    def _work_df(self, ds: Dataset, cols: list[str]) -> pd.DataFrame:
        """把需要的 TI/WPD 计算列物化进一个工作副本。"""
        extra = {}
        for col in cols:
            if col and col not in ds.df.columns:
                s = self._materialize_extra(ds, col)
                if s is not None:
                    extra[col] = s
        if not extra:
            return ds.df
        work = ds.df.copy()
        for name, s in extra.items():
            work[name] = s
        return work

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

    # ------------------------------------------------------------------
    # 刷新：按表型分发
    # ------------------------------------------------------------------
    def refresh(self):
        ds = self._active_dataset()
        if ds is None or ds.df.empty:
            self._set_table([])
            return
        ttype = self.cmb_table.currentData() or 'Data Set Summary'
        mask = self._build_filter_mask(ds)
        col = self.cmb_col.currentData()
        cols_needed = [c for c in (col, self.cmb_bin.currentData(),
                                   self.cmb_sensor.currentData()) if c]
        work = self._work_df(ds, cols_needed)

        builders = {
            'Data Set Summary': lambda: self._t_dataset_summary(work),
            'Environmental Summary': lambda: self._t_env_summary(work),
            'Data Columns': lambda: self._t_data_columns(work, mask),
            'Wind Speed Sensor Summary': lambda: self._t_sensor_summary(work, mask),
            'Monthly Statistics': lambda: self._t_group_table(work, mask, 'month'),
            'Annual Statistics': lambda: self._t_group_table(work, mask, 'year'),
            'Directional Statistics': lambda: self._t_directional(work, mask),
            'Statistics by Bin': lambda: self._t_by_bin(work, mask),
            'Weibull Statistics by Month': lambda: self._t_weibull_monthly(work, mask),
            'Wind Speed Statistics for Synthesis': lambda: self._t_synthesis(work, mask),
        }
        if ttype in builders:
            headers, rows = builders[ttype]()
        elif ttype in _MONTH_AGG:
            agg = _MONTH_AGG[ttype]
            if ttype.endswith('Month and Hour of Day'):
                headers, rows = self._t_month_hour(work, mask, agg)
            elif ttype.endswith('Year and Month'):
                headers, rows = self._t_year_month(work, mask, agg)
            else:
                headers, rows = self._t_by_month(work, mask, agg)
        else:
            headers, rows = [], []
        self._set_table([headers] + rows if headers else [])

    # ------------------------------------------------------------------
    # 各表型实现：返回 (headers, rows)
    # ------------------------------------------------------------------
    def _t_dataset_summary(self, work: pd.DataFrame):
        ds = self._active_dataset()
        attrs = getattr(ds, 'attrs', {})
        idx = work.index
        headers = ['Variable', 'Value']
        rows: list[list[str]] = []
        lat = attrs.get('lat')
        lon = attrs.get('lon')
        if lat is not None:
            hemi = 'N' if float(lat) >= 0 else 'S'
            rows.append(['Latitude', f'{hemi} {abs(float(lat)):.6f}'])
        if lon is not None:
            hemi = 'E' if float(lon) >= 0 else 'W'
            rows.append(['Longitude', f'{hemi} {abs(float(lon)):.6f}'])
        elev = attrs.get('elevation')
        if elev is not None:
            rows.append(['Elevation', f'{float(elev):g} m'])
        if len(idx):
            t0, t1 = pd.Timestamp(idx[0]), pd.Timestamp(idx[-1])
            rows.append(['Start date', t0.strftime('%Y/%m/%d %H:%M')])
            rows.append(['End date', t1.strftime('%Y/%m/%d %H:%M')])
            days = (t1 - t0).total_seconds() / 86400.0
            months = days / 30.4375
            rows.append(['Duration',
                         f'{months:.0f} months' if months >= 1
                         else f'{days:.0f} days'])
        minutes = ts.time_step_minutes(work)
        if minutes is not None:
            rows.append(['Length of time step', f'{minutes:g} minutes'])
        calm = getattr(ds, 'calm_threshold', 0.0)
        rows.append(['Calm threshold', f'{float(calm):g} m/s'])

        sel = self.project.selection if self.project else {}
        temp = sel.get('temp') or self._first_kind(ds, KIND_TEMP)
        pres = sel.get('pres')
        temp = temp if temp and temp in work.columns else None
        pres = pres if pres and pres in work.columns else None
        mean_t = float(work[temp].astype(float).mean()) if temp else None
        mean_p = float(work[pres].astype(float).mean()) if pres else None
        if mean_t is not None:
            rows.append(['Mean temperature', f'{mean_t:.1f} ℃'])
        if mean_p is not None:
            rows.append(['Mean pressure', f'{mean_p / 10.0:.1f} kPa'])
        rho = ts.mean_air_density(work, temp, pres)
        if rho is not None:
            rows.append(['Mean air density', f'{rho:.3f} kg/m3'])

        # 功率密度（取最接近 50m 的风速 Avg 通道）
        speeds = [(n, ch.height) for n, ch in ds.channels.items()
                  if ch.kind == KIND_SPEED
                  and getattr(ch, 'role', 'Avg') == 'Avg'
                  and n in work.columns]
        if speeds:
            h50 = min(speeds, key=lambda t: abs((t[1] or 0) - 50.0))
            v = pd.to_numeric(work[h50[0]], errors='coerce').dropna()
            if rho is None:
                rho = 1.225
            wpd = float(0.5 * rho * (v ** 3).mean())
            rows.append([f'Power density at {h50[1] or "?"}m',
                         f'{wpd:.0f} W/m2'])
            rows.append(['Wind power class', wind_power_class(wpd)])

        columns = {n: (ch.kind, ch.height) for n, ch in ds.channels.items()}
        alpha = ts.power_law_exponent(work, columns)
        if alpha is not None:
            rows.append(['Power law exponent', f'{alpha:.3f}'])
            # 地表粗糙度（对数律 z0）与粗糙度等级
            agg = {}
            for n, (kind, height) in columns.items():
                if kind == KIND_SPEED and height and height > 0 \
                        and n in work.columns:
                    v = pd.to_numeric(work[n], errors='coerce').mean()
                    if np.isfinite(v) and v > 0:
                        agg.setdefault(float(height), []).append(float(v))
            if len(agg) >= 2:
                hs = np.array(sorted(agg))
                vs = np.array([float(np.mean(agg[h])) for h in hs])
                b, a = np.polyfit(np.log(hs), vs, 1)
                if abs(b) > 1e-9:
                    z0 = float(np.exp(-a / b))
                    klass = (np.log(z0) + 3.91) / 1.05 if z0 > 0 else None
                    # 粗糙度不合理（负切变等极端情形）时省略这两行
                    if z0 is not None and 0 < z0 <= 50 and klass is not None \
                            and 0 <= klass <= 8:
                        rows.append(['Surface roughness', f'{z0:.2f} m'])
                        rows.append(['Roughness class', f'{klass:.2f}'])
        return headers, rows

    def _t_env_summary(self, work: pd.DataFrame):
        ds = self._active_dataset()
        sel = self.project.selection if self.project else {}
        temp = sel.get('temp') or self._first_kind(ds, KIND_TEMP)
        pres = sel.get('pres')
        temp = temp if temp and temp in work.columns else None
        pres = pres if pres and pres in work.columns else None
        if not temp or not pres:
            return ['Environmental Summary'], [
                ['Requires temperature and pressure channels']]
        t = pd.to_numeric(work[temp], errors='coerce')
        p = pd.to_numeric(work[pres], errors='coerce')
        rho = (p * 100.0) / (287.05 * (t + 273.15))
        frame = pd.DataFrame({'t': t, 'p': p, 'rho': rho})
        g = frame.groupby(frame.index.month)
        out = g.agg(t=('t', 'mean'), p=('p', 'mean'), rho=('rho', 'mean'))
        headers = ['Month', 'Mean temperature (℃)', 'Mean pressure (kPa)',
                   'Mean air density (kg/m3)']
        rows = [[str(m),
                 f'{r.t:.1f}' if pd.notna(r.t) else '',
                 f'{r.p / 10.0:.1f}' if pd.notna(r.p) else '',
                 f'{r.rho:.3f}' if pd.notna(r.rho) else '']
                for m, r in out.iterrows()]
        return headers, rows

    def _first_kind(self, ds: Dataset, kind) -> str | None:
        for n, ch in ds.channels.items():
            if ch.kind == kind and n in ds.df.columns:
                return n
        return None

    def _t_data_columns(self, work: pd.DataFrame, mask):
        ds = self._active_dataset()
        headers = ['#', 'Label', 'Units', 'Height', 'Possible Data Points',
                   'Valid Data Points', 'Recovery Rate (%)', 'Mean', 'Min',
                   'Max', 'Std. Dev.']
        rows = []
        names = list(ds.channels.keys()) + self._computed_entries(ds)
        possible = len(work)
        # 计算列（TI/WPD）按需物化
        extra = {}
        for name in names:
            if name not in work.columns:
                s = self._materialize_extra(ds, name)
                if s is not None:
                    extra[name] = s
        if extra:
            work = work.copy()
            for name, s in extra.items():
                work[name] = s
        for i, name in enumerate(names, start=1):
            ch = ds.channels.get(name)
            units = ('%' if name.endswith(_TI_SUFFIX)
                     else 'W/m²' if name.endswith(_WPD_SUFFIX)
                     else (ch.units if ch is not None and ch.units else ''))
            height = (ch.height if ch is not None else None)
            if name in work.columns:
                s = pd.to_numeric(work[name], errors='coerce')
                if mask is not None:
                    s = s[pd.Series(mask, index=work.index)
                          .fillna(False).astype(bool)]
                valid = int(s.notna().sum())
                st = ts._stats(s)
            else:
                valid, st = 0, ts._stats(pd.Series(dtype=float))
            recovery = valid / possible * 100.0 if possible else np.nan
            fmt = '.1f' if name.endswith(_TI_SUFFIX) else '.3f'
            rows.append([
                str(i), name, units,
                f'{height:g} m' if height else '', f'{possible:,}',
                f'{valid:,}',
                f'{recovery:.2f}' if np.isfinite(recovery) else '',
                f'{st["mean"]:{fmt}}' if np.isfinite(st['mean']) else '',
                f'{st["min"]:{fmt}}' if np.isfinite(st['min']) else '',
                f'{st["max"]:{fmt}}' if np.isfinite(st['max']) else '',
                f'{st["std"]:{fmt}}' if np.isfinite(st['std']) else '',
            ])
        return headers, rows

    def _t_sensor_summary(self, work: pd.DataFrame, mask):
        ds = self._active_dataset()
        headers = ['Label', 'Units', 'Height', 'Mean', 'Min', 'Max',
                   'Std. Dev.', 'Valid Data Points', 'Recovery Rate (%)']
        rows = []
        possible = len(work)
        for n, ch in ds.channels.items():
            if (ch.kind != KIND_SPEED
                    or getattr(ch, 'role', 'Avg') != 'Avg'
                    or n not in work.columns):
                continue
            s = pd.to_numeric(work[n], errors='coerce')
            if mask is not None:
                s = s[pd.Series(mask, index=work.index)
                      .fillna(False).astype(bool)]
            st = ts._stats(s)
            recovery = st['count'] / possible * 100.0 if possible else np.nan
            rows.append([n, ch.units or 'm/s',
                         f'{ch.height:g} m' if ch.height else '',
                         f'{st["mean"]:.3f}' if np.isfinite(st['mean']) else '',
                         f'{st["min"]:.3f}' if np.isfinite(st['min']) else '',
                         f'{st["max"]:.3f}' if np.isfinite(st['max']) else '',
                         f'{st["std"]:.3f}' if np.isfinite(st['std']) else '',
                         f'{st["count"]:,}',
                         f'{recovery:.2f}' if np.isfinite(recovery) else ''])
        return headers, rows

    def _t_group_table(self, work: pd.DataFrame, mask, mode: str):
        col = self.cmb_col.currentData()
        if not col or col not in work.columns:
            return ['Requires data column'], []
        frame = ts.by_month_stats(work, col, mask, with_all=True) \
            if mode == 'month' \
            else ts.by_year_stats(work, col, mask, with_all=True)
        headers = ['Month' if mode == 'month' else 'Year',
                   'Occurrences', 'Mean', 'Min', 'Max', 'Std. Dev.']
        rows = [[str(g), f'{int(r["count"]):,}',
                 f'{r["mean"]:.3f}' if pd.notna(r['mean']) else '',
                 f'{r["min"]:.3f}' if pd.notna(r['min']) else '',
                 f'{r["max"]:.3f}' if pd.notna(r['max']) else '',
                 f'{r["std"]:.3f}' if pd.notna(r['std']) else '']
                for g, r in frame.iterrows()]
        return headers, rows

    def _t_directional(self, work: pd.DataFrame, mask):
        col = self.cmb_col.currentData()
        sensor = self.cmb_sensor.currentData()
        sectors = self.spin_sectors.value()
        if not col or not sensor:
            return ['Requires data column and direction sensor'], []
        frame = ts.directional_stats(work, col, sensor, sectors, mask)
        if frame is None:
            return ['Requires data column and direction sensor'], []
        width = 360.0 / sectors
        headers = ['Sector', 'Midpoint (°)', 'Frequency (%)', 'Occurrences',
                   'Mean', 'Min', 'Max', 'Std. Dev.']
        rows = []
        for sec, r in frame.iterrows():
            mid = (sec - 0.5) * width
            rows.append([str(sec), f'{mid:.1f}',
                         f'{r["freq"]:.2f}' if pd.notna(r['freq']) else '',
                         f'{int(r["count"]):,}' if pd.notna(r['count']) else '',
                         f'{r["mean"]:.3f}' if pd.notna(r['mean']) else '',
                         f'{r["min"]:.3f}' if pd.notna(r['min']) else '',
                         f'{r["max"]:.3f}' if pd.notna(r['max']) else '',
                         f'{r["std"]:.3f}' if pd.notna(r['std']) else ''])
        return headers, rows

    def _t_month_hour(self, work: pd.DataFrame, mask, agg: str):
        col = self.cmb_col.currentData()
        if not col or col not in work.columns:
            return ['Requires data column'], []
        mat = ts.month_hour_matrix(work, col, agg, mask, with_all=True)
        is_count = agg == 'count'
        headers = ['Month'] + [str(h) for h in mat.columns]
        rows = []
        for m, r in mat.iterrows():
            rows.append([str(m)] + [
                f'{int(v):,}' if is_count and pd.notna(v)
                else f'{v:.2f}' if pd.notna(v) else ''
                for v in r])
        return headers, rows

    def _t_year_month(self, work: pd.DataFrame, mask, agg: str):
        col = self.cmb_col.currentData()
        if not col or col not in work.columns:
            return ['Requires data column'], []
        mat = ts.year_month_matrix(work, col, agg, mask, with_all=True)
        is_count = agg == 'count'
        headers = ['Year'] + [str(m) for m in mat.columns]
        rows = []
        for y, r in mat.iterrows():
            rows.append([str(y)] + [
                f'{int(v):,}' if is_count and pd.notna(v)
                else f'{v:.2f}' if pd.notna(v) else ''
                for v in r])
        return headers, rows

    def _t_by_month(self, work: pd.DataFrame, mask, agg: str):
        col = self.cmb_col.currentData()
        if not col or col not in work.columns:
            return ['Requires data column'], []
        frame = ts.by_month_stats(work, col, mask, with_all=True)
        key = {'count': 'count', 'mean': 'mean', 'min': 'min',
               'max': 'max', 'std': 'std'}[agg]
        headers = ['Month',
                   'Occurrences' if agg == 'count' else
                   {'mean': 'Mean', 'min': 'Min', 'max': 'Max',
                    'std': 'Std. Dev.'}[agg]]
        rows = []
        for m, r in frame.iterrows():
            v = r[key]
            rows.append([str(m),
                         f'{int(v):,}' if agg == 'count' and pd.notna(v)
                         else f'{v:.3f}' if pd.notna(v) else ''])
        return headers, rows

    def _t_by_bin(self, work: pd.DataFrame, mask):
        col = self.cmb_col.currentData()
        bin_col = self.cmb_bin.currentData()
        if not col or not bin_col:
            return ['Requires data column and bin column'], []
        frame = ts.bin_statistics(
            work, col, bin_col,
            bin_width=self.spin_width.value() if self.chk_width.isChecked()
            else None,
            bin_start=self.spin_start.value() if self.chk_start.isChecked()
            else None,
            half_first=self.chk_half.isChecked(),
            mask=mask)
        if frame is None:
            return ['Requires data column and bin column'], []
        headers = ['Bin', 'Lower', 'Upper', 'Occurrences', 'Mean', 'Min',
                   'Max', 'Std. Dev.']
        rows = []
        for i, ((lo, up), r) in enumerate(frame.iterrows(), start=1):
            rows.append([str(i), f'{lo:.1f}', f'{up:.1f}',
                         f'{int(r["count"]):,}' if pd.notna(r['count']) else '',
                         f'{r["mean"]:.3f}' if pd.notna(r['mean']) else '',
                         f'{r["min"]:.3f}' if pd.notna(r['min']) else '',
                         f'{r["max"]:.3f}' if pd.notna(r['max']) else '',
                         f'{r["std"]:.3f}' if pd.notna(r['std']) else ''])
        return headers, rows

    def _t_weibull_monthly(self, work: pd.DataFrame, mask):
        col = self.cmb_col.currentData()
        if not col or col not in work.columns:
            return ['Requires data column'], []
        frame = ts.weibull_monthly(work, col, mask)
        headers = ['Month', 'Weibull k', 'Weibull c (m/s)', 'Mean (m/s)',
                   'Occurrences']
        rows = []
        for m, r in frame.iterrows():
            rows.append([str(m),
                         f'{r["k"]:.2f}' if pd.notna(r['k']) else '',
                         f'{r["c"]:.2f}' if pd.notna(r['c']) else '',
                         f'{r["mean"]:.3f}' if pd.notna(r['mean']) else '',
                         f'{int(r["count"]):,}'])
        return headers, rows

    def _t_synthesis(self, work: pd.DataFrame, mask):
        headers, rows = self._t_weibull_monthly(work, mask)
        headers = ['Month', 'Mean Wind Speed (m/s)', 'Weibull k',
                   'Weibull c (m/s)']
        rows = [[r[0], r[4], r[1], r[2]] for r in rows]
        return headers, rows

    # ------------------------------------------------------------------
    # 表格渲染 / 右键菜单
    # ------------------------------------------------------------------
    def _set_table(self, grid: list[list[str]]):
        self.table.clear()
        if not grid:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return
        headers, body = grid[0], grid[1:]
        bold = QFont()
        bold.setBold(True)
        header_bg = QBrush(QColor('#e8f0fb'))
        self.table.setColumnCount(len(headers))
        self.table.setRowCount(len(body))
        self.table.setHorizontalHeaderLabels(headers)
        for c, h in enumerate(headers):
            item = self.table.horizontalHeaderItem(c)
            item.setFont(bold)
            item.setBackground(header_bg)
        for r, row in enumerate(body):
            for c, v in enumerate(row):
                item = QTableWidgetItem(str(v))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if c > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        self.table.resizeColumnsToContents()
        for c in range(self.table.columnCount()):
            header.setSectionResizeMode(c, QHeaderView.Interactive)
            if self.table.columnWidth(c) < 40:
                self.table.setColumnWidth(c, 40)

    def _table_data(self, transpose: bool = False) -> list[list[str]]:
        rows = self.table.rowCount()
        cols = self.table.columnCount()
        grid = []
        for r in range(rows):
            row = []
            for c in range(cols):
                item = self.table.item(r, c)
                row.append(item.text() if item is not None else '')
            grid.append(row)
        headers = [self.table.horizontalHeaderItem(c).text()
                   for c in range(cols)] if cols else []
        if transpose:
            out = [[h] + [grid[r][c] for r in range(rows)]
                   for c, h in enumerate(headers)]
            return out
        return [headers] + grid

    def _on_table_context_menu(self, pos):
        menu = QMenu(self.table)
        menu.addAction(QAction(tr('Copy Selection'), self.table,
                               triggered=self._copy_selection))
        menu.addAction(QAction(tr('Copy Table'), self.table,
                               triggered=lambda: self._copy_table(False)))
        menu.addSeparator()
        menu.addAction(QAction(tr('Export Table...'), self.table,
                               triggered=lambda: self._export_table(False)))
        menu.addSeparator()
        menu.addAction(QAction(tr('Copy Table Transposed'), self.table,
                               triggered=lambda: self._copy_table(True)))
        menu.addAction(QAction(tr('Export Table Transposed...'), self.table,
                               triggered=lambda: self._export_table(True)))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_selection(self):
        selected = self.table.selectedRanges()
        if not selected:
            return
        lines = []
        for rng in selected:
            for r in range(rng.topRow(), rng.bottomRow() + 1):
                line = []
                for c in range(rng.leftColumn(), rng.rightColumn() + 1):
                    item = self.table.item(r, c)
                    line.append(item.text() if item is not None else '')
                lines.append('\t'.join(line))
        QApplication.clipboard().setText('\n'.join(lines))

    def _copy_table(self, transpose: bool = False):
        data = self._table_data(transpose=transpose)
        text = '\n'.join('\t'.join(row) for row in data)
        QApplication.clipboard().setText(text)

    def _export_table(self, transpose: bool = False):
        path, _ = QFileDialog.getSaveFileName(
            self.table, 'Export Table', '',
            'Text Files (*.txt *.csv);;All Files (*)')
        if not path:
            return
        try:
            data = self._table_data(transpose=transpose)
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                for row in data:
                    f.write(self._csv_row(row) + '\n')
        except Exception as e:
            QMessageBox.critical(self.table, 'Export Error', str(e))

    @staticmethod
    def _csv_row(row: list[str]) -> str:
        return ','.join(
            '"' + cell.replace('"', '""') + '"' if any(
                ch in cell for ch in ',"\n') else cell
            for cell in row)
