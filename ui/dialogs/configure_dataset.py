"""Configure Data Set 对话框（两 Tab）。

- Data Columns：编辑每个通道的类别/标签/单位/颜色/高度/可见性/关联列，
  底部实时绘制 PDF / 日变化 / 月统计三张小图。
- Data Set：站点名称、描述、经纬度/海拔、时间戳位置、calm 阈值、无效值标记。

导入/追加原始数据时直接弹出；也可通过「修正 → 配置数据集」随时打开。
"""

from __future__ import annotations

import json
import math
import os
import re

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDialog, QDoubleSpinBox, QFileDialog,
                               QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSizePolicy, QSplitter,
                               QTabWidget, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout, QWidget,
                               QColorDialog)

from core.dataset import (KIND_DIR, KIND_PRES, KIND_RH, KIND_SPEED,
                                  KIND_SPEED_SD, KIND_TEMP, KIND_TI, KIND_WZ,
                                  KIND_SYNTH, Channel, Dataset)
from core.io_import import _norm_role, build_canon_name
from ui.modules.analysis_tabs import actual_name, display_name
from ui.modules.plot import PlotCanvas
from core.i18n import tr


_KIND_ITEMS = [
    (KIND_SPEED, 'SPEED'),
    (KIND_DIR, 'DIRECTION'),
    (KIND_SPEED_SD, 'SPEED SD'),
    (KIND_TEMP, 'TEMPERATURE'),
    (KIND_PRES, 'PRESSURE'),
    (KIND_RH, 'RH'),
    (KIND_WZ, 'Wz'),
    (KIND_TI, 'TI'),
    (KIND_SYNTH, 'Synthesized'),
    ('other', 'Other'),
]

_ROLE_ITEMS = ['Avg', 'SD', 'Min', 'Max', 'Gust', '']

_DEFAULT_COLORS = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
    '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5',
]


def _kind_label(kind: str) -> str:
    return next((c for k, c in _KIND_ITEMS if k == kind), '其它')


def _kind_from_label(label: str) -> str:
    return next((k for k, c in _KIND_ITEMS if c == label), 'other')


def _extract_orient(name: str) -> str:
    """从名称中提取方位（空格/下划线风格均可）：
    `Speed 160m W Avg` / `Ch1_Anem_160.00m_W_Avg` → W。"""
    m = re.search(r'(?:^|[\s_])(NE|NW|SE|SW|N|E|S|W)(?=$|[\s_])', name)
    return m.group(1) if m else ''


_STAT_TOKEN_RE = re.compile(r'(?:AVG|SD|MIN|MAX|GUST|GUSTDIR)$', re.I)


def _strip_suffix_letter(label: str) -> str:
    """去掉末尾的单字母后缀（前面是统计词时才认定）：
    `SPEED 120m AVG A` → `SPEED 120m AVG`。"""
    toks = label.split()
    if len(toks) >= 2 and len(toks[-1]) == 1 and toks[-1].isalpha() \
            and _STAT_TOKEN_RE.match(toks[-2]):
        return ' '.join(toks[:-1])
    return label.strip()


def _sensor_key_of(orig: str) -> str:
    """传感器身份 = 原始列名去掉统计词/单位词后的主干（下划线/空格通用）。

    同一支传感器的 Avg/SD/Min/Max 行归为同一键；不同传感器（Ch1/Ch2…）
    天然不同。"""
    toks = [t for t in re.split(r'[\s_]+', (orig or '').strip()) if t]
    out = []
    for t in toks:
        if _STAT_TOKEN_RE.match(t):
            continue
        if re.match(r'^\[?(?:m/s|deg|kpa|c|%rh|°|°c|hpa|db|%)\]?$', t, re.I):
            continue
        out.append(t)
    return ' '.join(out)


def _to_float(v):
    """把可能为 None/空/NaN 的值安全转成 float。

    QDoubleSpinBox.setValue(float('nan')) 在不同 Qt 版本下会 clamp 到范围边界
    （如 lat 变成 90），因此不能返回 NaN。对 None/空 返回 0.0，让对话框显示
    0 而不是极值；调用方再据此判断是否为「未设置」。
    """
    if v is None or v == '':
        return 0.0
    try:
        f = float(v)
        if math.isnan(f):
            return 0.0
        return f
    except Exception:
        return 0.0


