"""日变化廓线控件：左侧 Windographer 风格控制面板 + 折线图/表格切换。

对齐原版 Diurnal Profile 标签页：
- Data column：多选通道复选列表（含派生 TI/WPD 计算列）+ Clear All；
- Display：Single profile / By month；Format：图/表图标按钮（独占一行）；
- Use only time steps containing data for all selected columns（折行两行显示）；
- Filter by：Flag（Include/Exclude + 具体标记）、Date（Year/Month 各自
  <All>）、Date range、Direction sector（扇区 + Sectors + Direction
  sensor）、Data column（Min/Max 限值）；
- 表格：Hour of Day 逐小时行，每通道 Mean (unit) / Time Steps 两列，
  右键菜单 Copy Selection / Copy Table / Export Table... /
  Copy Table Transposed / Export Table Transposed...。

配置经 Project.plot_settings['diurnal'] 随项目文件持久化。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup,
                               QCheckBox, QDateEdit, QDialog, QDoubleSpinBox,
                               QFileDialog, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QMenu, QMessageBox,
                               QPushButton, QRadioButton, QScrollArea,
                               QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from core.dataset import (KIND_DIR, KIND_SPEED, KIND_SPEED_SD,
                                  Dataset)
from core.diurnal import (DiurnalResult, compute_diurnal, ti_series,
                                  wpd_series)
from core.project import Project
from ui.modules.plot import PALETTE, PlotCanvas
from ui.modules.wind_rose_widget import (_SilentComboBox,
                                                 _chart_icon, _table_icon)
from core.i18n import tr

_SECTOR_ALL = 'all'
_TI_SUFFIX = ' TI'        # 湍流强度计算列（%），如 `Speed 160m W Avg TI`
_WPD_SUFFIX = ' WPD'      # 风功率密度计算列 (W/m²)


class DiurnalWidget(QWidget):
    """日变化廓线控件：左侧控制面板 + 右侧图/表 + 最右图例面板。"""

    CFG_KEY = 'diurnal'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Project | None = None
        self._result: DiurnalResult | None = None

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

        # ---- Data column 分组：多选通道 + Clear All ----
        col_group = QGroupBox(tr('Data column'))
        col_v = QVBoxLayout(col_group)
        col_v.setSpacing(4)
        col_v.setContentsMargins(4, 4, 4, 4)

        self._col_scroll = QScrollArea()
        self._col_scroll.setWidgetResizable(True)
        self._col_scroll.setFrameShape(QScrollArea.NoFrame)
        self._col_scroll.setFixedHeight(190)
        self._col_container = QWidget()
        self._col_layout = QVBoxLayout(self._col_container)
        self._col_layout.setContentsMargins(0, 0, 0, 0)
        self._col_layout.setSpacing(2)
        self._col_layout.addStretch(1)
        self._col_scroll.setWidget(self._col_container)
        col_v.addWidget(self._col_scroll)

        self.btn_clear_all = QPushButton(tr('Clear All'))
        self.btn_clear_all.setMaximumWidth(80)
        col_v.addWidget(self.btn_clear_all, 0, Qt.AlignLeft)
        panel_v.addWidget(col_group)
        self._col_checks: dict[str, QCheckBox] = {}

        # ---- Display 行（Format 独占下一行，面板更窄）----
        disp_row = QHBoxLayout()
        disp_row.setSpacing(6)
        disp_row.addWidget(QLabel(tr('Display')))
        self.rb_single = QRadioButton(tr('Single profile'))
        self.rb_month = QRadioButton(tr('By month'))
        self.rb_single.setChecked(True)
        disp_row.addWidget(self.rb_single)
        disp_row.addWidget(self.rb_month)
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

        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(6)
        fmt_row.addWidget(QLabel(tr('Format')))
        fmt_row.addWidget(self.btn_chart)
        fmt_row.addWidget(self.btn_table)
        fmt_row.addStretch(1)
        panel_v.addLayout(fmt_row)

        # ---- 共同时间步复选框：文字较长，两行折行显示 ----
        common_row = QHBoxLayout()
        common_row.setSpacing(6)
        common_row.setContentsMargins(0, 0, 0, 0)
        self.chk_common = QCheckBox()
        self.lbl_common = QLabel(
            tr('Use only time steps containing data for all selected columns'))
        self.lbl_common.setWordWrap(True)
        # 点文字等效点复选框（QCheckBox 原生不支持折行）
        self.lbl_common.mousePressEvent = lambda _evt: self.chk_common.toggle()
        common_row.addWidget(self.chk_common)
        common_row.addWidget(self.lbl_common, 1)
        panel_v.addLayout(common_row)

        # ---- Filter by 分组 ----
        filter_group = QGroupBox(tr('Filter by'))
        filter_v = QVBoxLayout(filter_group)
        filter_v.setSpacing(5)
        filter_v.setContentsMargins(4, 4, 4, 4)

        h_flag = QHBoxLayout()
        self.chk_flag = QCheckBox(tr('Flag'))
        self.cmb_flag = _SilentComboBox()          # Include / Exclude
        self.cmb_flag.addItem(tr('Include'), 'include')
        self.cmb_flag.addItem(tr('Exclude'), 'exclude')
        self.cmb_flag_name = _SilentComboBox()     # <Unflagged data> / 具体标记
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
        self.cmb_sector = _SilentComboBox()        # All / 1..N
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
        self.canvas = PlotCanvas('Mean Diurnal Profile')
        self.canvas.export_header = 'Mean Diurnal Profile'

        self.table_page = QWidget()
        table_v = QVBoxLayout(self.table_page)
        table_v.setContentsMargins(0, 0, 0, 0)
        table_v.setSpacing(4)
        self.table = QTableWidget()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        self.table.verticalHeader().setVisible(False)
        # 表头行画在表格内部（跨行/跨列单元格），原生横向表头隐藏，
        # 但保留其 section 管理以驱动列宽模式
        self.table.horizontalHeader().setVisible(False)
        table_v.addWidget(self.table)
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.table_page)

        main_h.addWidget(scroll)
        main_h.addWidget(self.stack, 1)

        # ---- 最右图例面板（带复选框，与 Wind Rose 标签页一致）----
        self.legend_panel = QWidget(self)
        self.legend_panel.setMinimumWidth(170)
        self.legend_panel.setMaximumWidth(260)
        legend_v = QVBoxLayout(self.legend_panel)
        legend_v.setContentsMargins(4, 4, 4, 4)
        legend_v.setSpacing(4)
        self.legend_scroll = QScrollArea(self.legend_panel)
        self.legend_scroll.setWidgetResizable(True)
        self.legend_scroll.setFrameShape(QScrollArea.NoFrame)
        self.legend_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.legend_container = QWidget()
        self.legend_layout = QVBoxLayout(self.legend_container)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(3)
        self.legend_layout.addStretch(1)
        self.legend_scroll.setWidget(self.legend_container)
        legend_v.addWidget(self.legend_scroll)
        main_h.addWidget(self.legend_panel)
        self._legend_checks: list[tuple[str, QCheckBox]] = []

        # ---- 信号 ----
        self.btn_clear_all.clicked.connect(self._on_clear_all)
        self.rb_single.toggled.connect(self._on_cfg_changed)
        self.rb_month.toggled.connect(self._on_cfg_changed)
        self.btn_chart.toggled.connect(self._on_format_toggled)
        self.btn_table.toggled.connect(self._on_format_toggled)
        self.chk_common.stateChanged.connect(self._on_cfg_changed)

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
        # 程序化填充期间屏蔽信号，避免 toggled/currentIndexChanged 触发
        # _save_project_cfg 把已保存的选择覆盖成控件初值
        self._block_cfg_signals(True)
        try:
            ds = self._active_dataset()
            if ds is not None and not ds.df.empty:
                self._rebuild_column_list()
                self._refresh_flag_names()
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
            self.rb_single, self.rb_month,
            self.btn_chart, self.btn_table, self.chk_common,
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
        (self.rb_single if cfg.get('display', 'single') == 'single'
         else self.rb_month).setChecked(True)
        columns = cfg.get('columns')
        if columns is None:
            # 无保存配置时默认勾选全部风速 Avg 通道
            ds = self._active_dataset()
            columns = [n for n, ch in (ds.channels.items() if ds else [])
                       if ch.kind == KIND_SPEED
                       and getattr(ch, 'role', 'Avg') == 'Avg'] or \
                      list(self._col_checks.keys())
        for name, cb in self._col_checks.items():
            cb.blockSignals(True)
            cb.setChecked(name in columns)
            cb.blockSignals(False)
        self.chk_common.setChecked(cfg.get('use_common', False))

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
        cfg = {
            'display': 'single' if self.rb_single.isChecked() else 'month',
            'columns': [n for n, cb in self._col_checks.items()
                        if cb.isChecked()],
            'use_common': self.chk_common.isChecked(),
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
        # 保留图例样式（channel_styles 由图例开关/Properties 维护）
        old = self._current_cfg()
        styles = old.get('channel_styles') if isinstance(old, dict) else None
        if isinstance(styles, dict):
            cfg['channel_styles'] = dict(styles)
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
        """派生计算列名：有 SD 配对的风速 Avg → `... TI`；全部风速 Avg → `... WPD`。

        与原版一致：先列全部 TI，再列全部 WPD，附在普通通道之后。"""
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

    def _rebuild_column_list(self):
        ds = self._active_dataset()
        for cb in self._col_checks.values():
            cb.hide()           # 先隐藏再销毁，避免重建瞬间新旧条目重叠
            cb.deleteLater()
        self._col_checks.clear()
        while self._col_layout.count():
            item = self._col_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._col_layout.addStretch(1)
        if ds is None:
            return
        for name in list(ds.channels.keys()) + self._computed_entries(ds):
            cb = QCheckBox(name)
            cb.toggled.connect(self._on_cfg_changed)
            self._col_checks[name] = cb
            self._col_layout.insertWidget(self._col_layout.count() - 1, cb)

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

    def _sync_limit_suffix(self):
        """Min/Max 限值框单位后缀（随 Data column 过滤列的通道单位）。"""
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
        # 随任一过滤条件变化同步启用/禁用耦合（如选了具体扇区 → Direction sensor 可用）
        self._update_filter_enabled()
        self._save_project_cfg()
        self.refresh()

    def _on_format_toggled(self):
        self.stack.setCurrentIndex(0 if self.btn_chart.isChecked() else 1)
        self._save_project_cfg()
        self.refresh()

    def _on_clear_all(self):
        for cb in self._col_checks.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self._on_cfg_changed()

    def _on_range_check_changed(self, state: int):
        # stateChanged 传 int，不能与 Qt.Checked 枚举直接比较（恒 False），
        # 一律以 isChecked() 为准
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

    def _on_legend_toggled(self, index: int, checked: bool):
        if self.project is None:
            return
        cfg = self._current_cfg()
        styles = dict(cfg.get('channel_styles') or {})
        st = dict(styles.get(str(index)) or {})
        st['visible'] = checked
        styles[str(index)] = st
        self.project.set_plot_setting(
            self.CFG_KEY, {**cfg, 'channel_styles': styles})
        self.refresh()

    # ------------------------------------------------------------------
    # 过滤
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
                mask &= df.index <= pd.Timestamp(dr['to']) + pd.Timedelta(days=1) \
                    - pd.Timedelta(seconds=1)

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
    # 刷新（绘图 + 表格 + 图例）
    # ------------------------------------------------------------------
    def refresh(self):
        ds = self._active_dataset()
        if ds is None or ds.df.empty:
            self.canvas.clear(tr('未载入数据集'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self._update_legend_panel([], [])
            return

        selected = [n for n, cb in self._col_checks.items() if cb.isChecked()]
        if not selected:
            self.canvas.clear(tr('请选择数据列'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self._update_legend_panel([], [])
            return

        by_month = self.rb_month.isChecked()
        filter_mask = self._build_filter_mask(ds)

        # 拆分实列与计算列（TI/WPD 按需派生，参与同一过滤与统计）
        real_cols: list[str] = []
        extra: dict[str, pd.Series] = {}
        temp_col = (self.project.selection.get('temp') if self.project else None)
        pres_col = (self.project.selection.get('pres') if self.project else None)
        for n in selected:
            if n in ds.df.columns:
                real_cols.append(n)
            elif n.endswith(_TI_SUFFIX):
                base = n[:-len(_TI_SUFFIX)]
                sd = self._sd_partner(ds, base)
                if sd is None:
                    continue
                extra[n] = ti_series(ds.df, base, sd)
            elif n.endswith(_WPD_SUFFIX):
                base = n[:-len(_WPD_SUFFIX)]
                if base not in ds.df.columns:
                    continue
                extra[n] = wpd_series(ds.df, base, temp_col, pres_col)
        columns = real_cols + [n for n in selected if n in extra]
        if not columns:
            self.canvas.clear(tr('请选择数据列'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        result = compute_diurnal(
            ds.df, columns, by_month=by_month,
            filter_mask=filter_mask,
            use_common=self.chk_common.isChecked(),
            extra=extra)
        self._result = result
        if result is None:
            self.canvas.clear(tr('计算失败'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        cfg = self._current_cfg()
        styles_cfg = cfg.get('channel_styles') or {}
        labels = result.labels
        styles = []
        for j, lab in enumerate(labels):
            st = dict(styles_cfg.get(str(j)) or {})
            styles.append(st)

        self._update_legend_panel(labels, styles)

        visible_idx = [j for j, st in enumerate(styles)
                       if st.get('visible', True) is not False]
        if not visible_idx:
            self.canvas.clear(tr('未选择系列'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        if self.btn_table.isChecked():
            self._fill_table(result, visible_idx)
            self.stack.setCurrentIndex(1)
            return
        self.stack.setCurrentIndex(0)

        unit = self._unit_of(selected[0])
        title = ('Mean Diurnal Profile by Month' if by_month
                 else 'Mean Diurnal Profile')
        self.canvas.set_title(title)
        series = [(labels[j], np.arange(24, dtype=float),
                   result.means[:, j]) for j in visible_idx]
        qty = self._quantity_name(selected)
        ylabel = f'Mean {qty}' if qty == 'Value' \
            else f'Mean {qty}{unit}'
        self.canvas.plot_lines(
            series, xlabel='Hour of Day', ylabel=ylabel,
            xtick_fmt='hour', ymin=0, gap_detect=False, show_legend=False)

    def _unit_of(self, col: str) -> str:
        if col.endswith(_TI_SUFFIX):
            return ' (%)'
        if col.endswith(_WPD_SUFFIX):
            return ' (W/m²)'
        ds = self._active_dataset()
        ch = ds.channels.get(col) if ds else None
        if ch is not None and ch.units:
            return f' ({ch.units})'
        return ' (m/s)' if (ch is not None and ch.kind == KIND_SPEED) else ''

    def _quantity_name(self, cols: list[str]) -> str:
        """按所选通道类型给 y 轴命名（全部同类型时用具体名称）。"""
        ds = self._active_dataset()
        kinds = set()
        for c in cols:
            if c.endswith(_TI_SUFFIX):
                kinds.add('ti')
            elif c.endswith(_WPD_SUFFIX):
                kinds.add('wpd')
            elif ds and c in ds.channels:
                kinds.add(ds.channels[c].kind)
        name_map = {'speed': 'Wind Speed', 'dir': 'Direction',
                    'temp': 'Temperature', 'pres': 'Pressure',
                    'rh': 'Relative Humidity', 'wz': 'Vertical Wind Speed',
                    'ti': 'TI', 'wpd': 'Wind Power Density'}
        if len(kinds) == 1:
            return name_map.get(kinds.pop(), 'Value')
        return 'Value'

    # ------------------------------------------------------------------
    # 图例面板（与 WindRoseWidget 相同的就地更新策略）
    # ------------------------------------------------------------------
    def _update_legend_panel(self, labels: list[str], styles: list[dict]):
        existing = [lab for lab, _ in self._legend_checks]
        if existing and existing == list(labels):
            for j, (lab, chk) in enumerate(self._legend_checks):
                st = styles[j] if j < len(styles) else {}
                visible = st.get('visible', True) is not False
                chk.blockSignals(True)
                chk.setChecked(visible)
                chk.setStyleSheet(f'color: {self._resolve_color(st, j)};')
                chk.blockSignals(False)
            return

        for _, chk in self._legend_checks:
            chk.hide()          # 先隐藏再销毁，避免重建瞬间新旧条目重叠
            chk.deleteLater()
        self._legend_checks.clear()
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.legend_layout.addStretch(1)

        for j, lab in enumerate(labels):
            st = styles[j] if j < len(styles) else {}
            visible = st.get('visible', True) is not False
            chk = QCheckBox(lab)
            chk.setChecked(visible)
            chk.setStyleSheet(f'color: {self._resolve_color(st, j)};')
            chk.stateChanged.connect(
                lambda state, idx=j: self._on_legend_toggled(idx, bool(state)))
            self._legend_checks.append((lab, chk))
            self.legend_layout.insertWidget(self.legend_layout.count() - 1, chk)

    @staticmethod
    def _resolve_color(st: dict, index: int) -> str:
        color = st.get('color')
        # None 或 '' 均视为"自动取调色板"，避免空串被解析成黑色
        if not color:
            color = PALETTE[index % len(PALETTE)]
            return color.name() if hasattr(color, 'name') else str(color)
        if hasattr(color, 'name'):
            return color.name()
        return str(color)

    # ------------------------------------------------------------------
    # 表格视图（两级表头：通道名跨 2 列 + Mean/Time Steps 子表头）
    # ------------------------------------------------------------------
    def _fill_table(self, result: DiurnalResult, visible_idx: list[int]):
        k = len(visible_idx)
        n_rows = 24 + 2                       # 两行表头 + 24 小时
        self.table.clear()
        self.table.setColumnCount(1 + 2 * k)
        self.table.setRowCount(n_rows)

        bold = QFont()
        bold.setBold(True)
        header_bg = QBrush(QColor('#e8f0fb'))

        def _head_item(text: str) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            item.setFont(bold)
            item.setBackground(header_bg)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            return item

        # 行 0-1：表头。Hour of Day 竖跨两行；通道名横跨两列。
        self.table.setItem(0, 0, _head_item('Hour of Day'))
        self.table.setSpan(0, 0, 2, 1)
        for j, idx in enumerate(visible_idx):
            name = result.labels[idx]
            c = 1 + 2 * j
            self.table.setItem(0, c, _head_item(name))
            self.table.setSpan(0, c, 1, 2)
            unit = self._unit_of(name.split(' M')[0] if result.by_month
                                 else name)
            self.table.setItem(1, c, _head_item(f'Mean{unit}'))
            self.table.setItem(1, c + 1, _head_item('Time Steps'))

        # 数据行
        for h in range(24):
            r = 2 + h
            hour_item = QTableWidgetItem(f'{h:02d}:00 - {h + 1:02d}:00')
            hour_item.setFlags(hour_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 0, hour_item)
            for j, idx in enumerate(visible_idx):
                v = result.means[h, idx]
                txt = '' if not (v == v) else f'{v:.3f}'
                item = QTableWidgetItem(txt)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, 1 + 2 * j, item)
                s = int(result.steps[h, idx])
                item = QTableWidgetItem(str(s))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, 2 + 2 * j, item)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        self.table.resizeColumnsToContents()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for c in range(1, self.table.columnCount()):
            header.setSectionResizeMode(c, QHeaderView.Stretch)

    # ------------------------------------------------------------------
    # 表格右键菜单（对齐原版：Copy / Export / Transposed）
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
            # 转置：第 0 列（Hour of Day / 表头占位）作为行首标签列
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
