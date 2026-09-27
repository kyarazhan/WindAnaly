"""频率分布控件：左侧 Windographer 风格控制面板 + 直方图/表格切换。

对齐原版 Histogram 标签页：
- Display：frequency / occurrences；Format：图/表图标按钮；
- Versus：one data column / data column and month / data column and
  hour of day / two data columns；
- Primary bins：数据列下拉（含派生 TI/WPD 计算列）+ Width/Start at/
  Make first bin half this width；
- Filter by：Flag、Date、Date range、Direction sector、Data column
  Min/Max（与 Diurnal Profile 相同的一套过滤）；
- 图：frequency 模式叠加 Best-fit Weibull 曲线 + 底部图例；
- 表格：Bin | Bin Endpoints (Lower/Upper) | Occurrences | Frequency [%]。

配置经 Project.plot_settings['histogram'] 随项目文件持久化。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup,
                               QCheckBox, QComboBox, QDateEdit, QDialog,
                               QDoubleSpinBox, QFileDialog, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QMenu,
                               QMessageBox, QPushButton, QRadioButton,
                               QScrollArea, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

from core.dataset import KIND_DIR, KIND_SPEED, Dataset
from core.diurnal import ti_series, wpd_series
from core.histogram import (HistogramResult, compute_histogram,
                                    weibull_pdf)
from core.project import Project
from ui.modules.diurnal_widget import (_TI_SUFFIX, _WPD_SUFFIX,
                                               _SECTOR_ALL)
from ui.modules.plot import PlotCanvas
from ui.modules.wind_rose_widget import (_SilentComboBox,
                                                 _chart_icon, _table_icon)
from core.i18n import tr

_VERSUS_MODES = [
    ('one', 'one data column'),
    ('month', 'data column and month'),
    ('hour', 'data column and hour of day'),
    ('two', 'two data columns'),
]


class HistogramWidget(QWidget):
    """频率分布控件：左侧控制面板 + 右侧图/表。"""

    CFG_KEY = 'histogram'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Project | None = None
        self._result: HistogramResult | None = None

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

        # ---- Display 行 ----
        disp_row = QHBoxLayout()
        disp_row.setSpacing(6)
        disp_row.addWidget(QLabel(tr('Display')))
        self.rb_freq = QRadioButton(tr('frequency'))
        self.rb_occ = QRadioButton(tr('occurrences'))
        self.rb_freq.setChecked(True)
        disp_row.addWidget(self.rb_freq)
        disp_row.addWidget(self.rb_occ)
        disp_row.addStretch(1)
        panel_v.addLayout(disp_row)
        self.btn_chart = QToolButton()
        self.btn_chart.setIcon(_chart_icon())
        self.btn_chart.setCheckable(True)
        self.btn_chart.setChecked(True)
        self.btn_chart.setFixedSize(26, 26)
        self.btn_chart.setToolTip('Chart')
        self.btn_table = QToolButton()
        self.btn_table.setIcon(_table_icon())
        self.btn_table.setCheckable(True)
        self.btn_table.setFixedSize(26, 26)
        self.btn_table.setToolTip('Table')
        self._format_group = QButtonGroup(self)
        self._format_group.addButton(self.btn_chart, 0)
        self._format_group.addButton(self.btn_table, 1)
        self._format_group.setExclusive(True)

        # Format 独占一行（面板窄，与 Display 同行放不下）
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(6)
        fmt_row.addWidget(QLabel(tr('Format')))
        fmt_row.addWidget(self.btn_chart)
        fmt_row.addWidget(self.btn_table)
        fmt_row.addStretch(1)
        panel_v.addLayout(fmt_row)

        # Qt 对同父控件的单选钮自动互斥：Display 与 Versus 必须各自成组，
        # 否则选 Versus 会取消 Display 的勾选
        self._display_group = QButtonGroup(self)
        self._display_group.addButton(self.rb_freq)
        self._display_group.addButton(self.rb_occ)
        self._display_group.setExclusive(True)

        # ---- Versus（四个单选竖排，独立互斥组）----
        panel_v.addWidget(QLabel(tr('versus')))
        self.rb_v_one = QRadioButton(tr('one data column'))
        self.rb_v_month = QRadioButton(tr('data column and month'))
        self.rb_v_hour = QRadioButton(tr('data column and hour of day'))
        self.rb_v_two = QRadioButton(tr('two data columns'))
        self.rb_v_one.setChecked(True)
        for rb in (self.rb_v_one, self.rb_v_month, self.rb_v_hour,
                   self.rb_v_two):
            panel_v.addWidget(rb)
        self._versus_group = QButtonGroup(self)
        self._versus_group.addButton(self.rb_v_one)
        self._versus_group.addButton(self.rb_v_month)
        self._versus_group.addButton(self.rb_v_hour)
        self._versus_group.addButton(self.rb_v_two)
        self._versus_group.setExclusive(True)

        # ---- Primary bins ----
        pb_row = QHBoxLayout()
        pb_row.setSpacing(6)
        pb_row.addWidget(QLabel(tr('Primary bins')))
        self.cmb_col = _SilentComboBox()
        pb_row.addWidget(self.cmb_col, 1)
        panel_v.addLayout(pb_row)

        # versus=two 时的第二数据列（仅该模式显示）
        self.cmb_col2 = _SilentComboBox()
        self.cmb_col2.addItem('—', '')
        panel_v.addWidget(self.cmb_col2)
        self.cmb_col2.setVisible(False)

        # ---- 分箱设置 ----
        h_width = QHBoxLayout()
        h_width.setSpacing(6)
        self.chk_width = QCheckBox(tr('Width'))
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.1, 50)
        self.spin_width.setDecimals(1)
        self.spin_width.setValue(0.5)
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

        # Make first bin half this width：长文字两行折行（点文字等效点框）
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

        # ---- Filter by 分组（与 Diurnal Profile 同一套）----
        filter_group = QGroupBox(tr('Filter by'))
        filter_v = QVBoxLayout(filter_group)
        filter_v.setSpacing(5)
        filter_v.setContentsMargins(4, 4, 4, 4)

        h_flag = QHBoxLayout()
        self.chk_flag = QCheckBox(tr('Flag'))
        self.cmb_flag = _SilentComboBox()
        self.cmb_flag.addItem(tr('Include'), 'include')
        self.cmb_flag.addItem(tr('Exclude'), 'exclude')
        self.cmb_flag_name = _SilentComboBox()
        self.cmb_flag_name.setMinimumWidth(80)
        h_flag.addWidget(self.chk_flag)
        h_flag.addWidget(self.cmb_flag)
        h_flag.addWidget(self.cmb_flag_name, 1)
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
        panel_v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(self._panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        # ---- 右侧图形 / 表格 ----
        self.stack = QStackedWidget()
        self.canvas = PlotCanvas('Probability Distribution Function')
        self.canvas.export_header = 'Probability Distribution Function'

        self.table_page = QWidget()
        table_v = QVBoxLayout(self.table_page)
        table_v.setContentsMargins(0, 0, 0, 0)
        table_v.setSpacing(4)
        self.table = QTableWidget()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(
            self._on_table_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setVisible(False)
        table_v.addWidget(self.table)
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.table_page)

        main_h.addWidget(scroll)
        main_h.addWidget(self.stack, 1)

        # ---- 信号 ----
        self.rb_freq.toggled.connect(self._on_cfg_changed)
        self.rb_occ.toggled.connect(self._on_cfg_changed)
        self.btn_chart.toggled.connect(self._on_format_toggled)
        self.btn_table.toggled.connect(self._on_format_toggled)
        for rb in (self.rb_v_one, self.rb_v_month, self.rb_v_hour,
                   self.rb_v_two):
            rb.toggled.connect(self._on_cfg_changed)
        self.cmb_col.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_col2.currentIndexChanged.connect(self._on_cfg_changed)
        self.chk_width.stateChanged.connect(self._on_width_check_changed)
        self.spin_width.valueChanged.connect(self._on_cfg_changed)
        self.chk_start.stateChanged.connect(self._on_start_check_changed)
        self.spin_start.valueChanged.connect(self._on_cfg_changed)
        self.chk_half.stateChanged.connect(self._on_cfg_changed)

        self.chk_flag.stateChanged.connect(self._on_cfg_changed)
        self.cmb_flag.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_flag_name.currentIndexChanged.connect(self._on_cfg_changed)
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
                self._refresh_col_list()
                self._refresh_flag_names()
                self._refresh_year_month_lists()
                self._refresh_sensor_list()
                self._refresh_filter_data_list()
                self._init_date_range()
                self._sync_units()
                self._load_project_cfg()
                self.refresh()
        finally:
            self._block_cfg_signals(False)
        # versus 模式驱动第二列下拉可见性（放在信号屏蔽外，避免误存配置）
        self.cmb_col2.setVisible(self.rb_v_two.isChecked())

    def _active_dataset(self) -> Dataset | None:
        if self.project is None:
            return None
        return self.project.active_dataset

    def _block_cfg_signals(self, block: bool):
        widgets = [
            self.rb_freq, self.rb_occ, self.btn_chart, self.btn_table,
            self.rb_v_one, self.rb_v_month, self.rb_v_hour, self.rb_v_two,
            self.cmb_col, self.cmb_col2,
            self.chk_width, self.spin_width, self.chk_start, self.spin_start,
            self.chk_half,
            self.chk_flag, self.cmb_flag, self.cmb_flag_name,
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
        (self.rb_freq if cfg.get('display', 'frequency') == 'frequency'
         else self.rb_occ).setChecked(True)
        v = cfg.get('versus', 'one')
        {'one': self.rb_v_one, 'month': self.rb_v_month,
         'hour': self.rb_v_hour, 'two': self.rb_v_two}[v].setChecked(True)
        col = cfg.get('col')
        if col and self.cmb_col.findData(col) >= 0:
            self.cmb_col.setCurrentIndexByData(col)
        self.chk_width.setChecked(cfg.get('use_width', False))
        self.spin_width.setValue(float(cfg.get('width', 0.5)))
        self.chk_start.setChecked(cfg.get('use_start', False))
        self.spin_start.setValue(float(cfg.get('start', 0.0)))
        self.chk_half.setChecked(cfg.get('half_first', False))

        f = cfg.get('filter', {})
        self.chk_flag.setChecked(f.get('use_flag', False))
        self.cmb_flag.setCurrentIndexByData(f.get('flag_mode', 'include'))
        self.cmb_flag_name.setCurrentIndexByData(f.get('flag_name', ''))
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

        fmt = cfg.get('format', 'chart')
        self.btn_chart.setChecked(fmt == 'chart')
        self.btn_table.setChecked(fmt == 'table')
        self._update_filter_enabled()

    def _save_project_cfg(self):
        if self.project is None:
            return
        versus = ('month' if self.rb_v_month.isChecked() else
                  'hour' if self.rb_v_hour.isChecked() else
                  'two' if self.rb_v_two.isChecked() else 'one')
        cfg = {
            'display': 'frequency' if self.rb_freq.isChecked()
            else 'occurrences',
            'versus': versus,
            'col': self.cmb_col.currentData() or '',
            'use_width': self.chk_width.isChecked(),
            'width': self.spin_width.value(),
            'use_start': self.chk_start.isChecked(),
            'start': self.spin_start.value(),
            'half_first': self.chk_half.isChecked(),
            'filter': {
                'use_flag': self.chk_flag.isChecked(),
                'flag_mode': self.cmb_flag.currentData(),
                'flag_name': self.cmb_flag_name.currentData() or '',
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
            'format': 'chart' if self.btn_chart.isChecked() else 'table',
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
        """派生计算列名（与 Diurnal 一致：先全部 TI，再全部 WPD）。"""
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

    def _refresh_col_list(self):
        """Primary bins 下拉：全部通道 + TI/WPD 计算列（对齐原版截图）。"""
        self.cmb_col.clear()
        self.cmb_col2.clear()
        self.cmb_col2.addItem('—', '')
        ds = self._active_dataset()
        if ds is None:
            return
        for name in list(ds.channels.keys()) + self._computed_entries(ds):
            self.cmb_col.addItem(name, name)
            self.cmb_col2.addItem(name, name)

    def _refresh_flag_names(self):
        self.cmb_flag_name.clear()
        self.cmb_flag_name.addItem('<Unflagged data>', '')
        ds = self._active_dataset()
        if ds is None:
            return
        for name in getattr(ds, 'flag_registry', {}):
            self.cmb_flag_name.addItem(name, name)

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

    def _sync_units(self):
        """Width/Start at 的单位标签随 Primary bins 列的通道单位。"""
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

    def _on_format_toggled(self):
        self.stack.setCurrentIndex(0 if self.btn_chart.isChecked() else 1)
        self._save_project_cfg()
        self.refresh()

    def _on_width_check_changed(self, state: int):
        # stateChanged 传 int，不能与 Qt.Checked 枚举直接比较（恒 False），
        # 一律以 isChecked() 为准
        self.spin_width.setEnabled(self.chk_width.isChecked())
        self._on_cfg_changed()

    def _on_start_check_changed(self, state: int):
        self.spin_start.setEnabled(self.chk_start.isChecked())
        self._on_cfg_changed()

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
        self.cmb_flag.setEnabled(enabled)
        self.cmb_flag_name.setEnabled(enabled)
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

    # ------------------------------------------------------------------
    # 过滤（与 Diurnal Profile 同一套）
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
            mode = cfg.get('flag_mode', 'include')
            flag_name = cfg.get('flag_name', '')
            if flag_name:
                fm = getattr(ds, 'flag_masks', {}).get(flag_name)
                if fm is not None and len(fm) == len(df):
                    flag_mask = fm.astype(bool)
                else:
                    flag_mask = pd.Series(False, index=df.index)
                mask &= flag_mask if mode == 'include' else ~flag_mask
            else:
                flags = getattr(ds, 'flags', None)
                if flags is not None and len(flags) == len(df):
                    flags = flags.astype(bool)
                    mask &= ~flags if mode == 'include' else flags

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

    def refresh(self):
        ds = self._active_dataset()
        if ds is None or ds.df.empty:
            self.canvas.clear(tr('未载入数据集'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        col = self.cmb_col.currentData()
        if not col:
            self.canvas.clear(tr('请选择数据列'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        versus = ('month' if self.rb_v_month.isChecked() else
                  'hour' if self.rb_v_hour.isChecked() else
                  'two' if self.rb_v_two.isChecked() else 'one')
        self.cmb_col2.setVisible(versus == 'two')
        col2 = self.cmb_col2.currentData() if versus == 'two' else None
        if versus == 'two' and not col2:
            self.canvas.clear(tr('请选择第二数据列'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        # 计算列按需派生（TI/WPD），与实列走同一过滤
        extra: dict[str, pd.Series] = {}
        if col.endswith(_TI_SUFFIX):
            base = col[:-len(_TI_SUFFIX)]
            sd = self._sd_partner(ds, base)
            if sd is None:
                self.canvas.clear(tr('缺少配对的 SD 通道，无法计算 TI'))
                return
            extra[col] = ti_series(ds.df, base, sd)
        elif col.endswith(_WPD_SUFFIX):
            base = col[:-len(_WPD_SUFFIX)]
            temp_col = (self.project.selection.get('temp')
                        if self.project else None)
            pres_col = (self.project.selection.get('pres')
                        if self.project else None)
            extra[col] = wpd_series(ds.df, base, temp_col, pres_col)

        result = compute_histogram(
            ds.df, col, col2=col2, versus=versus,
            bin_width=self.spin_width.value() if self.chk_width.isChecked()
            else None,
            bin_start=self.spin_start.value() if self.chk_start.isChecked()
            else None,
            half_first=self.chk_half.isChecked(),
            filter_mask=self._build_filter_mask(ds),
            extra=extra,
            unit=self._col_unit(col))
        self._result = result
        if result is None:
            self.canvas.clear(tr('计算失败'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        if self.btn_table.isChecked():
            self._fill_table(result)
            self.stack.setCurrentIndex(1)
            return
        self.stack.setCurrentIndex(0)

        self.canvas.set_title('Probability Distribution Function')
        freq_mode = self.rb_freq.isChecked()
        mat = result.freq if freq_mode else result.occ
        ylabel = 'Frequency (%)' if freq_mode else 'Occurrences'
        thousands = not freq_mode

        if versus == 'one':
            overlay = None
            legend = None
            if freq_mode and result.weibull:
                k, c = result.weibull['k'], result.weibull['c']
                width = float(np.median(np.diff(result.edges)))
                xs = np.linspace(float(result.edges[0]),
                                 float(result.edges[-1]), 200)
                ys = weibull_pdf(xs, k, c) * width * 100.0
                overlay = (xs, ys, '#333333',
                           f'Best-fit Weibull distribution')
                legend = [('#1a4e8a', 'Actual data'),
                          ('#333333',
                           f'Best-fit Weibull distribution '
                           f'(k={k:.2f}, c={c:.2f} {self._col_unit(col)})')]
            self.canvas.plot_histogram(
                result.edges, mat[:, 0],
                xlabel=result.x_label, ylabel=ylabel, ymin=0,
                overlay=overlay, legend=legend, thousands=thousands)
            return

        # 多系列：逐系列画折线（bins 中心为 x），内嵌图例
        centers = (result.edges[:-1] + result.edges[1:]) / 2.0
        series = [(lab, centers, mat[:, i])
                  for i, lab in enumerate(result.labels)]
        self.canvas.plot_lines(
            series, xlabel=result.x_label, ylabel=ylabel, ymin=0)

    # ------------------------------------------------------------------
    # 表格视图（两级表头：Bin Endpoints 跨 Lower/Upper）
    # ------------------------------------------------------------------
    def _fill_table(self, result: HistogramResult):
        n = len(result.edges) - 1
        multi = len(result.labels) > 1
        cols = 1 + 2 + (2 * len(result.labels) if multi else 2)
        rows = n + 2
        self.table.clear()
        self.table.setColumnCount(cols)
        self.table.setRowCount(rows)

        bold = QFont()
        bold.setBold(True)
        header_bg = QBrush(QColor('#e8f0fb'))

        def _head(item_text: str) -> QTableWidgetItem:
            item = QTableWidgetItem(item_text)
            item.setFont(bold)
            item.setBackground(header_bg)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            return item

        unit = result.unit
        ep_label = f'Bin Endpoints ({unit})' if unit else 'Bin Endpoints'
        self.table.setItem(0, 0, _head('Bin'))
        self.table.setSpan(0, 0, 2, 1)
        self.table.setItem(0, 1, _head(ep_label))
        self.table.setSpan(0, 1, 1, 2)
        self.table.setItem(1, 1, _head('Lower'))
        self.table.setItem(1, 2, _head('Upper'))
        if multi:
            for i, lab in enumerate(result.labels):
                c = 3 + 2 * i
                self.table.setItem(0, c, _head(lab))
                self.table.setSpan(0, c, 1, 2)
                self.table.setItem(1, c, _head('Occurrences'))
                self.table.setItem(1, c + 1, _head('Frequency [%]'))
        else:
            self.table.setItem(0, 3, _head('Occurrences'))
            self.table.setSpan(0, 3, 2, 1)
            self.table.setItem(0, 4, _head('Frequency [%]'))
            self.table.setSpan(0, 4, 2, 1)

        for i in range(n):
            r = 2 + i
            bin_item = QTableWidgetItem(str(i + 1))
            bin_item.setFlags(bin_item.flags() & ~Qt.ItemIsEditable)
            bin_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 0, bin_item)
            lo_item = QTableWidgetItem(f'{result.edges[i]:.1f}')
            lo_item.setFlags(lo_item.flags() & ~Qt.ItemIsEditable)
            lo_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 1, lo_item)
            up_item = QTableWidgetItem(f'{result.edges[i + 1]:.1f}')
            up_item.setFlags(up_item.flags() & ~Qt.ItemIsEditable)
            up_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 2, up_item)
            for j in range(len(result.labels)):
                c = 3 + 2 * j if multi else 3
                occ = int(result.occ[i, j])
                occ_item = QTableWidgetItem(f'{occ:,}')
                occ_item.setFlags(occ_item.flags() & ~Qt.ItemIsEditable)
                occ_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, occ_item)
                fr_item = QTableWidgetItem(f'{result.freq[i, j]:.3f}')
                fr_item.setFlags(fr_item.flags() & ~Qt.ItemIsEditable)
                fr_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c + 1, fr_item)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        # 对齐原版：列宽按内容自适应，右侧留白（不拉伸占满）
        self.table.resizeColumnsToContents()
        # resizeColumnsToContents 不感知跨列单元格，且 ResizeToContents 模式下
        # setColumnWidth 无效：先转 Interactive 再兜底表头宽度
        fm = self.table.fontMetrics()

        def _ensure(col: int, need: int):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            if self.table.columnWidth(col) < need:
                self.table.setColumnWidth(col, need)

        _ensure(0, fm.horizontalAdvance('Bin') + 16)
        ep_text = f'Bin Endpoints ({unit})' if unit else 'Bin Endpoints'
        half = (fm.horizontalAdvance(ep_text) + 20) // 2
        _ensure(1, half)
        _ensure(2, half)
        _ensure(1, fm.horizontalAdvance('Lower') + 16)
        _ensure(2, fm.horizontalAdvance('Upper') + 16)
        if multi:
            for lab in result.labels:
                w_half = (fm.horizontalAdvance(lab) + 20) // 2
                for c in range(3, cols):
                    _ensure(c, w_half)
        _ensure(3, fm.horizontalAdvance('Occurrences') + 16)
        _ensure(4, fm.horizontalAdvance('Frequency [%]') + 16)

    # ------------------------------------------------------------------
    # 表格右键菜单（与 Diurnal 同一套）
    # ------------------------------------------------------------------
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
        if transpose:
            out = []
            for c in range(cols):
                out.append([grid[r][c] for r in range(rows)])
            return out
        return grid

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