class AddCalculatedColumnDialog(QDialog):
    """添加计算列：支持 11 种计算类型（对齐 Windographer 17.11-17.18）。"""

    TYPES = [
        ('copy', 'Copy Column'),
        ('avg_2', 'Average of Two Speeds'),
        ('vector_avg', 'Vector Average Speed'),
        ('expression', 'Custom Expression'),
        ('accumulation', 'Accumulation'),
        ('moving_avg', 'Moving Average'),
        ('date_time', 'Date or Time Component'),
        ('piecewise', 'Piecewise Linear Function'),
        ('polynomial', 'Polynomial Function'),
        ('rews', 'Rotor Equivalent Wind Speed'),
        ('solar', 'Solar Variables'),
    ]

    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Add Calculated Column'))
        self.resize(420, 320)
        self._df = df
        self._result: tuple[str, pd.Series] | None = None

        cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        lay = QVBoxLayout(self)

        g = QGridLayout()
        g.addWidget(QLabel(tr('New column name')), 0, 0)
        self.name_edit = QLineEdit('NewColumn')
        g.addWidget(self.name_edit, 0, 1)

        g.addWidget(QLabel(tr('Function')), 1, 0)
        self.type_combo = QComboBox()
        for t in self.TYPES:
            self.type_combo.addItem(t['label'], t['key'])
        g.addWidget(self.type_combo, 1, 1)

        g.addWidget(QLabel(tr('Source A')), 2, 0)
        self.src_a = QComboBox()
        self.src_a.addItems(cols)
        g.addWidget(self.src_a, 2, 1)

        g.addWidget(QLabel(tr('Source B')), 3, 0)
        self.src_b = QComboBox()
        self.src_b.addItems(cols)
        if len(cols) > 1:
            self.src_b.setCurrentIndex(1)
        g.addWidget(self.src_b, 3, 1)

        g.addWidget(QLabel(tr('Expression')), 4, 0)
        self.expr_edit = QLineEdit('(A + B) / 2')
        self.expr_edit.setEnabled(False)
        g.addWidget(self.expr_edit, 4, 1)

        g.addWidget(QLabel(tr('Moving avg window')), 5, 0)
        self.sp_window = QSpinBox()
        self.sp_window.setRange(2, 999)
        self.sp_window.setValue(6)
        self.sp_window.setEnabled(False)
        g.addWidget(self.sp_window, 5, 1)

        g.addWidget(QLabel(tr('Date/Time component')), 6, 0)
        self.cmb_dt_component = QComboBox()
        self.cmb_dt_component.addItems(['Year', 'Month', 'Day', 'Hour',
                                        'Minute', 'Day of Year',
                                        'Day of Week', 'Julian Day'])
        self.cmb_dt_component.setEnabled(False)
        g.addWidget(self.cmb_dt_component, 6, 1)

        g.addWidget(QLabel(tr('Poly coefficients (c0,c1,...)')), 7, 0)
        self.ed_poly = QLineEdit('0,1')
        self.ed_poly.setEnabled(False)
        g.addWidget(self.ed_poly, 7, 1)

        g.addWidget(QLabel(tr('Latitude (for Solar)')), 8, 0)
        self.sp_latitude = QDoubleSpinBox()
        self.sp_latitude.setRange(-90, 90)
        self.sp_latitude.setValue(35.0)
        self.sp_latitude.setEnabled(False)
        g.addWidget(self.sp_latitude, 8, 1)

        lay.addLayout(g)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _on_type_changed(self, index: int):
        key = self.type_combo.currentData()
        is_copy = key == 'copy'
        is_expr = key == 'expression'
        needs_ab = key in ('copy', 'avg_2', 'vector_avg', 'expression',
                           'accumulation', 'moving_avg', 'piecewise',
                           'polynomial')
        self.src_a.setEnabled(needs_ab)
        self.src_b.setEnabled(key in ('avg_2', 'vector_avg', 'expression'))
        self.expr_edit.setEnabled(is_expr)
        self.sp_window.setEnabled(key == 'moving_avg')
        self.cmb_dt_component.setEnabled(key == 'date_time')
        self.ed_poly.setEnabled(key == 'polynomial')
        self.sp_latitude.setEnabled(key == 'solar')

    def _accept(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, 'Input', 'Please enter a column name')
            return
        if name in self._df.columns:
            QMessageBox.warning(self, 'Input', f'Column "{name}" already exists')
            return
        key = self.type_combo.currentData()
        col_a = self.src_a.currentText()
        col_b = self.src_b.currentText()
        try:
            from core.calculated_columns import compute_calculated
            params = {}
            if key == 'moving_avg':
                params['window'] = self.sp_window.value()
            elif key == 'date_time':
                params['component'] = self.cmb_dt_component.currentText()
            elif key == 'polynomial':
                coeffs = [float(x) for x in self.ed_poly.text().split(',')]
                params['coefficients'] = coeffs
            elif key == 'solar':
                params['latitude'] = self.sp_latitude.value()
            s = compute_calculated(self._df, key, col_a=col_a, col_b=col_b,
                                   name=name, **params)
            self._result = (name, s)
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, 'Calculation Error', str(e))

    def result(self) -> tuple[str, pd.Series] | None:
        return self._result


