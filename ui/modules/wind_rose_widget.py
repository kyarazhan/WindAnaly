"""风玫瑰图控件：左侧 Windographer 风格控制面板 + 极坐标图/表格切换。

Display: occurrences / frequency / mean / min / max / std_dev / total_energy / scatter_plot
Versus: direction / direction_and_month / direction_and_hour / direction_and_bin
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup,
                               QCheckBox, QComboBox, QDateEdit, QDialog,
                               QFileDialog,
                               QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QRadioButton,
                               QScrollArea, QSizePolicy, QSpinBox,
                               QStackedWidget, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from core import settings
from core.dataset import KIND_DIR, KIND_SPEED, Dataset
from core.project import Project
from core.wind_rose import (DISPLAY_TYPES, RoseResult, VERSUS_TYPES,
                                    compute_rose)
from ui.modules.plot import PALETTE, PlotCanvas
from core.i18n import tr

_DIR_ALL = '__ALL__'

# 规范名 → 中文显示映射（仅用于 Wind Rose 界面展示，内部存储仍为英文规范名）
_KIND_CN = {
    'Speed': '风速', 'Dir': '风向', 'Temp': '气温', 'Pres': '气压',
    'RH': '相对湿度', 'Wz': '垂直风速', 'other': '其它',
}
_STAT_CN = {
    'Avg': '均值', 'SD': '标准差', 'Min': '最小', 'Max': '最大',
    'Gust': '阵风', '': '',
}
_ORIENT_CN = {
    'NE': '东北', 'NW': '西北', 'SE': '东南', 'SW': '西南',
    'N': '北', 'E': '东', 'S': '南', 'W': '西',
    '': '水平',
}


def _channel_display_name(name: str, ds: Dataset | None = None) -> str:
    """中文模式：把英文规范通道名转换为中文显示名
    （如 `Dir 180m N Avg` → `180m北风向 [均值]`）；英文模式原样返回规范名。

    若通道在 Dataset 注册表中有 label 字段，优先使用该 label。
    """
    if ds is not None:
        ch = ds.channels.get(name)
        if ch is not None and getattr(ch, 'label', ''):
            return ch.label
    from core.i18n import language
    if language() == 'en':
        return name
    parts = name.split()
    if not parts:
        return name
    kind = _KIND_CN.get(parts[0], parts[0])
    height = ''
    orient = ''
    stat = ''
    for tok in parts[1:]:
        if tok.endswith('m') and tok[:-1].replace('.', '', 1).isdigit():
            height = tok
        elif tok in _ORIENT_CN:
            orient = _ORIENT_CN[tok]
        elif tok in _STAT_CN:
            stat = _STAT_CN[tok]
    label = ''
    if height:
        label += height
    if orient:
        label += orient
    label += kind
    if stat:
        label += f' [{stat}]'
    return label or name


# 风玫瑰绘制风格（Windographer 风格）
_ROSE_STYLES = [
    ('filled_line', 'Filled line'),
    ('filled', 'Filled'),
    ('line', 'Line'),
    ('bar', 'Bar'),
]


def _chart_icon() -> QIcon:
    """绘制小折线图图标（用于 Format 图表按钮）。"""
    px = QPixmap(16, 16)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor('#4a5460'), 1.5))
    pts = [(3, 11), (6, 5), (10, 8), (13, 3)]
    for i in range(len(pts) - 1):
        p.drawLine(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
    p.end()
    return QIcon(px)


def _table_icon() -> QIcon:
    """绘制小表格网格图标（用于 Format 表格按钮）。"""
    px = QPixmap(16, 16)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setPen(QPen(QColor('#4a5460'), 1.0))
    p.drawRect(2, 2, 12, 12)
    p.drawLine(2, 6, 14, 6)
    p.drawLine(2, 10, 14, 10)
    p.drawLine(6, 2, 6, 14)
    p.drawLine(10, 2, 10, 14)
    p.end()
    return QIcon(px)


class _SilentComboBox(QComboBox):
    """封装 setCurrentIndexByData，自动 blockSignals。"""

    def setCurrentIndexByData(self, data):
        idx = self.findData(data)
        if idx >= 0:
            self.setCurrentIndex(idx)


class WindRoseWidget(QWidget):
    """风玫瑰图控件：左侧控制面板 + 右侧图/表。

    show_toolbar=True 时显示左侧控制栏（用于 Wind Rose Tab）；
    show_toolbar=False 时仅保留绘图区（用于 Summary 首页，靠右键菜单操作）。
    """

    def __init__(self, parent=None, show_toolbar: bool = True):
        super().__init__(parent)
        self.project: Project | None = None
        self._rose_cfg_key = 'wind_rose'
        self._show_toolbar = show_toolbar

        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(4)

        # ---- 左侧控制面板 ----
        self._panel = QWidget(self)
        self._panel.setMinimumWidth(250)
        self._panel.setMaximumWidth(320)
        panel_v = QVBoxLayout(self._panel)
        panel_v.setSpacing(8)
        panel_v.setContentsMargins(6, 6, 6, 6)

        self.cmb_display = _SilentComboBox()
        for key, label in [
            ('occurrences', 'Occurrences'),
            ('frequency', 'Frequency'),
            ('mean', 'Mean'),
            ('min', 'Min'),
            ('max', 'Max'),
            ('std_dev', 'Std. dev.'),
            ('total_energy', 'Total energy'),
            ('scatter_plot', 'Scatter plot'),
        ]:
            self.cmb_display.addItem(label, key)

        self.cmb_versus = _SilentComboBox()
        for key, label in [
            ('all_direction_sensors', 'All direction sensors'),
            ('direction', 'Direction'),
            ('direction_and_month', 'Direction and month'),
            ('direction_and_hour', 'Direction and hour'),
            ('direction_and_bin', 'Direction and bin'),
        ]:
            self.cmb_versus.addItem(label, key)

        self.spin_sectors = QSpinBox()
        self.spin_sectors.setRange(4, 72)
        self.spin_sectors.setSingleStep(4)

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

        self.cmb_style = _SilentComboBox()
        for key, label in _ROSE_STYLES:
            self.cmb_style.addItem(label, key)

        self.cmb_dir = _SilentComboBox()
        self.cmb_dir.setMinimumWidth(90)

        self.cmb_data = _SilentComboBox()
        self.cmb_data.setMinimumWidth(90)

        self.cmb_bin = _SilentComboBox()
        self.cmb_bin.setMinimumWidth(90)

        self.cmb_speed = _SilentComboBox()
        self.cmb_speed.setMinimumWidth(90)

        # 顶部两行：Display/Versus + Sectors/Format/Style
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        top_row.addWidget(QLabel(tr('Display')))
        top_row.addWidget(self.cmb_display, 4)
        top_row.addWidget(QLabel(tr('Versus')))
        top_row.addWidget(self.cmb_versus, 5)
        panel_v.addLayout(top_row)

        second_row = QHBoxLayout()
        second_row.setSpacing(6)
        second_row.addWidget(QLabel(tr('Sectors')))
        second_row.addWidget(self.spin_sectors)
        second_row.addWidget(QLabel(tr('Format')))
        second_row.addWidget(self.btn_chart)
        second_row.addWidget(self.btn_table)
        second_row.addSpacing(8)
        second_row.addWidget(QLabel(tr('Style')))
        second_row.addWidget(self.cmb_style, 1)
        second_row.addStretch(1)
        panel_v.addLayout(second_row)

        # 基本参数网格（从 Direction sensor 开始）
        grid = QGridLayout()
        grid.setSpacing(5)
        grid.setColumnStretch(1, 1)
        row = 0
        grid.addWidget(QLabel(tr('Direction sensor')), row, 0)
        grid.addWidget(self.cmb_dir, row, 1)
        row += 1
        grid.addWidget(QLabel(tr('Data column')), row, 0)
        grid.addWidget(self.cmb_data, row, 1)
        row += 1
        grid.addWidget(QLabel(tr('Bin column')), row, 0)
        grid.addWidget(self.cmb_bin, row, 1)
        row += 1
        grid.addWidget(QLabel(tr('Speed sensor')), row, 0)
        grid.addWidget(self.cmb_speed, row, 1)

        panel_v.addLayout(grid)

        # ---- Bin settings 分组 ----
        bin_group = QGroupBox(tr('Bin settings'))
        bin_v = QVBoxLayout(bin_group)
        bin_v.setSpacing(4)
        bin_v.setContentsMargins(6, 6, 6, 6)

        h_width = QHBoxLayout()
        self.chk_bin_width = QCheckBox(tr('Width'))
        self.spin_bin_width = QSpinBox()
        self.spin_bin_width.setRange(-1, 90)
        self.spin_bin_width.setSpecialValueText('-1')
        self.spin_bin_width.setValue(-1)
        self.spin_bin_width.setSuffix(' °')
        h_width.addWidget(self.chk_bin_width)
        h_width.addWidget(self.spin_bin_width)
        h_width.addStretch(1)
        bin_v.addLayout(h_width)

        h_start = QHBoxLayout()
        self.chk_bin_start = QCheckBox(tr('Start at'))
        self.spin_bin_start = QSpinBox()
        self.spin_bin_start.setRange(-1, 359)
        self.spin_bin_start.setSpecialValueText('-1')
        self.spin_bin_start.setValue(-1)
        self.spin_bin_start.setSuffix(' °')
        h_start.addWidget(self.chk_bin_start)
        h_start.addWidget(self.spin_bin_start)
        h_start.addStretch(1)
        bin_v.addLayout(h_start)

        self.chk_half_first = QCheckBox(tr('Make first bin half this width'))
        bin_v.addWidget(self.chk_half_first)
        panel_v.addWidget(bin_group)

        # ---- Filter by 分组 ----
        filter_group = QGroupBox(tr('Filter by'))
        filter_v = QVBoxLayout(filter_group)
        filter_v.setSpacing(5)
        filter_v.setContentsMargins(6, 6, 6, 6)

        h_flag = QHBoxLayout()
        self.chk_flag = QCheckBox(tr('Flag'))
        self.cmb_flag = _SilentComboBox()          # Include / Exclude
        self.cmb_flag.addItem(tr('Include'), 'include')
        self.cmb_flag.addItem(tr('Exclude'), 'exclude')
        self.cmb_flag_name = _SilentComboBox()     # 具体 flag 名称
        self.cmb_flag_name.setMinimumWidth(80)
        h_flag.addWidget(self.chk_flag)
        h_flag.addWidget(self.cmb_flag)
        h_flag.addWidget(self.cmb_flag_name)
        h_flag.addStretch(1)
        filter_v.addLayout(h_flag)

        h_date = QHBoxLayout()
        self.chk_date = QCheckBox(tr('Date'))
        self.cmb_date = _SilentComboBox()        # Year / Month
        self.cmb_date.addItem(tr('Year'), 'year')
        self.cmb_date.addItem(tr('Month'), 'month')
        self.cmb_date_value = _SilentComboBox()  # <All> / 具体年份或月份
        self.cmb_date_value.setMinimumWidth(60)
        h_date.addWidget(self.chk_date)
        h_date.addWidget(self.cmb_date)
        h_date.addWidget(self.cmb_date_value)
        h_date.addStretch(1)
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
        h_range.addWidget(self.date_to)
        h_range.addStretch(1)
        filter_v.addLayout(h_range)

        h_dcol = QHBoxLayout()
        self.chk_dcol = QCheckBox(tr('Data column'))
        self.cmb_filter_data = _SilentComboBox()
        self.edit_min = QLineEdit()
        self.edit_min.setPlaceholderText('Min')
        self.edit_min.setMaximumWidth(50)
        self.edit_max = QLineEdit()
        self.edit_max.setPlaceholderText('Max')
        self.edit_max.setMaximumWidth(50)
        h_dcol.addWidget(self.chk_dcol)
        h_dcol.addWidget(self.cmb_filter_data)
        h_dcol.addWidget(self.edit_min)
        h_dcol.addWidget(self.edit_max)
        h_dcol.addStretch(1)
        filter_v.addLayout(h_dcol)

        panel_v.addWidget(filter_group)
        panel_v.addStretch(1)

        # 滚动容器
        scroll = QScrollArea()
        scroll.setWidget(self._panel)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        # ---- 右侧图形 / 表格 ----
        self.stack = QStackedWidget()
        self.canvas = PlotCanvas(tr('风向玫瑰图'))
        self.canvas.export_header = 'Wind Rose'

        self.table_page = QWidget()
        table_v = QVBoxLayout(self.table_page)
        table_v.setContentsMargins(0, 0, 0, 0)
        table_v.setSpacing(4)
        self.table_title = QLabel()
        self.table_title.setStyleSheet('font-weight:bold; padding:4px 6px; color:#4a5460;')
        self.table_title.setAlignment(Qt.AlignCenter)
        self.table = QTableWidget()
        self.table.setColumnCount(0)
        self.table.setRowCount(0)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        table_v.addWidget(self.table_title)
        table_v.addWidget(self.table, 1)

        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.table_page)

        main_h.addWidget(scroll)
        main_h.addWidget(self.stack, 1)

        # 右侧图例面板（带复选框，与原版一致）
        self.legend_panel = QWidget(self)
        self.legend_panel.setMinimumWidth(140)
        self.legend_panel.setMaximumWidth(220)
        legend_v = QVBoxLayout(self.legend_panel)
        legend_v.setContentsMargins(4, 4, 4, 4)
        legend_v.setSpacing(4)
        legend_v.addWidget(QLabel(tr('Legend')))
        self.legend_scroll = QScrollArea(self.legend_panel)
        self.legend_scroll.setWidgetResizable(True)
        self.legend_scroll.setFrameShape(QScrollArea.NoFrame)
        self.legend_container = QWidget()
        self.legend_layout = QVBoxLayout(self.legend_container)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(3)
        self.legend_layout.addStretch(1)
        self.legend_scroll.setWidget(self.legend_container)
        legend_v.addWidget(self.legend_scroll)
        main_h.addWidget(self.legend_panel)

        self._legend_checks: list[tuple[str, QCheckBox]] = []

        if not self._show_toolbar:
            scroll.setVisible(False)
            self.legend_panel.setVisible(False)

        # 默认配置
        defaults = settings.get_wind_rose_defaults()
        self.spin_sectors.setValue(defaults.get('sectors', 16))

        # 信号
        self.cmb_display.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_versus.currentIndexChanged.connect(self._on_cfg_changed)
        self.spin_sectors.valueChanged.connect(self._on_cfg_changed)
        self.cmb_data.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_dir.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_bin.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_speed.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_style.currentIndexChanged.connect(self._on_cfg_changed)

        self.btn_chart.toggled.connect(self._on_format_toggled)
        self.btn_table.toggled.connect(self._on_format_toggled)

        self.chk_bin_width.stateChanged.connect(self._on_cfg_changed)
        self.spin_bin_width.valueChanged.connect(self._on_cfg_changed)
        self.chk_bin_start.stateChanged.connect(self._on_cfg_changed)
        self.spin_bin_start.valueChanged.connect(self._on_cfg_changed)
        self.chk_half_first.stateChanged.connect(self._on_cfg_changed)

        self.chk_flag.stateChanged.connect(self._on_cfg_changed)
        self.cmb_flag.currentIndexChanged.connect(self._on_cfg_changed)
        self.cmb_flag_name.currentIndexChanged.connect(self._on_cfg_changed)
        self.chk_date.stateChanged.connect(self._on_cfg_changed)
        self.cmb_date.currentIndexChanged.connect(self._on_date_mode_changed)
        self.cmb_date_value.currentIndexChanged.connect(self._on_cfg_changed)
        self.chk_range.stateChanged.connect(self._on_range_check_changed)
        self.date_from.dateChanged.connect(self._on_cfg_changed)
        self.date_to.dateChanged.connect(self._on_cfg_changed)
        self.chk_dcol.stateChanged.connect(self._on_cfg_changed)
        self.cmb_filter_data.currentIndexChanged.connect(self._on_cfg_changed)
        self.edit_min.textChanged.connect(self._on_cfg_changed)
        self.edit_max.textChanged.connect(self._on_cfg_changed)

        self._update_filter_enabled()

        # 右击图形「Properties...」打开风玫瑰专属属性对话框（Summary 无工具栏时仍可用）
        self.canvas.properties_handler = self._on_properties

        self._rose_result = None

    def set_project(self, project: Project | None):
        self.project = project
        # 程序化填充/载入期间屏蔽信号，避免 currentIndexChanged 触发 _save_project_cfg
        # 把已保存的选择（dir_col/data_col 等）覆盖成第一个选项
        self._block_cfg_signals(True)
        try:
            ds = self._active_dataset()
            if ds is not None and not ds.df.empty:
                self._refresh_dir_list()
                self._refresh_data_column_list()
                self._refresh_bin_column_list()
                self._refresh_speed_list()
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
            self.cmb_display, self.cmb_versus, self.spin_sectors,
            self.cmb_style, self.cmb_dir, self.cmb_data,
            self.cmb_bin, self.cmb_speed,
            self.chk_bin_width, self.spin_bin_width,
            self.chk_bin_start, self.spin_bin_start, self.chk_half_first,
            self.chk_flag, self.cmb_flag, self.cmb_flag_name,
            self.chk_date, self.cmb_date, self.cmb_date_value,
            self.chk_range, self.date_from, self.date_to,
            self.chk_dcol, self.cmb_filter_data, self.edit_min, self.edit_max,
            self.btn_chart, self.btn_table,
        ]
        for w in widgets:
            w.blockSignals(block)

    def _on_cfg_changed(self):
        self._save_project_cfg()
        self.refresh()

    def _on_date_mode_changed(self):
        self._refresh_date_value_list()
        self._on_cfg_changed()

    def _on_range_check_changed(self, state: int):
        # stateChanged 传 int，不能与 Qt.Checked 枚举直接比较（恒 False），
        # 一律以 isChecked() 为准
        enabled = self.chk_range.isChecked()
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)
        self._on_cfg_changed()

    def _on_format_toggled(self):
        chart = self.btn_chart.isChecked()
        self.stack.setCurrentIndex(0 if chart else 1)
        self._save_project_cfg()
        self.refresh()

    def _refresh_dir_list(self):
        self.cmb_dir.clear()
        self.cmb_dir.addItem(tr('All direction sensors'), _DIR_ALL)
        ds = self._active_dataset()
        if ds is None:
            return
        for n, ch in ds.channels.items():
            if (ch.kind == KIND_DIR
                    and getattr(ch, 'role', 'Avg') == 'Avg'
                    and n in ds.df.columns):
                self.cmb_dir.addItem(_channel_display_name(n, ds), n)

    def _refresh_data_column_list(self):
        self.cmb_data.clear()
        self.cmb_data.addItem('—', '')
        ds = self._active_dataset()
        if ds is None:
            return
        for n, ch in ds.channels.items():
            if (ch.kind == KIND_SPEED
                    and getattr(ch, 'role', 'Avg') == 'Avg'
                    and n in ds.df.columns):
                self.cmb_data.addItem(_channel_display_name(n, ds), n)
        for n in ds.df.columns:
            if self.cmb_data.findData(n) < 0:
                self.cmb_data.addItem(_channel_display_name(n, ds), n)

    def _refresh_bin_column_list(self):
        self.cmb_bin.clear()
        self.cmb_bin.addItem('—', '')
        ds = self._active_dataset()
        if ds is None:
            return
        for n in ds.df.columns:
            self.cmb_bin.addItem(_channel_display_name(n, ds), n)

    def _refresh_speed_list(self):
        self.cmb_speed.clear()
        self.cmb_speed.addItem('—', '')
        ds = self._active_dataset()
        if ds is None:
            return
        for n, ch in ds.channels.items():
            if (ch.kind == KIND_SPEED
                    and getattr(ch, 'role', 'Avg') == 'Avg'
                    and n in ds.df.columns):
                self.cmb_speed.addItem(_channel_display_name(n, ds), n)

    def _refresh_filter_data_list(self):
        self.cmb_filter_data.clear()
        self.cmb_filter_data.addItem('—', '')
        ds = self._active_dataset()
        if ds is None:
            return
        for n, ch in ds.channels.items():
            if n in ds.df.columns:
                self.cmb_filter_data.addItem(_channel_display_name(n, ds), n)
        for n in ds.df.columns:
            if self.cmb_filter_data.findData(n) < 0:
                self.cmb_filter_data.addItem(_channel_display_name(n, ds), n)

    def _refresh_date_value_list(self):
        self.cmb_date_value.clear()
        self.cmb_date_value.addItem('<All>', '')
        ds = self._active_dataset()
        if ds is None or ds.df.empty or not hasattr(ds.df.index, 'year'):
            return
        mode = self.cmb_date.currentData()
        if mode == 'year':
            years = sorted(ds.df.index.year.unique(), reverse=True)
            for y in years:
                self.cmb_date_value.addItem(str(y), str(y))
        elif mode == 'month':
            for m in range(1, 13):
                self.cmb_date_value.addItem(str(m), str(m))

    def _init_date_range(self):
        ds = self._active_dataset()
        if ds is None or ds.df.empty:
            return
        idx = ds.df.index
        if len(idx) == 0:
            return
        t0 = pd.Timestamp(idx[0])
        t1 = pd.Timestamp(idx[-1])
        self.date_from.setDate(t0.to_pydatetime())
        self.date_to.setDate(t1.to_pydatetime())

    def _load_project_cfg(self):
        if self.project is None:
            return
        cfg = self.project.plot_setting(self._rose_cfg_key)
        self.cmb_display.setCurrentIndexByData(cfg.get('display', 'frequency'))
        self.cmb_versus.setCurrentIndexByData(cfg.get('versus', 'all_direction_sensors'))
        self.spin_sectors.setValue(cfg.get('sectors', 16))
        self.cmb_style.setCurrentIndexByData(cfg.get('style', 'filled_line'))
        self.cmb_dir.setCurrentIndexByData(cfg.get('dir_col', _DIR_ALL))
        self.cmb_data.setCurrentIndexByData(cfg.get('data_col', ''))
        self.cmb_bin.setCurrentIndexByData(cfg.get('bin_col', ''))
        self.cmb_speed.setCurrentIndexByData(cfg.get('speed_col', ''))

        # Bin settings
        bin_cfg = cfg.get('bin_settings', {})
        self.chk_bin_width.setChecked(bin_cfg.get('use_width', False))
        self.spin_bin_width.setValue(int(bin_cfg.get('width', -1)))
        self.chk_bin_start.setChecked(bin_cfg.get('use_start', False))
        self.spin_bin_start.setValue(int(bin_cfg.get('start', -1)))
        self.chk_half_first.setChecked(bin_cfg.get('half_first', False))

        # Filter
        filter_cfg = cfg.get('filter', {})
        self.chk_flag.setChecked(filter_cfg.get('use_flag', False))
        self.cmb_flag.setCurrentIndexByData(filter_cfg.get('flag_mode', 'include'))
        self.cmb_flag_name.setCurrentIndexByData(filter_cfg.get('flag_name', ''))
        self.chk_date.setChecked(filter_cfg.get('use_date', False))
        self.cmb_date.setCurrentIndexByData(filter_cfg.get('date_mode', 'year'))
        self._refresh_date_value_list()
        self.cmb_date_value.setCurrentIndexByData(filter_cfg.get('date_value', ''))
        self.chk_range.setChecked(filter_cfg.get('use_range', False))
        dr = cfg.get('date_range', {})
        if dr.get('from'):
            self.date_from.setDate(pd.Timestamp(dr['from']).to_pydatetime())
        if dr.get('to'):
            self.date_to.setDate(pd.Timestamp(dr['to']).to_pydatetime())
        self.chk_dcol.setChecked(filter_cfg.get('use_dcol', False))
        self.cmb_filter_data.setCurrentIndexByData(filter_cfg.get('dcol', ''))
        self.edit_min.setText(filter_cfg.get('min', ''))
        self.edit_max.setText(filter_cfg.get('max', ''))

        # Format
        fmt = cfg.get('format', 'chart')
        self.btn_chart.setChecked(fmt == 'chart')
        self.btn_table.setChecked(fmt == 'table')

    def _save_project_cfg(self):
        if self.project is None:
            return
        cfg = {
            'display': self.cmb_display.currentData(),
            'versus': self.cmb_versus.currentData(),
            'sectors': self.spin_sectors.value(),
            'style': self.cmb_style.currentData(),
            'dir_col': self.cmb_dir.currentData() or _DIR_ALL,
            'data_col': self.cmb_data.currentData() or '',
            'bin_col': self.cmb_bin.currentData() or '',
            'speed_col': self.cmb_speed.currentData() or '',
            'bin_settings': {
                'use_width': self.chk_bin_width.isChecked(),
                'width': self.spin_bin_width.value(),
                'use_start': self.chk_bin_start.isChecked(),
                'start': self.spin_bin_start.value(),
                'half_first': self.chk_half_first.isChecked(),
            },
            'filter': {
                'use_flag': self.chk_flag.isChecked(),
                'flag_mode': self.cmb_flag.currentData(),
                'flag_name': self.cmb_flag_name.currentData() or '',
                'use_date': self.chk_date.isChecked(),
                'date_mode': self.cmb_date.currentData(),
                'date_value': self.cmb_date_value.currentData() or '',
                'use_range': self.chk_range.isChecked(),
                'use_dcol': self.chk_dcol.isChecked(),
                'dcol': self.cmb_filter_data.currentData() or '',
                'min': self.edit_min.text(),
                'max': self.edit_max.text(),
            },
            'date_range': {
                'from': self.date_from.date().toString('yyyy/MM/dd'),
                'to': self.date_to.date().toString('yyyy/MM/dd'),
            },
            'format': 'chart' if self.btn_chart.isChecked() else 'table',
        }
        self.project.set_plot_setting(self._rose_cfg_key, cfg)

    def _current_cfg(self) -> dict:
        if self.project is None:
            return {}
        return self.project.plot_setting(self._rose_cfg_key)

    def _update_filter_enabled(self):
        enabled = self.chk_flag.isChecked()
        self.cmb_flag.setEnabled(enabled)
        self.cmb_flag_name.setEnabled(enabled)
        enabled = self.chk_date.isChecked()
        self.cmb_date.setEnabled(enabled)
        self.cmb_date_value.setEnabled(enabled)
        enabled = self.chk_range.isChecked()
        self.date_from.setEnabled(enabled)
        self.date_to.setEnabled(enabled)
        enabled = self.chk_dcol.isChecked()
        self.cmb_filter_data.setEnabled(enabled)
        self.edit_min.setEnabled(enabled)
        self.edit_max.setEnabled(enabled)
        enabled = self.chk_bin_width.isChecked()
        self.spin_bin_width.setEnabled(enabled)
        enabled = self.chk_bin_start.isChecked()
        self.spin_bin_start.setEnabled(enabled)

    def _on_properties(self):
        """打开风玫瑰属性对话框（RosePropertiesDialog）。

        签名：RosePropertiesDialog(project, current_cfg, labels, parent)
        —— project 必须是真正的 Project 实例，labels 为当前系列标签列表。
        """
        from ui.dialogs.rose_properties import RosePropertiesDialog
        labels = list(self._rose_result.labels) if self._rose_result else []
        cfg = self.project.plot_setting(self._rose_cfg_key) if self.project else {}
        dialog = RosePropertiesDialog(self.project, cfg, labels, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def _update_legend_panel(self, labels: list[str], styles: list[dict]):
        """右侧图例面板：每条系列一个带复选框的条目，与原版一致。

        关键修复：若系列集合未变化，仅就地更新勾选状态与颜色，绝不销毁重建
        复选框。否则会在复选框自身的 stateChanged 回调里执行 deleteLater，
        引发黑屏 / 勾选失灵 / 偶发勾不上。
        """
        existing = [lab for lab, _ in self._legend_checks]
        if existing and existing == list(labels):
            for j, (lab, chk) in enumerate(self._legend_checks):
                st = styles[j] if j < len(styles) else {}
                visible = st.get('visible', True) is not False
                color = self._resolve_color(st, j)
                chk.blockSignals(True)
                chk.setChecked(visible)
                chk.setStyleSheet(f'color: {color};')
                chk.blockSignals(False)
            return

        # 系列集合变化 → 重建
        for _, chk in self._legend_checks:
            chk.deleteLater()
        self._legend_checks.clear()
        while self.legend_layout.count():
            item = self.legend_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.legend_layout.addStretch(1)

        if not labels:
            return
        for j, lab in enumerate(labels):
            st = styles[j] if j < len(styles) else {}
            visible = st.get('visible', True) is not False
            color = self._resolve_color(st, j)
            chk = QCheckBox(lab)
            chk.setChecked(visible)
            chk.setStyleSheet(f'color: {color};')
            chk.stateChanged.connect(
                lambda state, idx=j: self._on_legend_toggled(idx, bool(state)))
            self._legend_checks.append((lab, chk))
            self.legend_layout.insertWidget(self.legend_layout.count() - 1, chk)

    @staticmethod
    def _resolve_color(st: dict, index: int) -> str:
        color = st.get('color')
        # None 或 ''（默认"自动取调色板"）都按自动处理，避免空串被当成黑色
        if not color:
            color = PALETTE[index % len(PALETTE)]
            return color.name() if hasattr(color, 'name') else str(color)
        if hasattr(color, 'name'):   # QColor
            return color.name()
        return str(color)

    def _palette_color_hex(self, index: int) -> str:
        color = PALETTE[index % len(PALETTE)]
        return color.name()

    def _on_legend_toggled(self, index: int, checked: bool):
        if self.project is None:
            return
        cfg = self.project.plot_setting(self._rose_cfg_key)
        channel_styles = cfg.get('channel_styles', {})
        if isinstance(channel_styles, dict):
            key = str(index)
            st = channel_styles.get(key, {})
            st['visible'] = checked
            channel_styles[key] = st
        else:
            channel_styles = list(channel_styles)
            while len(channel_styles) <= index:
                channel_styles.append({})
            channel_styles[index]['visible'] = checked
        self.project.set_plot_setting(
            self._rose_cfg_key, {**cfg, 'channel_styles': channel_styles})
        self.refresh()

    def _build_filter_mask(self, ds: Dataset) -> pd.Series | None:
        """根据左侧 Filter 设置构造布尔 mask。"""
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
                # 指定具体 flag
                reg = getattr(ds, 'flag_registry', None)
                if isinstance(reg, dict) and flag_name in reg:
                    fm = reg[flag_name]
                    if hasattr(fm, '__len__') and len(fm) == len(df):
                        flag_mask = pd.Series(np.asarray(fm, dtype=bool), index=df.index)
                    else:
                        flag_mask = pd.Series(False, index=df.index)
                else:
                    flag_mask = pd.Series(False, index=df.index)
                if mode == 'include':
                    mask &= flag_mask
                else:
                    mask &= ~flag_mask
            else:
                # <Unflagged data>：未指定 flag 名时，按主 flags 汇总判断
                flags = getattr(ds, 'flags', None)
                if flags is not None and len(flags) == len(df):
                    if mode == 'include':
                        mask &= ~flags.astype(bool)  # 保留未标记
                    else:
                        mask &= flags.astype(bool)   # 排除未标记，即只保留已标记

        if cfg.get('use_date'):
            has_filter = True
            mode = cfg.get('date_mode', 'year')
            val = cfg.get('date_value', '')
            if val:
                try:
                    ival = int(val)
                    if mode == 'year':
                        mask &= df.index.year == ival
                    elif mode == 'month':
                        mask &= df.index.month == ival
                except Exception:
                    pass

        if cfg.get('use_range'):
            has_filter = True
            dr = self._current_cfg().get('date_range', {})
            dfrom = dr.get('from')
            dto = dr.get('to')
            if dfrom:
                mask &= df.index >= pd.Timestamp(dfrom)
            if dto:
                mask &= df.index <= pd.Timestamp(dto)

        if cfg.get('use_dcol'):
            has_filter = True
            dcol = cfg.get('dcol')
            if dcol and dcol in df.columns:
                s = pd.to_numeric(df[dcol], errors='coerce')
                vmin = self._float_text(self.edit_min.text())
                vmax = self._float_text(self.edit_max.text())
                if vmin is not None:
                    mask &= s >= vmin
                if vmax is not None:
                    mask &= s <= vmax

        return mask if has_filter else None

    @staticmethod
    def _float_text(txt: str) -> float | None:
        try:
            return float(txt)
        except Exception:
            return None

    def _bin_settings_kwargs(self) -> dict:
        cfg = self._current_cfg().get('bin_settings', {})
        kw = {}
        if cfg.get('use_width') and cfg.get('width', -1) > 0:
            kw['bin_width'] = float(cfg['width'])
        if cfg.get('use_start') and cfg.get('start', -1) >= 0:
            kw['bin_start'] = float(cfg['start'])
        kw['half_first_bin'] = cfg.get('half_first', False)
        return kw

    def refresh(self):
        ds = self._active_dataset()
        if ds is None or ds.df.empty:
            self.canvas.clear(tr('未载入数据集'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        dir_cols = [n for n, ch in ds.channels.items()
                    if ch.kind == KIND_DIR
                    and getattr(ch, 'role', 'Avg') == 'Avg'
                    and n in ds.df.columns]
        if not dir_cols:
            self.canvas.clear(tr('无风向通道'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        versus = self.cmb_versus.currentData()
        dir_col = self.cmb_dir.currentData()

        # versus=全部风向传感器 或 dir_col 未选/全部 → 全部叠加
        all_mode = versus == 'all_direction_sensors' or dir_col is None or dir_col == _DIR_ALL
        if all_mode:
            dir_col = _DIR_ALL
            # 回落到第一个风向通道用于单通道标题等
            primary_dir = dir_cols[0]
        else:
            primary_dir = dir_col

        data_col = self.cmb_data.currentData() or None
        display = self.cmb_display.currentData()
        sectors = self.spin_sectors.value()
        bin_col = self.cmb_bin.currentData() or None
        speed_col = self.cmb_speed.currentData() or None
        if not speed_col:
            speed_col = self._auto_speed_col(ds, primary_dir)

        # frequency/occurrences 不使用 data_col
        if display in ('frequency', 'occurrences'):
            data_col = None
        elif not data_col and speed_col:
            data_col = speed_col

        filter_mask = self._build_filter_mask(ds)
        bin_kw = self._bin_settings_kwargs()

        if dir_col == _DIR_ALL:
            result = self._compute_all_directions(
                ds, dir_cols, sectors, display, data_col,
                filter_mask=filter_mask, **bin_kw)
        else:
            result = compute_rose(
                ds.df, dir_col,
                sectors=sectors,
                display=display,
                versus=versus if versus != 'all_direction_sensors' else 'direction',
                data_col=data_col,
                speed_col=speed_col,
                bin_col=bin_col,
                filter_mask=filter_mask,
                **bin_kw,
            )
        self._rose_result = result
        if result is None:
            self.canvas.clear(tr('计算失败'))
            return

        # 构建 styles
        cfg = self.project.plot_setting(self._rose_cfg_key) if self.project else {}
        channel_styles = cfg.get('channel_styles', {})
        # channel_styles 可能是 dict（按通道名）或 list（按索引）；统一按索引取
        if isinstance(channel_styles, dict):
            channel_styles = list(channel_styles.values())
        labels = result.labels
        styles = []
        ds = self._active_dataset()
        for j, lab in enumerate(labels):
            st = channel_styles[j] if j < len(channel_styles) else {}
            st.setdefault('label', _channel_display_name(lab, ds))
            st.setdefault('rose_style', self.cmb_style.currentData())
            styles.append(st)

        self._update_legend_panel(labels, styles)

        # 按图例复选框过滤可见系列
        visible_idx = [j for j, st in enumerate(styles)
                       if st.get('visible', True) is not False]
        if not visible_idx:
            self.canvas.clear(tr('未选择系列'))
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        plot_result = RoseResult(
            sectors=result.sectors,
            center_deg=result.center_deg,
            values=result.values[:, visible_idx],
            labels=[result.labels[j] for j in visible_idx],
            calm=result.calm,
            display=result.display,
            versus=result.versus,
            unit=result.unit,
        )

        if self.btn_table.isChecked():
            self._fill_table(plot_result)
            self.stack.setCurrentIndex(1)
            return
        self.stack.setCurrentIndex(0)

        # 标题按 Display 动态化
        title_map = {
            'occurrences': 'Wind Direction Occurrences',
            'frequency': 'Wind Direction Frequency',
            'mean': 'Wind Direction Mean',
            'min': 'Wind Direction Min',
            'max': 'Wind Direction Max',
            'std_dev': 'Wind Direction Std. Dev.',
            'total_energy': 'Wind Direction Total Energy',
            'scatter_plot': 'Wind Direction Scatter',
        }
        title = title_map.get(display, 'Wind Rose')

        self.canvas.plot_polar(
            result.sectors,
            plot_result.values,
            title=title,
            labels=plot_result.labels,
            calm=plot_result.calm,
            center_deg=plot_result.center_deg,
            display_type=plot_result.display,
            unit=plot_result.unit,
            styles=styles,
            inner_circle_pct=cfg.get('inner_circle_pct', 0.0),
            fill_factor=cfg.get('fill_factor', 0.85),
            show_legend=cfg.get('show_legend', True) and not self._show_toolbar,
        )

        if not self.btn_chart.isChecked():
            self._fill_table(plot_result)

    def _compute_all_directions(self, ds: Dataset, dir_cols: list[str],
                                sectors: int, display: str,
                                data_col: str | None,
                                filter_mask=None,
                                **bin_kw) -> RoseResult | None:
        """全部风向通道模式：每个风向通道作为一条系列叠加到同一风玫瑰。"""
        center_deg = np.arange(sectors) * (360.0 / sectors) + 180.0 / sectors

        if display == 'scatter_plot':
            pts = []
            for dc in dir_cols:
                sp = self._auto_speed_col(ds, dc)
                val = data_col or sp
                r = compute_rose(ds.df, dc, sectors=sectors,
                                 display='scatter_plot', versus='direction',
                                 data_col=val, speed_col=sp,
                                 filter_mask=filter_mask, **bin_kw)
                if r is not None and r.values is not None and len(r.values):
                    pts.append(r.values)
            if not pts:
                return None
            values = np.vstack(pts)
            return RoseResult(sectors=sectors, center_deg=center_deg,
                              values=values, labels=['全部风向通道'],
                              calm=0.0, display='scatter_plot',
                              versus='direction', unit='')

        series_vals: list[np.ndarray] = []
        series_labels: list[str] = []
        units: set[str] = set()
        for dc in dir_cols:
            sp = self._auto_speed_col(ds, dc)
            if display in ('frequency', 'occurrences'):
                val = None
            elif data_col:
                val = data_col
            else:
                val = sp
            r = compute_rose(ds.df, dc, sectors=sectors, display=display,
                             versus='direction', data_col=val, speed_col=sp,
                             filter_mask=filter_mask, **bin_kw)
            if r is None:
                continue
            series_vals.append(r.values[:, 0])
            series_labels.append(_channel_display_name(dc, ds))
            units.add(r.unit)
        if not series_vals:
            return None
        values = np.column_stack(series_vals)
        unit = next(iter(units), '%')
        return RoseResult(sectors=sectors, center_deg=center_deg,
                          values=values, labels=series_labels, calm=0.0,
                          display=display, versus='direction', unit=unit)

    def _auto_speed_col(self, ds: Dataset, dir_col: str) -> str | None:
        """按高度/方向匹配最近的风速 Avg 列。"""
        dir_ch = ds.channels.get(dir_col)
        if dir_ch is None:
            return None
        best = None
        best_score = float('inf')
        for n, ch in ds.channels.items():
            if ch.kind != KIND_SPEED or getattr(ch, 'role', 'Avg') != 'Avg':
                continue
            if n not in ds.df.columns:
                continue
            # 简单匹配：高度最接近
            hdiff = abs(getattr(ch, 'height', 0) - getattr(dir_ch, 'height', 0))
            if hdiff < best_score:
                best_score = hdiff
                best = n
        return best

    def _fill_table(self, result):
        n, k = result.values.shape
        self.table.clear()
        self.table.setColumnCount(k + 2)
        show_calm = bool(result.calm and result.calm > 0)
        self.table.setRowCount(n + (1 if show_calm else 0) + 1)

        ds = self._active_dataset()
        headers = ['Sector', 'Midpoint'] + [
            _channel_display_name(lab, ds) for lab in result.labels]
        self.table.setHorizontalHeaderLabels(headers)

        # 表格顶部标题（与原版 Frequency (%) 等对齐）
        title_map = {
            'occurrences': 'Occurrences',
            'frequency': 'Frequency (%)',
            'mean': 'Mean',
            'min': 'Min',
            'max': 'Max',
            'std_dev': 'Std. dev.',
            'total_energy': 'Total energy',
            'scatter_plot': 'Scatter plot',
        }
        title = title_map.get(result.display, 'Wind Rose')
        if result.unit and result.display != 'frequency':
            title += f' ({result.unit})'
        self.table_title.setText(title)

        for i in range(n):
            item = QTableWidgetItem(str(i + 1))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, item)

            mp = result.center_deg[i]
            item = QTableWidgetItem(f'{mp:.1f}°')
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 1, item)

            for j in range(k):
                v = result.values[i, j]
                txt = '' if not (v == v) else f'{v:.2f}'
                item = QTableWidgetItem(txt)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, j + 2, item)

        row = n
        if show_calm:
            calm_item = QTableWidgetItem('Calm')
            calm_item.setFlags(calm_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, calm_item)
            self.table.setItem(row, 1, QTableWidgetItem(''))
            for j in range(k):
                item = QTableWidgetItem(f'{result.calm:.2f}')
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, j + 2, item)
            row += 1

        total_item = QTableWidgetItem('Total')
        total_item.setFlags(total_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 0, total_item)
        self.table.setItem(row, 1, QTableWidgetItem(''))
        for j in range(k):
            col = result.values[:, j]
            finite = col[np.isfinite(col)]
            total = float(finite.sum())
            item = QTableWidgetItem(f'{total:.2f}')
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, j + 2, item)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        self.table.resizeColumnsToContents()
        for c in range(self.table.columnCount()):
            if c < 2:
                header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
            else:
                header.setSectionResizeMode(c, QHeaderView.Stretch)

    def _on_table_context_menu(self, pos):
        """表格视图右键菜单：Copy / Export / Transposed。"""
        menu = QMenu(self.table)
        menu.addAction(QAction(tr('Copy Selection'), self.table,
                               triggered=self._copy_selection))
        menu.addAction(QAction(tr('Copy Table'), self.table,
                               triggered=lambda: self._copy_table(transpose=False)))
        menu.addSeparator()
        menu.addAction(QAction(tr('Copy Table Transposed'), self.table,
                               triggered=lambda: self._copy_table(transpose=True)))
        menu.addSeparator()
        menu.addAction(QAction(tr('Export Table...'), self.table,
                               triggered=lambda: self._export_table(transpose=False)))
        menu.addAction(QAction(tr('Export Table Transposed...'), self.table,
                               triggered=lambda: self._export_table(transpose=True)))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _table_data(self, transpose: bool = False) -> list[list[str]]:
        """提取当前表格全部内容（含表头），返回二维字符串列表。"""
        rows = self.table.rowCount()
        cols = self.table.columnCount()
        header = [self.table.horizontalHeaderItem(c).text()
                  for c in range(cols)]
        body: list[list[str]] = []
        for r in range(rows):
            row = []
            for c in range(cols):
                item = self.table.item(r, c)
                row.append(item.text() if item is not None else '')
            body.append(row)
        if transpose:
            out = []
            out.append([''] + header)
            for r in range(rows):
                vh = self.table.verticalHeaderItem(r)
                out.append([vh.text() if vh is not None else ''] + body[r])
            return out
        return [header] + body

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
        text = '\n'.join(lines)
        QApplication.clipboard().setText(text)

    def _copy_table(self, transpose: bool = False):
        data = self._table_data(transpose=transpose)
        text = '\n'.join('\t'.join(row) for row in data)
        QApplication.clipboard().setText(text)

    def _export_table(self, transpose: bool = False):
        path, _ = QFileDialog.getSaveFileName(
            self.table, 'Export Table',
            '',
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
        out = []
        for cell in row:
            if ',' in cell or '"' in cell or '\n' in cell:
                cell = '"' + cell.replace('"', '""') + '"'
            out.append(cell)
        return ','.join(out)