class ConfigureDatasetDialog(QDialog):
    """Configure Data Set 主对话框。"""

    def __init__(self, dataset: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('配置数据集'))
        self.resize(1280, 780)
        self._ds = dataset
        self._rows: list[dict] = []   # 每个通道一行，包含 visible=False
        self._adjusting_columns = False
        self._last_viewport_width = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self._build_columns_tab()
        self._build_dataset_tab()

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr('取消'))
        ok = QPushButton(tr('确定'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

        self._init_rows()
        if self.chk_auto_assoc.isChecked():
            self._auto_associate()
        self._refresh_table()
        if self._rows:
            self.table.selectRow(0)
            self._on_selection_changed()

    # ------------------------------------------------------------------
    # Data Columns Tab
    # ------------------------------------------------------------------
    def _build_columns_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)

        # 顶部按钮
        btns = QHBoxLayout()
        self.btn_add = QPushButton(tr('Add Column...'))
        self.btn_del = QPushButton(tr('Delete Column(s)'))
        self.btn_colors = QPushButton(tr('Assign Default Colors to All Columns'))
        self.btn_regen = QPushButton(tr('Recalculate Standardized Names'))
        self.btn_regen.setToolTip(tr(
            'Rebuild standardized labels as "SPEED 120m W AVG"; multiple '
            'sensors at the same height and type get suffixes A, B, C...'))
        self.btn_save_tmpl = QPushButton(tr('Save Template...'))
        self.btn_load_tmpl = QPushButton(tr('Load Template...'))
        for b in (self.btn_add, self.btn_del, self.btn_colors,
                  self.btn_regen, self.btn_save_tmpl, self.btn_load_tmpl):
            btns.addWidget(b)
        self.chk_auto_assoc = QCheckBox(tr('Auto-associate SD/Max/Min'))
        self.chk_auto_assoc.setChecked(True)
        self.chk_auto_assoc.stateChanged.connect(self._on_auto_assoc_changed)
        btns.addWidget(self.chk_auto_assoc)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.btn_add.clicked.connect(self._add_column)
        self.btn_del.clicked.connect(self._delete_columns)
        self.btn_colors.clicked.connect(self._assign_default_colors)
        self.btn_regen.clicked.connect(self._regen_labels)
        self.btn_save_tmpl.clicked.connect(self._save_template)
        self.btn_load_tmpl.clicked.connect(self._load_template)

        # 中部分割器：左表 + 右属性面板
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            [tr('启用'), tr('标准化标签'), tr('原始标签'), tr('类别'), tr('高度(m)'), tr('单位'), tr('颜色'),
             tr('均值'), tr('最小'), tr('最大')])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        hdr = self.table.horizontalHeader()
        # 列宽策略：每列先保证完整显示；多余空间由所有列均分。
        # 通过 eventFilter 监听表格 viewport resize，动态重新分配；
        # 用户仍可手动拖动任意列宽。
        self.table.viewport().installEventFilter(self)
        hdr.setStretchLastSection(False)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        left_lay.addWidget(self.table, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 0, 0, 0)

        prop = QGroupBox(tr('数据列属性'))
        prop_lay = QGridLayout(prop)
        prop_lay.setColumnStretch(1, 1)

        self.p_type = QComboBox()
        for k, cn in _KIND_ITEMS:
            self.p_type.addItem(cn, k)
        self.p_type.currentIndexChanged.connect(self._apply_kind)

        self.p_role = QComboBox()
        self.p_role.addItems(_ROLE_ITEMS)
        self.p_role.currentIndexChanged.connect(self._apply_role)

        self.p_label = QLineEdit()
        self.p_label.editingFinished.connect(self._apply_label)

        self.p_units = QLineEdit()
        self.p_units.editingFinished.connect(self._apply_units)

        self.p_height = QDoubleSpinBox()
        self.p_height.setRange(0, 9999)
        self.p_height.setDecimals(1)
        self.p_height.valueChanged.connect(self._apply_height)

        # 后缀：同类型同高度多支传感器区分用（A/B/C，可手动输入其它字母）
        self.p_suffix = QComboBox()
        self.p_suffix.setEditable(True)
        self.p_suffix.setInsertPolicy(QComboBox.NoInsert)
        for _x in ('', 'A', 'B', 'C'):
            self.p_suffix.addItem(_x)
        self.p_suffix.setFixedWidth(80)
        self.p_suffix.currentIndexChanged.connect(self._apply_suffix)
        self.p_suffix.lineEdit().editingFinished.connect(self._apply_suffix)

        color_h = QHBoxLayout()
        self.p_color_line = QLineEdit()
        self.p_color_line.setReadOnly(True)
        self.p_color_line.setMaximumWidth(90)
        self.p_color_btn = QPushButton('...')
        self.p_color_btn.setMaximumWidth(32)
        self.p_color_btn.clicked.connect(self._choose_color)
        color_h.addWidget(self.p_color_line)
        color_h.addWidget(self.p_color_btn)

        self.p_visible = QCheckBox(tr('Visible'))
        self.p_visible.stateChanged.connect(self._apply_visible)

        self.p_sd = QComboBox()
        self.p_max = QComboBox()
        self.p_min = QComboBox()
        for cb in (self.p_sd, self.p_max, self.p_min):
            cb.addItem('<none>', '')
            cb.currentIndexChanged.connect(self._apply_assoc)

        self._l_sd = QLabel(tr('Std. dev.'))
        self._l_max = QLabel(tr('Max.'))
        self._l_min = QLabel(tr('Min.'))

        r = 0
        prop_lay.addWidget(QLabel(tr('Type')), r, 0)
        prop_lay.addWidget(self.p_type, r, 1)
        r += 1
        prop_lay.addWidget(QLabel(tr('Subtype')), r, 0)
        prop_lay.addWidget(self.p_role, r, 1)
        r += 1
        prop_lay.addWidget(QLabel(tr('Label')), r, 0)
        prop_lay.addWidget(self.p_label, r, 1)
        r += 1
        prop_lay.addWidget(QLabel(tr('Units')), r, 0)
        prop_lay.addWidget(self.p_units, r, 1)
        r += 1
        prop_lay.addWidget(QLabel(tr('Height')), r, 0)
        prop_lay.addWidget(self.p_height, r, 1)
        r += 1
        prop_lay.addWidget(QLabel(tr('Suffix')), r, 0)
        prop_lay.addWidget(self.p_suffix, r, 1)
        r += 1
        prop_lay.addWidget(QLabel(tr('Color')), r, 0)
        prop_lay.addLayout(color_h, r, 1)
        r += 1
        prop_lay.addWidget(QLabel(tr('Visible')), r, 0)
        prop_lay.addWidget(self.p_visible, r, 1)
        r += 1
        prop_lay.addWidget(self._l_sd, r, 0)
        prop_lay.addWidget(self.p_sd, r, 1)
        r += 1
        prop_lay.addWidget(self._l_max, r, 0)
        prop_lay.addWidget(self.p_max, r, 1)
        r += 1
        prop_lay.addWidget(self._l_min, r, 0)
        prop_lay.addWidget(self.p_min, r, 1)
        r += 1
        prop_lay.setRowStretch(r, 1)

        right_lay.addWidget(prop)
        right_lay.addStretch(1)
        splitter.addWidget(right)
        splitter.setSizes([760, 280])

        lay.addWidget(splitter, 1)

        # 底部三张小图
        charts = QHBoxLayout()
        self.pdf_canvas = PlotCanvas('PDF')
        self.diurnal_canvas = PlotCanvas('Mean Diurnal Profile')
        self.monthly_canvas = PlotCanvas('Monthly Statistics')
        for c in (self.pdf_canvas, self.diurnal_canvas, self.monthly_canvas):
            c.setMinimumHeight(180)
            charts.addWidget(c, 1)
        lay.addLayout(charts)

        self.tabs.addTab(page, tr('Data Columns'))

    # ------------------------------------------------------------------
    # Data Set Tab
    # ------------------------------------------------------------------
    def _build_dataset_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)

        site_g = QGroupBox(tr('Site information'))
        site_lay = QGridLayout(site_g)
        site_lay.addWidget(QLabel(tr('Name')), 0, 0)
        self.ds_name = QLineEdit()
        site_lay.addWidget(self.ds_name, 0, 1)
        site_lay.addWidget(QLabel(tr('Description')), 1, 0, Qt.AlignTop)
        self.ds_desc = QTextEdit()
        self.ds_desc.setMaximumHeight(80)
        site_lay.addWidget(self.ds_desc, 1, 1)
        lay.addWidget(site_g)

        loc_g = QGroupBox(tr('Location'))
        loc_lay = QGridLayout(loc_g)
        self.ds_lat = QDoubleSpinBox()
        self.ds_lat.setRange(-90, 90)
        self.ds_lat.setDecimals(6)
        self.ds_lon = QDoubleSpinBox()
        self.ds_lon.setRange(-180, 180)
        self.ds_lon.setDecimals(6)
        self.ds_elev = QDoubleSpinBox()
        self.ds_elev.setRange(-500, 9000)
        self.ds_elev.setDecimals(1)
        loc_lay.addWidget(QLabel(tr('Latitude')), 0, 0)
        loc_lay.addWidget(self.ds_lat, 0, 1)
        loc_lay.addWidget(QLabel(tr('Longitude')), 0, 2)
        loc_lay.addWidget(self.ds_lon, 0, 3)
        loc_lay.addWidget(QLabel(tr('Elevation')), 0, 4)
        loc_lay.addWidget(self.ds_elev, 0, 5)
        loc_lay.addWidget(QLabel('m'), 0, 6)
        lay.addWidget(loc_g)

        time_g = QGroupBox(tr('Date and time'))
        time_lay = QGridLayout(time_g)
        self.lbl_start = QLabel('—')
        self.lbl_end = QLabel('—')
        self.lbl_duration = QLabel('—')
        self.lbl_step = QLabel('—')
        time_lay.addWidget(QLabel(tr('Data set starts:')), 0, 0)
        time_lay.addWidget(self.lbl_start, 0, 1)
        time_lay.addWidget(QLabel(tr('Data set ends:')), 1, 0)
        time_lay.addWidget(self.lbl_end, 1, 1)
        time_lay.addWidget(QLabel(tr('Data set duration:')), 2, 0)
        time_lay.addWidget(self.lbl_duration, 2, 1)
        time_lay.addWidget(QLabel(tr('Length of time step:')), 3, 0)
        time_lay.addWidget(self.lbl_step, 3, 1)
        time_lay.addWidget(QLabel(tr('Time stamps')), 0, 2)
        self.ds_stamp = QComboBox()
        self.ds_stamp.addItems(['Start', 'Middle', 'End'])
        time_lay.addWidget(self.ds_stamp, 0, 3)
        lay.addWidget(time_g)

        other_g = QGroupBox(tr('Other'))
        other_lay = QHBoxLayout(other_g)
        other_lay.addWidget(QLabel(tr('Calm threshold')))
        self.ds_calm = QDoubleSpinBox()
        self.ds_calm.setRange(0, 99)
        self.ds_calm.setDecimals(2)
        self.ds_calm.setSuffix(' m/s')
        other_lay.addWidget(self.ds_calm)
        other_lay.addSpacing(20)
        self.chk_invalid = QCheckBox(tr('Flag as invalid any data point with the value'))
        self.spin_invalid = QDoubleSpinBox()
        self.spin_invalid.setRange(-99999, 99999)
        self.spin_invalid.setDecimals(3)
        self.spin_invalid.setEnabled(False)
        self.chk_invalid.toggled.connect(self.spin_invalid.setEnabled)
        other_lay.addWidget(self.chk_invalid)
        other_lay.addWidget(self.spin_invalid)
        other_lay.addStretch(1)
        lay.addWidget(other_g)

        lay.addStretch(1)
        self.tabs.addTab(page, tr('Data Set'))

    # ------------------------------------------------------------------
    # 数据初始化
    # ------------------------------------------------------------------
    def _init_rows(self):
        df = self._ds.df
        meta = {m['name']: m for m in (self._ds.import_meta or [])}
        # 优先用 df 列顺序，缺失的用 channels 补充
        seen = set()
        for col in df.columns:
            seen.add(col)
            m = meta.get(col, {})
            ch = self._ds.channels.get(col)
            self._rows.append(self._make_row(col, m, ch))
        for name, ch in self._ds.channels.items():
            if name in seen:
                continue
            m = meta.get(name, {})
            self._rows.append(self._make_row(name, m, ch))
        # 非 Avg 通道不应保留 SD/Max/Min 关联
        for row in self._rows:
            if row['role'] != 'Avg':
                row['sd_col'] = row['max_col'] = row['min_col'] = ''

    def _make_row(self, name: str, m: dict, ch: Channel | None) -> dict:
        # role 统一归一到 Avg/SD/Min/Max/Gust：历史解析器可能写入 'std'/'max'
        # 等原始 token，直接 findText 匹配不到会静默回落到第 0 项 Avg。
        raw_role = m.get('role', ch.role if ch else '')
        return {
            'name': name,
            'label': m.get('label', display_name(name)),
            'orig': m.get('orig', name),
            'kind': m.get('kind', ch.kind if ch else 'other'),
            'height': m.get('height', ch.height if ch else None),
            'units': m.get('units', ch.units if ch else ''),
            'role': _norm_role(raw_role),
            'color': m.get('color', ch.color if ch else ''),
            'sd_col': m.get('sd_col', ch.sd_col if ch else ''),
            'max_col': m.get('max_col', ch.max_col if ch else ''),
            'min_col': m.get('min_col', ch.min_col if ch else ''),
            'visible': m.get('enabled', True),
        }

    def _refresh_table(self):
        self.table.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            # 启用
            cb = QCheckBox()
            cb.setChecked(row['visible'])
            cb.stateChanged.connect(lambda _s, row_r=r: self._sync_visible(row_r))
            self.table.setCellWidget(r, 0, cb)
            # 通道（Label / 规范名）
            it = QTableWidgetItem(row['label'])
            it.setData(Qt.UserRole, row['name'])
            self.table.setItem(r, 1, it)
            # 原始标签
            it_orig = QTableWidgetItem(row.get('orig', row['name']))
            it_orig.setFlags(it_orig.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 2, it_orig)
            # 类别
            self.table.setItem(r, 3, QTableWidgetItem(_kind_label(row['kind'])))
            # 高度
            h = row['height']
            self.table.setItem(r, 4, QTableWidgetItem(f'{h:g}' if h is not None else ''))
            # 单位
            self.table.setItem(r, 5, QTableWidgetItem(row['units'] or ''))
            # 颜色
            color_it = QTableWidgetItem('')
            if row['color']:
                color_it.setBackground(QBrush(QColor(row['color'])))
            self.table.setItem(r, 6, color_it)
            # 统计量
            stats = self._compute_stats(row['name'])
            for c, k in enumerate(('mean', 'min', 'max'), start=7):
                itc = QTableWidgetItem(stats.get(k, '—'))
                itc.setFlags(itc.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, itc)
        self._adjust_column_widths()

    def eventFilter(self, obj, event):
        """监听表格 viewport resize，窗口/分割器变化时重新均分列宽。"""
        from PySide6.QtCore import QEvent
        if obj is self.table.viewport() and event.type() == QEvent.Resize:
            self._adjust_column_widths()
        return super().eventFilter(obj, event)

    def _adjust_column_widths(self):
        """先让每列完整显示内容，再把多余空间均分给所有列。"""
        if (not self._rows or self._adjusting_columns or
                self.table.viewport().width() <= 0):
            return
        new_w = self.table.viewport().width()
        if abs(new_w - self._last_viewport_width) <= 2:
            return
        self._adjusting_columns = True
        self._last_viewport_width = new_w
        try:
            hdr = self.table.horizontalHeader()
            # 按内容显示完整
            self.table.resizeColumnsToContents()
            # 全部设为 Interactive，使用户可拖动
            for c in range(self.table.columnCount()):
                hdr.setSectionResizeMode(c, QHeaderView.Interactive)
            hdr.setStretchLastSection(False)
            # 均分多余空间
            viewport_width = self.table.viewport().width()
            total = sum(hdr.sectionSize(c)
                        for c in range(self.table.columnCount()))
            extra = viewport_width - total
            if extra > 0:
                per = extra / self.table.columnCount()
                for c in range(self.table.columnCount()):
                    hdr.resizeSection(c, int(hdr.sectionSize(c) + per))
        finally:
            self._adjusting_columns = False

    def _compute_stats(self, name: str) -> dict:
        out = {'mean': '—', 'min': '—', 'max': '—'}
        if name not in self._ds.df.columns:
            return out
        s = self._ds.numeric_series(name)
        if s.notna().any():
            out['mean'] = f'{float(s.mean()):.3f}'
            out['min'] = f'{float(s.min()):.3f}'
            out['max'] = f'{float(s.max()):.3f}'
        return out

    # ------------------------------------------------------------------
    # 选择 / 属性面板同步
    # ------------------------------------------------------------------
    def _current_rows(self) -> list[int]:
        return sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})

    def _on_selection_changed(self):
        rows = self._current_rows()
        if not rows:
            return
        r = rows[0]
        row = self._rows[r]

        self.p_type.blockSignals(True)
        self.p_role.blockSignals(True)
        self.p_height.blockSignals(True)
        self.p_suffix.blockSignals(True)
        self.p_visible.blockSignals(True)
        self.p_sd.blockSignals(True)
        self.p_max.blockSignals(True)
        self.p_min.blockSignals(True)

        idx = next((i for i, (k, _) in enumerate(_KIND_ITEMS)
                    if k == row['kind']), len(_KIND_ITEMS) - 1)
        self.p_type.setCurrentIndex(idx)

        ridx = self.p_role.findText(row['role'])
        self.p_role.setCurrentIndex(max(0, ridx))

        self.p_label.setText(row['label'])
        self.p_units.setText(row['units'])
        self.p_height.setValue(row['height'] or 0.0)
        # 后缀回显：标签末尾的单字母（前一位是统计词）
        toks = row['label'].split()
        letter = ''
        if len(toks) >= 2 and len(toks[-1]) == 1 and toks[-1].isalpha() \
                and _STAT_TOKEN_RE.match(toks[-2]):
            letter = toks[-1]
        self.p_suffix.setCurrentText(letter)
        self.p_color_line.setText(row['color'])
        self.p_visible.setChecked(row['visible'])

        self._refresh_assoc_combos()
        self._set_combo(self.p_sd, row['sd_col'])
        self._set_combo(self.p_max, row['max_col'])
        self._set_combo(self.p_min, row['min_col'])
        self._update_assoc_visibility(row['role'] == 'Avg')

        self.p_type.blockSignals(False)
        self.p_role.blockSignals(False)
        self.p_height.blockSignals(False)
        self.p_suffix.blockSignals(False)
        self.p_visible.blockSignals(False)
        self.p_sd.blockSignals(False)
        self.p_max.blockSignals(False)
        self.p_min.blockSignals(False)

        self._update_plots(row['name'])

    def _refresh_assoc_combos(self):
        names = ['<none>'] + [r['label'] for r in self._rows]
        data = [''] + [r['name'] for r in self._rows]
        for cb in (self.p_sd, self.p_max, self.p_min):
            cb.blockSignals(True)
            old = cb.currentData()
            cb.clear()
            for n, d in zip(names, data):
                cb.addItem(n, d)
            cb.setCurrentIndex(0)
            if old:
                idx = cb.findData(old)
                if idx >= 0:
                    cb.setCurrentIndex(idx)
            cb.blockSignals(False)

    def _set_combo(self, cb: QComboBox, actual_name: str):
        cb.blockSignals(True)
        idx = cb.findData(actual_name) if actual_name else 0
        cb.setCurrentIndex(max(0, idx))
        cb.blockSignals(False)

    def _update_assoc_visibility(self, show: bool):
        """仅 Avg 通道显示 Std. dev./Max./Min. 关联下拉。"""
        for w in (self._l_sd, self.p_sd, self._l_max, self.p_max,
                  self._l_min, self.p_min):
            w.setVisible(show)

    def _apply_kind(self):
        rows = self._current_rows()
        if not rows:
            return
        kind = self.p_type.currentData()
        for r in rows:
            self._rows[r]['kind'] = kind
            self.table.item(r, 3).setText(_kind_label(kind))

    def _apply_role(self):
        rows = self._current_rows()
        if not rows:
            return
        role = self.p_role.currentText()
        for r in rows:
            self._rows[r]['role'] = role
            if role != 'Avg':
                self._rows[r]['sd_col'] = ''
                self._rows[r]['max_col'] = ''
                self._rows[r]['min_col'] = ''
        self._update_assoc_visibility(role == 'Avg')
        if role != 'Avg':
            self._refresh_assoc_combos()

    def _apply_label(self):
        rows = self._current_rows()
        if not rows:
            return
        label = self.p_label.text().strip()
        for r in rows:
            self._rows[r]['label'] = label
            self.table.item(r, 1).setText(label)
        self._refresh_assoc_combos()

    def _apply_units(self):
        rows = self._current_rows()
        if not rows:
            return
        units = self.p_units.text().strip()
        for r in rows:
            self._rows[r]['units'] = units
            self.table.item(r, 5).setText(units)

    def _apply_height(self):
        rows = self._current_rows()
        if not rows:
            return
        h = self.p_height.value()
        for r in rows:
            self._rows[r]['height'] = h or None
            self.table.item(r, 4).setText(f'{h:g}' if h else '')

    def _apply_suffix(self, *args):
        """后缀下拉：把所选通道的标准化标签追加/替换末尾字母
        （`SPEED 120m AVG` + A → `SPEED 120m AVG A`）；选（空）则去掉。"""
        rows = self._current_rows()
        if not rows:
            return
        letter = self.p_suffix.currentText().strip().upper()
        if letter and not re.fullmatch(r'[A-Z]', letter):
            letter = ''
        for r in rows:
            base = _strip_suffix_letter(self._rows[r]['label'])
            new_label = base + (f' {letter}' if letter else '')
            self._rows[r]['label'] = new_label
            self.table.item(r, 1).setText(new_label)
        self._refresh_assoc_combos()

    def _regen_labels(self):
        """按规则重算标准化名：`SPEED 120m W AVG`（类型全大写完整单词 +
        高度 + 方位 + 统计）；同类型同高度多支传感器按原始列名主干识别，
        自动加后缀 A/B/C…，单支默认不加。"""
        kind_base = {'speed': 'Speed', 'speed_sd': 'Speed', 'dir': 'Dir',
                     'temp': 'Temp', 'pres': 'Pres', 'rh': 'RH'}
        bases = []
        for row in self._rows:
            base = kind_base.get(row['kind'])
            if base is None:
                bases.append(None)
                continue
            orient = _extract_orient(row.get('orig') or row['label'])
            stat = row['role'] if row['role'] in ('Avg', 'SD', 'Min',
                                                  'Max', 'Gust') else ''
            bases.append(build_canon_name(base, row['height'], orient, stat))
        # 传感器后缀：按（类型, 高度）分组，组内按传感器主干去重
        groups = {}
        for i, row in enumerate(self._rows):
            if bases[i] is None:
                continue
            groups.setdefault((row['kind'], row['height']), []).append(i)
        letters = {}
        for rows_idx in groups.values():
            order = []
            key_of = {}
            for i in rows_idx:
                key = _sensor_key_of(self._rows[i].get('orig')
                                     or self._rows[i]['name'])
                key_of[i] = key
                if key not in order:
                    order.append(key)
            if len(order) <= 1:
                continue
            for i in rows_idx:
                letters[i] = chr(ord('A') + order.index(key_of[i]))
        # 写回标签与表格
        for i, row in enumerate(self._rows):
            if bases[i] is None:
                continue
            letter = letters.get(i, '')
            new_label = bases[i] + (f' {letter}' if letter else '')
            row['label'] = new_label
            self.table.item(i, 1).setText(new_label)
        self._refresh_assoc_combos()
        self._on_selection_changed()

    def _choose_color(self):
        rows = self._current_rows()
        if not rows:
            return
        init = QColor(self._rows[rows[0]].get('color', '#000000') or '#000000')
        c = QColorDialog.getColor(init, self)
        if not c.isValid():
            return
        hex_c = c.name()
        self.p_color_line.setText(hex_c)
        for r in rows:
            self._rows[r]['color'] = hex_c
            self.table.item(r, 6).setBackground(QBrush(c))

    def _apply_visible(self):
        rows = self._current_rows()
        if not rows:
            return
        visible = self.p_visible.isChecked()
        for r in rows:
            self._rows[r]['visible'] = visible
            cb = self.table.cellWidget(r, 0)
            cb.blockSignals(True)
            cb.setChecked(visible)
            cb.blockSignals(False)

    def _apply_assoc(self):
        rows = self._current_rows()
        if not rows:
            return
        r = rows[0]
        self._rows[r]['sd_col'] = self.p_sd.currentData() or ''
        self._rows[r]['max_col'] = self.p_max.currentData() or ''
        self._rows[r]['min_col'] = self.p_min.currentData() or ''

    def _sync_visible(self, r: int):
        visible = self.table.cellWidget(r, 0).isChecked()
        self._rows[r]['visible'] = visible
        if self._current_rows() and self._current_rows()[0] == r:
            self.p_visible.blockSignals(True)
            self.p_visible.setChecked(visible)
            self.p_visible.blockSignals(False)

    # ------------------------------------------------------------------
    # 底部三张小图
    # ------------------------------------------------------------------
    def _update_plots(self, name: str):
        if name not in self._ds.df.columns:
            for c in (self.pdf_canvas, self.diurnal_canvas, self.monthly_canvas):
                c.clear(tr('无数据'))
            return
        s = self._ds.numeric_series(name).dropna()
        if s.empty:
            for c in (self.pdf_canvas, self.diurnal_canvas, self.monthly_canvas):
                c.clear(tr('无有效数据'))
            return

        # PDF
        try:
            counts, edges = np.histogram(s.values, bins=20)
            centers = (edges[:-1] + edges[1:]) / 2
            self.pdf_canvas.plot_bar(
                centers, counts, xlabel='Value',
                ylabel='Frequency')
        except Exception:
            self.pdf_canvas.clear(tr('PDF 计算失败'))

        # Mean Diurnal Profile
        try:
            hourly = s.groupby(s.index.hour).mean().reindex(range(24))
            x = hourly.index.values.astype(float)
            y = hourly.values.astype(float)
            self.diurnal_canvas.plot_lines(
                [('Mean', x, y)], xlabel='Hour of Day',
                ylabel='Mean Value', xtick_fmt='hour')
        except Exception:
            self.diurnal_canvas.clear(tr('日变化计算失败'))

        # Monthly Statistics
        try:
            groups = []
            for m in range(1, 13):
                sub = s[s.index.month == m]
                if len(sub) >= 1:
                    groups.append((f'{m}月', {
                        'min': float(sub.min()),
                        'q1': float(sub.quantile(0.25)),
                        'med': float(sub.median()),
                        'q3': float(sub.quantile(0.75)),
                        'max': float(sub.max()),
                        'mean': float(sub.mean()),
                        'n': len(sub),
                    }))
            if groups:
                self.monthly_canvas.plot_box(
                    groups, xlabel='Month', ylabel='Value')
            else:
                self.monthly_canvas.clear(tr('无月度数据'))
        except Exception:
            self.monthly_canvas.clear(tr('月统计计算失败'))

    # ------------------------------------------------------------------
    # 按钮：添加 / 删除 / 颜色 / 模板
    # ------------------------------------------------------------------
    def _add_column(self):
        dlg = AddCalculatedColumnDialog(self._ds.df, self)
        if dlg.exec() != QDialog.Accepted:
            return
        res = dlg.result()
        if res is None:
            return
        name, series = res
        self._ds.df[name] = series
        row = {
            'name': name,
            'label': display_name(name),
            'orig': name,
            'kind': 'other',
            'height': None,
            'units': '',
            'role': 'Avg',
            'color': '',
            'sd_col': '',
            'max_col': '',
            'min_col': '',
            'visible': True,
        }
        self._rows.append(row)
        r = len(self._rows) - 1
        self._refresh_table()
        self.table.selectRow(r)

    def _delete_columns(self):
        rows = self._current_rows()
        if not rows:
            return
        names = [self._rows[r]['name'] for r in rows]
        for name in names:
            if name in self._ds.df.columns:
                del self._ds.df[name]
        for r in sorted(rows, reverse=True):
            del self._rows[r]
        self._refresh_table()
        self._refresh_assoc_combos()

    def _assign_default_colors(self):
        for i, row in enumerate(self._rows):
            row['color'] = _DEFAULT_COLORS[i % len(_DEFAULT_COLORS)]
        self._refresh_table()

    def _save_template(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '保存通道模板', 'channels.template.json',
            'JSON (*.json);;所有文件 (*.*)')
        if not path:
            return
        payload = []
        for row in self._rows:
            payload.append({
                'name': row['name'], 'label': row['label'],
                'orig': row.get('orig', row['name']),
                'kind': row['kind'], 'height': row['height'],
                'units': row['units'], 'role': row['role'],
                'color': row['color'], 'sd_col': row['sd_col'],
                'max_col': row['max_col'], 'min_col': row['min_col'],
                'visible': row['visible'],
            })
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _load_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '加载通道模板', '',
            'JSON (*.json);;所有文件 (*.*)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, tr('加载失败'), f'{e}')
            return
        mapping = {r['name']: r for r in self._rows}
        for item in payload:
            name = item.get('name')
            if name in mapping:
                for k in ('label', 'orig', 'kind', 'height', 'units', 'role',
                          'color', 'sd_col', 'max_col', 'min_col', 'visible'):
                    if k in item:
                        mapping[name][k] = item[k]
        self._refresh_table()
        self._on_selection_changed()

    def _on_auto_assoc_changed(self):
        """自动关联开关状态变化。"""
        if self.chk_auto_assoc.isChecked():
            self._auto_associate()
        else:
            for row in self._rows:
                row['sd_col'] = ''
                row['max_col'] = ''
                row['min_col'] = ''
        self._refresh_table()
        self._refresh_assoc_combos()
        rows = self._current_rows()
        if rows:
            self._on_selection_changed()

    def _auto_associate(self):
        """为每个 Avg 通道自动匹配同类型、同高度、同方位的 SD/Max/Min。"""

        def _assoc_kind(row: dict) -> str:
            # Speed SD 的 kind 历史上被单独标记，但关联时应归到 Speed 组
            return KIND_SPEED if row['kind'] == KIND_SPEED_SD else row['kind']

        # 先清空已有自动关联
        for row in self._rows:
            row['sd_col'] = ''
            row['max_col'] = ''
            row['min_col'] = ''
        # 建立辅助索引：按（归一化类型, 高度, 方位）分组
        idx = {}
        for r, row in enumerate(self._rows):
            key = (_assoc_kind(row), row['height'], _extract_orient(row['name']))
            idx.setdefault(key, {})[row['role']] = row['name']
        # 为 Avg 通道填充关联
        for row in self._rows:
            if row['role'] != 'Avg':
                continue
            key = (_assoc_kind(row), row['height'], _extract_orient(row['name']))
            mapping = idx.get(key, {})
            row['sd_col'] = mapping.get('SD', '')
            row['max_col'] = mapping.get('Max', '')
            row['min_col'] = mapping.get('Min', '')

    # ------------------------------------------------------------------
    # 接受：写回 Dataset
    # ------------------------------------------------------------------
    def _on_ok(self):
        # Data Set 页
        self._ds.name = self.ds_name.text().strip() or self._ds.name
        self._ds.description = self.ds_desc.toPlainText().strip()
        # 经纬度/海拔：若原本缺失且用户未改动（仍为 0），则保持缺失，避免
        # QDoubleSpinBox 把 NaN clamp 成 90/180/9000 这样的假默认值写回。
        if not (getattr(self, '_lat_missing', False) and self.ds_lat.value() == 0.0):
            self._ds.attrs['lat'] = self.ds_lat.value()
        if not (getattr(self, '_lon_missing', False) and self.ds_lon.value() == 0.0):
            self._ds.attrs['lon'] = self.ds_lon.value()
        if not (getattr(self, '_elev_missing', False) and self.ds_elev.value() == 0.0):
            self._ds.attrs['elevation'] = self.ds_elev.value()
        self._ds.timestamp_position = self.ds_stamp.currentText().lower()
        self._ds.calm_threshold = self.ds_calm.value()
        if self.chk_invalid.isChecked():
            self._ds.invalid_value = self.spin_invalid.value()
        else:
            self._ds.invalid_value = None

        # 数据列
        meta = []
        self._ds.channels.clear()
        for row in self._rows:
            meta.append({
                'name': row['name'], 'label': row['label'],
                'orig': row.get('orig', row['name']),
                'kind': row['kind'], 'height': row['height'],
                'units': row['units'], 'role': row['role'],
                'color': row['color'], 'sd_col': row['sd_col'],
                'max_col': row['max_col'], 'min_col': row['min_col'],
                'enabled': row['visible'],
            })
            if row['visible']:
                self._ds.add_channel(Channel(
                    name=row['name'], kind=row['kind'],
                    height=row['height'], units=row['units'],
                    role=row['role'], color=row['color'],
                    sd_col=row['sd_col'], max_col=row['max_col'],
                    min_col=row['min_col']))
        self._ds.import_meta = meta

        # 无效值标记
        if self._ds.invalid_value is not None and not self._ds.df.empty:
            val = self._ds.invalid_value
            mask = (self._ds.df == val).any(axis=1)
            if mask.any():
                self._ds.set_flag_mask(mask)

        self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self._load_dataset_tab()

    def _load_dataset_tab(self):
        ds = self._ds
        self.ds_name.setText(ds.name)
        self.ds_desc.setPlainText(ds.description)
        # 记录经纬度/海拔是否原本缺失，便于保存时区分「未设置 0」与「真实 0」
        self._lat_missing = ds.attrs.get('lat') is None
        self._lon_missing = ds.attrs.get('lon') is None
        self._elev_missing = ds.attrs.get('elevation') is None
        self.ds_lat.setValue(_to_float(ds.attrs.get('lat')))
        self.ds_lon.setValue(_to_float(ds.attrs.get('lon')))
        self.ds_elev.setValue(_to_float(ds.attrs.get('elevation')))
        pos = ds.timestamp_position.capitalize()
        idx = self.ds_stamp.findText(pos)
        self.ds_stamp.setCurrentIndex(max(0, idx))
        self.ds_calm.setValue(ds.calm_threshold or 0.0)
        if ds.invalid_value is not None:
            self.chk_invalid.setChecked(True)
            self.spin_invalid.setValue(ds.invalid_value)
        else:
            self.chk_invalid.setChecked(False)

        df = ds.df
        if not df.empty:
            self.lbl_start.setText(str(df.index[0]))
            self.lbl_end.setText(str(df.index[-1]))
            dur = df.index[-1] - df.index[0]
            days = dur.total_seconds() / 86400
            self.lbl_duration.setText(f'{days:.1f} days')
            try:
                dt = (df.index[1] - df.index[0]).total_seconds() / 60
                self.lbl_step.setText(f'{dt:.0f} minutes')
            except Exception:
                self.lbl_step.setText('—')
        else:
            self.lbl_start.setText('—')
            self.lbl_end.setText('—')
            self.lbl_duration.setText('—')
            self.lbl_step.setText('—')
