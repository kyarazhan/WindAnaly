"""Flags 菜单 8 个核心对话框（WindAnaly）。

按 Windographer 风格实现：
1) Manual Flag：时间区间 + 通道勾选 + 标记应用/移除 + 数据表 + 时序预览
2) Flag By Scatter Plot：X/Y 选择 + 散点图 + 刷选/框选 + 应用标记
3) Flag With Rules：规则表 + 可勾选规则 + Test/Execute
4) Flag Tower Shading：风速仪对 + 扇区 + 中位数比/散点比双图
5) Inspect and Remove Flags：标记筛选 + 通道 + 时序/统计展示 + 取消标记
6) Define Flags：标记类型表（颜色/参与计算/显示）
7) Define Favorite Flags：常用标记定义
8) View Favorite Flag Rules：常用标记规则查看
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateTimeEdit,
    QDialog, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QRadioButton, QSpinBox, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.dataset import Dataset, Flag
from ui.modules.analysis_tabs import display_name
from ui.modules.plot import PlotCanvas
from core.i18n import tr


# ------------------------------------------------------------------ 工具函数
_NUMERIC_KINDS = {'speed', 'dir', 'temp', 'pres', 'rh', 'ti', 'synthetic'}


def _numeric_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind in _NUMERIC_KINDS]


def _speed_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind == 'speed']


def _dir_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind == 'dir']


def _to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors='coerce')


def _col_disp(ds: Dataset, col: str) -> str:
    return display_name(col) if col in ds.channels else col


def _disp_col(ds: Dataset, disp: str) -> str:
    for c in ds.channels:
        if display_name(c) == disp:
            return c
    return disp


# ------------------------------------------------------------------ 可复用组件
class _CheckList(QWidget):
    """带「全选」复选框的多选列表。"""

    def __init__(self, title: str = '', parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.sel_all = QCheckBox(tr('Select all'))
        self.sel_all.stateChanged.connect(self._on_all)
        top.addWidget(self.sel_all)
        top.addStretch(1)
        if title:
            top.insertWidget(0, QLabel(title))
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.list)

    def add_items(self, items: list[str]):
        self.list.clear()
        for t in items:
            it = QListWidgetItem(t)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.list.addItem(it)

    def checked(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.text())
        return out

    def _on_all(self, state):
        st = Qt.Checked if state == Qt.Checked.value else Qt.Unchecked
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(st)


class _DateTimeRow(QWidget):
    """标签 + QDateTimeEdit 组合。"""

    def __init__(self, label: str, dt: datetime, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(label))
        self.edit = QDateTimeEdit(dt)
        self.edit.setDisplayFormat('yyyy-MM-dd HH:mm')
        self.edit.setCalendarPopup(True)
        h.addWidget(self.edit)

    def get_dt(self) -> datetime:
        return self.edit.dateTime().toPython()

    def set_dt(self, dt: datetime):
        from PySide6.QtCore import QDateTime
        self.edit.setDateTime(QDateTime.fromString(
            dt.strftime('%Y-%m-%d %H:%M'), 'yyyy-MM-dd HH:mm'))


class _ColorBlock(QWidget):
    """颜色块显示。"""

    def __init__(self, color: str, size: int = 18, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setStyleSheet(f'background:{color};border:1px solid #888;')


# ------------------------------------------------------------------ 标记应用公共对话框
class _FlagApplyBase(QDialog):
    """含 Flag 选择 + Apply/Remove/Remove All 按钮的公共底部区。"""

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self._ds = ds

    def _flag_names(self) -> list[str]:
        return list(self._ds.flag_registry.keys())

    def _make_flag_combo(self, label: str = 'Flag to apply or remove:'):
        h = QHBoxLayout()
        h.addWidget(QLabel(label))
        combo = QComboBox()
        for n in self._flag_names():
            combo.addItem(n)
        h.addWidget(combo)
        h.addStretch(1)
        return combo, h

    def _make_apply_buttons(self, apply_slot, remove_slot, remove_all_slot):
        v = QVBoxLayout()
        v.setSpacing(6)
        btn_apply = QPushButton(tr('Apply Flag'))
        btn_rem = QPushButton(tr('Remove Flag from Selection'))
        btn_rem_all = QPushButton(tr('Remove All Flags from Selection'))
        btn_apply.clicked.connect(apply_slot)
        btn_rem.clicked.connect(remove_slot)
        btn_rem_all.clicked.connect(remove_all_slot)
        v.addWidget(btn_apply)
        v.addWidget(btn_rem)
        v.addWidget(btn_rem_all)
        return v


# ------------------------------------------------------------------ 1. Flag Manually
class ManualFlagTableSettings(QDialog):
    """Table Settings：选择表格可见列（按类型 / 按名称）、着色与标签截断。"""

    KIND_ROWS = [
        ('Wind speed', 'speed'),
        ('Vertical wind speed', 'wz'),
        ('Wind direction', 'dir'),
        ('Temperature', 'temp'),
        ('Air pressure', 'pres'),
        ('Relative humidity', 'rh'),
        ('Other', 'other'),
    ]
    STAT_COLS = [('Mean', 'Avg'), ('SD', 'SD'), ('Max', 'Max'), ('Min', 'Min')]

    def __init__(self, cfg: dict, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Table Settings...'))
        self.resize(520, 560)
        self._ds = ds
        self._cfg = dict(cfg)
        self.result_cfg: dict | None = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr('Choose visible data columns by')))
        hb = QHBoxLayout()
        self.rb_types = QRadioButton(tr('data column types'))
        self.rb_names = QRadioButton(tr('data column names'))
        (self.rb_types if cfg.get('mode', 'types') == 'types'
         else self.rb_names).setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self.rb_types)
        bg.addButton(self.rb_names)
        hb.addStretch(1)
        hb.addWidget(self.rb_types)
        hb.addWidget(self.rb_names)
        hb.addStretch(1)
        lay.addLayout(hb)

        self.stack = QStackedWidget()
        # 类型页：kind × (Mean/SD/Max/Min) 复选矩阵
        types_w = QWidget()
        tv = QVBoxLayout(types_w)
        grid = QGridLayout()
        grid.addWidget(QLabel(tr('Data column type')), 0, 0)
        for c, (label, _role) in enumerate(self.STAT_COLS, start=1):
            grid.addWidget(QLabel(tr(label)), 0, c)
        self._type_checks = {}
        kinds_in_ds = {ch.kind for ch in ds.channels.values()}
        for r, (label, kind) in enumerate(self.KIND_ROWS, start=1):
            grid.addWidget(QLabel(tr(label)), r, 0)
            for c, (_lb, role) in enumerate(self.STAT_COLS, start=1):
                cb = QCheckBox()
                key = (kind, role)
                cb.setChecked(key in cfg.get('types', set()))
                cb.setEnabled(kind in kinds_in_ds or kind == 'other')
                self._type_checks[key] = cb
                grid.addWidget(cb, r, c,
                               alignment=Qt.AlignHCenter | Qt.AlignVCenter)
        tv.addLayout(grid)
        tv.addStretch(1)
        self.stack.addWidget(types_w)
        # 名称页：全部通道复选列表
        names_w = QWidget()
        nv = QVBoxLayout(names_w)
        self.names_list = QListWidget()
        self.names_list.setSelectionMode(QAbstractItemView.NoSelection)
        for col in ds.df.columns:
            it = QListWidgetItem(display_name(col))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if col in cfg.get('names', set())
                             else Qt.Unchecked)
            it.setData(Qt.UserRole, col)
            self.names_list.addItem(it)
        nv.addWidget(self.names_list)
        self.stack.addWidget(names_w)
        lay.addWidget(self.stack, 1)
        self.rb_types.toggled.connect(
            lambda on: self.stack.setCurrentIndex(0 if on else 1))
        self.stack.setCurrentIndex(0 if self.rb_types.isChecked() else 1)

        self.chk_color = QCheckBox(
            tr('Color code cells according to data column type'))
        self.chk_color.setChecked(cfg.get('color_code', True))
        lay.addWidget(self.chk_color)
        sh = QHBoxLayout()
        sh.addWidget(QLabel(tr('Shorten labels longer than')))
        self.spin_short = QSpinBox()
        self.spin_short.setRange(0, 60)
        self.spin_short.setValue(cfg.get('shorten', 6))
        sh.addWidget(self.spin_short)
        sh.addWidget(QLabel(tr('characters')))
        sh.addStretch(1)
        lay.addLayout(sh)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('OK'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _on_ok(self):
        cfg = {'mode': 'types' if self.rb_types.isChecked() else 'names',
               'color_code': self.chk_color.isChecked(),
               'shorten': self.spin_short.value(),
               'types': set(), 'names': set()}
        if cfg['mode'] == 'types':
            for key, cb in self._type_checks.items():
                if cb.isChecked():
                    cfg['types'].add(key)
            if not cfg['types']:
                QMessageBox.warning(self, tr('Table Settings...'),
                                    tr('Select at least one checkbox'))
                return
        else:
            for i in range(self.names_list.count()):
                it = self.names_list.item(i)
                if it.checkState() == Qt.Checked:
                    cfg['names'].add(it.data(Qt.UserRole))
            if not cfg['names']:
                QMessageBox.warning(self, tr('Table Settings...'),
                                    tr('Select at least one checkbox'))
                return
        self.result_cfg = cfg
        self.accept()


class ManualFlagDialog(_FlagApplyBase):
    """Flag Manually：原版三区布局。

    左：时间区间 + 数据列勾选 + 更新选项 + 标记下拉 + 三个 Segment 按钮；
    中：时序图（选段黄色高亮带，无重复图例，y 轴从 0 起）+ 数据表；
    右：图例复选网格——每行三个复选框（图/表/标记）+ 颜色样 + 通道名，
        All wind speed / direction columns 快选只勾选平均值（Avg）列。
    """

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(ds, parent)
        self.setWindowTitle(tr('Flag Manually'))
        self.resize(1500, 900)
        self._info = ''
        self._building = False
        self._table_cfg = {'mode': 'types',
                           'types': {('speed', 'Avg')},
                           'names': set(),
                           'color_code': True,
                           'shorten': 6}
        self._palette = ['#1f4e79', '#e67e22', '#27ae60', '#8e44ad',
                         '#16a085', '#c0392b', '#2c3e50', '#d35400',
                         '#7f8c8d', '#2471a3']
        t0 = ds.df.index[0] if len(ds.df) else datetime.now()
        t1 = ds.df.index[-1] if len(ds.df) else datetime.now()

        root = QVBoxLayout(self)
        body = QHBoxLayout()

        # ---- 左：时间区间 / 数据列 / 标记操作 ----
        left = QWidget()
        left.setFixedWidth(280)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)
        lv.addWidget(QLabel(tr('Time interval:')))
        self.start = _DateTimeRow(tr('Start:'), t0)
        self.end = _DateTimeRow(tr('End:'), t1)
        lv.addWidget(self.start)
        lv.addWidget(self.end)
        lv.addSpacing(8)
        lv.addWidget(QLabel(tr('Data columns:')))
        self.col_list = QListWidget()
        self.col_list.setSelectionMode(QAbstractItemView.NoSelection)
        for col in ds.df.columns:
            it = QListWidgetItem(display_name(col))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, col)
            self.col_list.addItem(it)
        lv.addWidget(self.col_list, 1)
        self.chk_update = QCheckBox(
            tr('Update this list when I select a segment'))
        self.chk_update.setChecked(True)
        lv.addWidget(self.chk_update)
        lv.addSpacing(8)
        self.flag_combo, fh = self._make_flag_combo(
            tr('Flag to apply or remove:'))
        lv.addLayout(fh)
        for label, slot in (
                (tr('Apply Flag to Segment'), self._apply_segment),
                (tr('Remove Flag from Segment'), self._remove_segment),
                (tr('Remove All Flags from Segment'),
                 self._remove_all_segment)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            lv.addWidget(b)
        lv.addStretch(1)
        body.addWidget(left)

        # ---- 中：图 + 表 ----
        mid = QSplitter(Qt.Vertical)
        self.plot = PlotCanvas('')
        self.plot.setMinimumHeight(220)
        mid.addWidget(self.plot)
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ContiguousSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        mid.addWidget(self.table)
        mid.setSizes([380, 420])
        body.addWidget(mid, 1)

        # ---- 右：图例复选网格（3 列复选：图 / 表 / 标记）----
        right = QWidget()
        right.setFixedWidth(300)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 8, 8, 8)
        self.chk_all_speed = QCheckBox(tr('All wind speed columns'))
        self.chk_all_dir = QCheckBox(tr('All wind direction columns'))
        rv.addWidget(self.chk_all_speed)
        rv.addWidget(self.chk_all_dir)
        self.legend = QTableWidget(0, 4)
        self.legend.verticalHeader().setVisible(False)
        self.legend.horizontalHeader().setVisible(False)
        self.legend.setSelectionMode(QAbstractItemView.NoSelection)
        self.legend.setEditTriggers(QTableWidget.NoEditTriggers)
        self.legend.setShowGrid(False)
        self.legend.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Fixed)
        for c in range(3):
            self.legend.setColumnWidth(c, 24)
        self.legend.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        self.legend.verticalHeader().setDefaultSectionSize(20)
        rv.addWidget(self.legend, 1)
        body.addWidget(right)
        root.addLayout(body, 1)

        # ---- 底部：Help | Table Settings | Cancel/OK ----
        bb = QHBoxLayout()
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, tr('Help'),
            tr('Select a time interval, check the data columns, then click '
               'Apply Flag to Segment. Select rows in the table to choose a '
               'segment; the chart highlights it in yellow.')))
        bb.addWidget(help_btn)
        bb.addStretch(1)
        tbl_btn = QPushButton(tr('Table Settings...'))
        tbl_btn.clicked.connect(self._table_settings)
        bb.addWidget(tbl_btn)
        bb.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('OK'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        bb.addWidget(cancel)
        bb.addWidget(ok)
        root.addLayout(bb)

        # ---- 事件 ----
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._refresh_all)
        for w in (self.start.edit, self.end.edit):
            w.dateTimeChanged.connect(lambda _c: self._debounce.start())
        self.chk_all_speed.stateChanged.connect(
            lambda _s: self._quick_filter('speed'))
        self.chk_all_dir.stateChanged.connect(
            lambda _s: self._quick_filter('dir'))

        self._build_legend()
        self._refresh_all()

    # ---- 图例复选网格 ----
    def _build_legend(self):
        ds = self._ds
        self._building = True
        self.legend.setRowCount(len(ds.df.columns))
        checked_n = 0
        for r, col in enumerate(ds.df.columns):
            ch = ds.channels.get(col)
            color = ch.color if ch is not None and ch.color else \
                self._palette[r % len(self._palette)]
            for c in range(3):
                cb = QCheckBox()
                cb.setStyleSheet('QCheckBox{margin-left:5px;}')
                cb.stateChanged.connect(lambda _s: self._on_legend_changed())
                self.legend.setCellWidget(r, c, cb)
            name_it = QTableWidgetItem(display_name(col))
            pm = QPixmap(14, 14)
            pm.fill(QColor(color))
            name_it.setIcon(QIcon(pm))
            name_it.setData(Qt.UserRole, col)
            name_it.setData(Qt.UserRole + 1, color)
            self.legend.setItem(r, 3, name_it)
            if ch is not None and ch.kind == 'speed' \
                    and (ch.role or 'Avg') == 'Avg' and checked_n < 3:
                for c in range(3):
                    self.legend.cellWidget(r, c).setChecked(True)
                checked_n += 1
        self._building = False

    def _legend_col(self, r: int) -> str:
        return self.legend.item(r, 3).data(Qt.UserRole)

    def _legend_checks(self, r: int) -> tuple[bool, bool, bool]:
        return tuple(self.legend.cellWidget(r, c).isChecked()
                     for c in range(3))

    def _set_legend_checks(self, r: int, g: bool, t: bool, f: bool):
        for c, v in zip(range(3), (g, t, f)):
            self.legend.cellWidget(r, c).setChecked(v)

    def _legend_rows(self):
        for r in range(self.legend.rowCount()):
            yield r, self._legend_col(r)

    def _graph_cols(self) -> list[str]:
        return [col for r, col in self._legend_rows()
                if self._legend_checks(r)[0]]

    def _table_cols(self) -> list[str]:
        return [col for r, col in self._legend_rows()
                if self._legend_checks(r)[1]]

    def _flag_cols(self) -> list[str]:
        return [col for r, col in self._legend_rows()
                if self._legend_checks(r)[2]]

    def _on_legend_changed(self):
        if self._building:
            return
        self._sync_left_from_flags()
        self._debounce.start()

    def _sync_left_from_flags(self):
        flags = set(self._flag_cols())
        for i in range(self.col_list.count()):
            it = self.col_list.item(i)
            it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in flags
                             else Qt.Unchecked)

    def _quick_filter(self, kind: str):
        """All wind speed / direction columns：只勾选该类型的平均值（Avg）列。"""
        if self._building:
            return
        self._building = True
        cb = self.chk_all_speed if kind == 'speed' else self.chk_all_dir
        on = cb.isChecked()
        for r, col in self._legend_rows():
            ch = self._ds.channels.get(col)
            if ch is not None and ch.kind == kind \
                    and (ch.role or 'Avg') == 'Avg':
                self._set_legend_checks(r, on, on, on)
        self._building = False
        self._sync_left_from_flags()
        self._debounce.start()

    def _short(self, text: str) -> str:
        n = self._table_cfg.get('shorten', 0)
        return text[:n] if n and len(text) > n else text

    # ---- 刷新 ----
    def _refresh_all(self):
        self._refresh_chart()
        self._refresh_table()

    def _refresh_chart(self):
        ds = self._ds
        cols = self._graph_cols()
        series = []
        unit = ''
        for c in cols:
            if c not in ds.df.columns:
                continue
            ch = ds.channels.get(c)
            if not unit and ch is not None and ch.units:
                unit = ch.units
            color = None
            for r, col in self._legend_rows():
                if col == c:
                    color = self.legend.item(r, 3).data(Qt.UserRole + 1)
                    break
            series.append((c, ds.df.index, _to_num(ds.df[c])))
            if color:
                self.plot.set_series_color(c, color)
        # 无重复图例（右侧网格即是图例）；风速等数值轴从 0 起
        self.plot.plot_lines(series, xlabel=tr('Time'),
                             ylabel=f'({unit})' if unit else '',
                             ymin=0, gap_detect=True, show_legend=False)

    def _refresh_table(self):
        ds = self._ds
        cols = self._table_cols()
        a, b = self.start.get_dt(), self.end.get_dt()
        if b < a:
            a, b = b, a
        sub = ds.df.loc[a:b]
        cap = 5000
        sub = sub.iloc[:cap]
        short = self._table_cfg.get('shorten', 0)
        headers = [tr('Start Time')]
        for c in cols:
            ch = ds.channels.get(c)
            u = ch.units if ch is not None else ''
            name = _col_disp(ds, c)
            if short:
                name = name[:short]
            headers.append(f'{name}\n({u})' if u else name)
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(sub))
        kind_tint = {'speed': QColor(219, 233, 249), 'dir': QColor(223, 240, 216),
                     'temp': QColor(253, 234, 218), 'pres': QColor(232, 224, 245),
                     'rh': QColor(223, 243, 245)}
        color_code = self._table_cfg.get('color_code', False)
        for r, (t, row) in enumerate(sub.iterrows()):
            it = QTableWidgetItem(t.strftime('%Y/%m/%d %H:%M'))
            self.table.setItem(r, 0, it)
            for ci, col in enumerate(cols, start=1):
                v = row.get(col, np.nan)
                ch = ds.channels.get(col)
                cell = QTableWidgetItem('' if pd.isna(v) else f'{v:.3f}')
                if color_code and ch is not None:
                    tint = kind_tint.get(ch.kind)
                    if tint is not None:
                        cell.setBackground(tint)
                self.table.setItem(r, ci, cell)

    # ---- 选段 ----
    def _selected_times(self):
        rows = sorted({ix.row() for ix in self.table.selectedIndexes()})
        if not rows:
            return None
        ts = [self.table.item(r, 0).text() for r in (rows[0], rows[-1])]
        return (pd.Timestamp(pd.to_datetime(ts[0])),
                pd.Timestamp(pd.to_datetime(ts[1])))

    @staticmethod
    def _to_ordinal(ts: pd.Timestamp) -> float:
        frac = (ts.hour * 3600 + ts.minute * 60 + ts.second) / 86400.0
        return ts.toordinal() + frac

    def _on_selection(self):
        seg = self._selected_times()
        if seg is None:
            self.plot.set_segment_band(None, None)
            return
        t0, t1 = seg
        self.plot.set_segment_band(self._to_ordinal(t0),
                                   self._to_ordinal(t1) + 1 / 86400.0)
        if not self.chk_update.isChecked():
            return
        # 数据列列表自动更新为选段内有有效数据的标记列
        ds = self._ds
        cols = self._flag_cols()
        sub = ds.df.loc[t0:t1]
        valid = {c for c in cols if c in sub.columns and sub[c].notna().any()}
        for i in range(self.col_list.count()):
            it = self.col_list.item(i)
            col = it.data(Qt.UserRole)
            it.setCheckState(Qt.Checked if col in valid else Qt.Unchecked)

    def _context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act = menu.addAction(tr('Copy Selection'))
        if menu.exec(self.table.viewport().mapToGlobal(pos)) is act:
            self._copy_selection()

    def _copy_selection(self):
        from PySide6.QtWidgets import QApplication
        sel = self.table.selectedIndexes()
        if not sel:
            return
        cells = {(ix.row(), ix.column()): ix.data() or '' for ix in sel}
        rows = sorted({r for r, _ in cells})
        cols = sorted({c for _, c in cells})
        lines = ['\t'.join(cells.get((r, c), '') for c in cols) for r in rows]
        QApplication.clipboard().setText('\n'.join(lines))

    # ---- 标记应用 ----
    def _segment_mask(self) -> pd.Series:
        seg = self._selected_times()
        if seg is not None:
            a, b = seg
        else:
            a, b = self.start.get_dt(), self.end.get_dt()
            if b < a:
                a, b = b, a
        idx = self._ds.df.index
        return (idx >= a) & (idx <= b)

    def _apply_segment(self):
        flag = self.flag_combo.currentText()
        mask = self._segment_mask()
        n = int(mask.sum())
        self._ds.apply_flag(flag, mask)
        self._info = f'Applied {flag} to {n} time steps'
        QMessageBox.information(self, tr('Flag Manually'), self._info)

    def _remove_segment(self):
        flag = self.flag_combo.currentText()
        mask = self._segment_mask()
        n = int(mask.sum())
        self._ds.remove_flag(flag, mask)
        self._info = f'Removed {flag} from {n} time steps'
        QMessageBox.information(self, tr('Flag Manually'), self._info)

    def _remove_all_segment(self):
        mask = self._segment_mask()
        n = int(mask.sum())
        for flag in list(self._ds.flag_registry.keys()):
            self._ds.remove_flag(flag, mask)
        self._info = f'Removed all flags from {n} time steps'
        QMessageBox.information(self, tr('Flag Manually'), self._info)

    # ---- Table Settings ----
    def _table_settings(self):
        dlg = ManualFlagTableSettings(self._table_cfg, self._ds, self)
        if dlg.exec() and dlg.result_cfg:
            cfg = dlg.result_cfg
            self._table_cfg = cfg
            # 应用可见列：三类复选同步勾选
            if cfg['mode'] == 'types':
                visible = set()
                for col in self._ds.df.columns:
                    ch = self._ds.channels.get(col)
                    if ch is None:
                        continue
                    role = ch.role or 'Avg'
                    if (ch.kind, role) in cfg['types']:
                        visible.add(col)
            else:
                visible = set(cfg['names'])
            self._building = True
            for r, col in self._legend_rows():
                on = col in visible
                self._set_legend_checks(r, on, on, on)
            self._building = False
            self._sync_left_from_flags()
            self._refresh_all()


# ------------------------------------------------------------------ 2. Flag By Scatter Plot
class FlagByScatterDialog(_FlagApplyBase):
    """散点图标记：X/Y 选择 + 散点 + 选择计数 + 应用标记。"""

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(ds, parent)
        self.setWindowTitle(tr('Flag By Scatter Plot'))
        self.resize(1000, 680)
        self._info = ''
        self._selected_mask = pd.Series(False, index=ds.df.index)

        root = QHBoxLayout(self)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)

        form = QFormLayout()
        self.x_combo = QComboBox()
        self.y_combo = QComboBox()
        for c in _numeric_cols(ds):
            self.x_combo.addItem(_col_disp(ds, c), c)
            self.y_combo.addItem(_col_disp(ds, c), c)
        form.addRow('Plot:', self.x_combo)
        form.addRow('versus:', self.y_combo)
        lv.addLayout(form)

        self.color_by_flag = QCheckBox(tr('Color code by flag'))
        lv.addWidget(self.color_by_flag)

        self.cols = _CheckList('Data columns to flag:')
        self.cols.add_items([_col_disp(ds, c) for c in ds.channels.keys()])
        lv.addWidget(self.cols)

        self.flag_combo, fh = self._make_flag_combo('Flag to apply or remove:')
        lv.addLayout(fh)

        btns = self._make_apply_buttons(
            self._apply, self._remove, self._remove_all)
        lv.addLayout(btns)

        filter_gb = QGroupBox(tr('Filter by'))
        fv = QVBoxLayout(filter_gb)
        self.filter_flag = QCheckBox(tr('Flag'))
        self.filter_unflagged = QCheckBox(tr('Unflagged data'))
        self.filter_synthesized = QCheckBox(tr('Synthesized'))
        self.filter_flag.setChecked(True)
        self.filter_unflagged.setChecked(True)
        fv.addWidget(self.filter_flag)
        fv.addWidget(self.filter_unflagged)
        fv.addWidget(self.filter_synthesized)
        lv.addWidget(filter_gb)

        self.lbl_count = QLabel(tr('Number of points selected: 0'))
        lv.addWidget(self.lbl_count)
        self.show_fit = QCheckBox(tr('Show line of best fit'))
        lv.addWidget(self.show_fit)
        lv.addStretch(1)

        self.plot = PlotCanvas('flag_scatter')
        self.plot.setMinimumSize(620, 520)
        root.addWidget(left)
        root.addWidget(self.plot, 1)

        self.x_combo.currentIndexChanged.connect(self._refresh)
        self.y_combo.currentIndexChanged.connect(self._refresh)
        self.color_by_flag.stateChanged.connect(self._refresh)
        self.show_fit.stateChanged.connect(self._refresh)

        bb = QHBoxLayout()
        bb.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        bb.addWidget(cancel)
        bb.addWidget(ok)
        lv.addLayout(bb)

        self._refresh()

    def _refresh(self):
        ds = self._ds
        x_col = self.x_combo.currentData()
        y_col = self.y_combo.currentData()
        if not x_col or not y_col:
            return
        x = _to_num(ds.df[x_col]).dropna()
        y = _to_num(ds.df[y_col]).dropna()
        idx = x.index.intersection(y.index)
        x, y = x.loc[idx], y.loc[idx]
        self.plot.plot_scatter(x.values, y.values,
                               xlabel=f'{_col_disp(ds, x_col)} ({ds.channels.get(x_col, type("c", (), {"units":""})()).units})',
                               ylabel=f'{_col_disp(ds, y_col)} ({ds.channels.get(y_col, type("c", (), {"units":""})()).units})',
                               regression=self.show_fit.isChecked())
        self.plot.set_title(f'{_col_disp(ds, x_col)} vs. {_col_disp(ds, y_col)}')
        self.lbl_count.setText(f'Number of points selected: 0')

    def _apply(self):
        flag = self.flag_combo.currentText()
        # 简化：以当前散点范围筛选为演示；真实框选需鼠标交互
        mask = self._ds.flags if self._ds.flags.any() else pd.Series(False, index=self._ds.df.index)
        self._ds.apply_flag(flag, mask)
        self._info = f'Applied {flag}'
        self._refresh()

    def _remove(self):
        flag = self.flag_combo.currentText()
        mask = self._ds.flag_masks.get(flag, pd.Series(False, index=self._ds.df.index))
        self._ds.remove_flag(flag, mask)
        self._info = f'Removed {flag}'
        self._refresh()

    def _remove_all(self):
        flag = self.flag_combo.currentText()
        self._ds.remove_flag(flag)
        self._info = f'Removed all {flag}'
        self._refresh()


# ------------------------------------------------------------------ 3. Flag With Rules
@dataclass
class FlagRule:
    """规则定义。"""
    name: str
    flag_name: str
    criteria: str
    columns: str
    favorite: bool = False


class FlagWithRulesDialog(QDialog):
    """按规则标记：规则表 + 可勾选 + Test/Execute。"""

    DEFAULT_RULES = [
        FlagRule('Direction <>', 'Invalid',
                 "any mean WD column outside range 0 to 360", "relevant mean WD column"),
        FlagRule('Direction 6h', 'Invalid',
                 "any mean WD column changes less than 1 deg over 6h", "relevant mean WD column"),
        FlagRule('Direction SD 3h', 'Icing',
                 "any WD SD column < 0.1 and any mean WD column changes < 5", "relevant mean WD column and WD SD"),
        FlagRule('Humidity <>', 'Invalid',
                 "relative humidity column outside range 0% to 100%", "relative humidity column"),
        FlagRule('Icing', 'Icing',
                 "any mean WS column < 0.2 m/s and any mean WD column changes > 10", "relevant mean WS column and WD columns"),
        FlagRule('Pressure <>', 'Invalid',
                 "any pressure column outside range 60 to 110 kPa", "relevant pressure column"),
        FlagRule('Pressure 3h', 'Invalid',
                 "any pressure column changes more than 1 kPa over 3h", "relevant pressure column"),
        FlagRule('Q<80', 'Low quality',
                 "any quality column < 80", "all columns associated with relevant quality column"),
        FlagRule('Temperature 1h', 'Invalid',
                 "any temperature column changes more than 5 C over 1h", "relevant temperature column"),
        FlagRule('Temperature <>', 'Invalid',
                 "any temperature column outside range -40 to 50 C", "all temperature columns"),
        FlagRule('Wind Speed <>', 'Invalid',
                 "any mean WS column outside range 0 to 40 m/s", "relevant mean WS column"),
        FlagRule('Wind Speed 1h', 'Invalid',
                 "any mean WS column changes more than 6 m/s over 1h", "relevant mean WS column"),
        FlagRule('Wind Speed 6h', 'Invalid',
                 "any mean WS column changes less than 0.1 m/s over 6h", "relevant mean WS column"),
        FlagRule('Wind Speed SD', 'Invalid',
                 "any WS SD column outside range 0 to 6 m/s", "relevant mean WS column and WS SD"),
    ]

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Flag With Rules'))
        self.resize(960, 620)
        self._ds = ds
        self._info = ''

        root = QVBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        # 左侧规则定义表
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.addWidget(QLabel(tr('Define flag rules')))
        self.rule_table = QTableWidget(0, 4)
        self.rule_table.setHorizontalHeaderLabels(
            ['Name', 'Flag', 'Search Criteria', 'Columns To Flag'])
        self.rule_table.horizontalHeader().setStretchLastSection(True)
        lv.addWidget(self.rule_table)
        btn_lay = QHBoxLayout()
        self.btn_edit = QPushButton(tr('Edit...'))
        self.btn_add = QPushButton(tr('Add...'))
        self.btn_del = QPushButton(tr('Delete...'))
        self.btn_fav = QPushButton(tr('Add to Favorites'))
        self.btn_import = QPushButton(tr('Import from Favorites...'))
        btn_lay.addWidget(self.btn_edit)
        btn_lay.addWidget(self.btn_add)
        btn_lay.addWidget(self.btn_del)
        btn_lay.addStretch(1)
        btn_lay.addWidget(self.btn_fav)
        btn_lay.addWidget(self.btn_import)
        lv.addLayout(btn_lay)
        split.addWidget(left)

        # 右侧下方面板
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        rv.addWidget(QLabel(tr('Rules applicable to this data set')))
        self.applicable = _CheckList()
        self.applicable.add_items([r.name for r in self.DEFAULT_RULES])
        rv.addWidget(self.applicable)

        rv.addWidget(QLabel(tr('Results')))
        self.res_table = QTableWidget(0, 3)
        self.res_table.setHorizontalHeaderLabels(
            ['Flag Rule', 'Time Steps Caught', 'Data Points Newly Flagged'])
        self.res_table.horizontalHeader().setStretchLastSection(True)
        rv.addWidget(self.res_table)
        split.addWidget(right)
        split.setSizes([560, 400])

        bb = QHBoxLayout()
        bb.addWidget(QLabel(tr('Help')))
        bb.addStretch(1)
        self.btn_test = QPushButton(tr('Test Flag Rules'))
        self.btn_exec = QPushButton(tr('Execute Flag Rules'))
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        self.btn_test.clicked.connect(self._test_rules)
        self.btn_exec.clicked.connect(self._execute_rules)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        bb.addWidget(self.btn_test)
        bb.addWidget(self.btn_exec)
        bb.addWidget(cancel)
        bb.addWidget(ok)
        root.addLayout(bb)

        self._load_rules()

    def _load_rules(self):
        rules = self.DEFAULT_RULES
        self.rule_table.setRowCount(len(rules))
        for r, rule in enumerate(rules):
            self.rule_table.setItem(r, 0, QTableWidgetItem(rule.name))
            self.rule_table.setItem(r, 1, QTableWidgetItem(rule.flag_name))
            self.rule_table.setItem(r, 2, QTableWidgetItem(rule.criteria))
            self.rule_table.setItem(r, 3, QTableWidgetItem(rule.columns))

    def _rule_mask(self, rule: FlagRule) -> pd.Series:
        ds = self._ds
        idx = ds.df.index
        mask = pd.Series(False, index=idx)
        if 'mean WD column outside range 0 to 360' in rule.criteria:
            for c in _dir_cols(ds):
                v = _to_num(ds.df[c])
                mask = mask | ((v < 0) | (v > 360))
        elif 'temperature column outside range' in rule.criteria:
            for c in [cc for cc in ds.channels if ds.channels[cc].kind == 'temp']:
                v = _to_num(ds.df[c])
                mask = mask | ((v < -40) | (v > 50))
        elif 'pressure column outside range' in rule.criteria:
            for c in [cc for cc in ds.channels if ds.channels[cc].kind == 'pres']:
                v = _to_num(ds.df[c])
                mask = mask | ((v < 60) | (v > 110))
        elif 'relative humidity column outside range' in rule.criteria:
            for c in [cc for cc in ds.channels if ds.channels[cc].kind == 'rh']:
                v = _to_num(ds.df[c])
                mask = mask | ((v < 0) | (v > 100))
        elif 'any mean WS column outside range' in rule.criteria:
            for c in _speed_cols(ds):
                v = _to_num(ds.df[c])
                mask = mask | ((v < 0) | (v > 40))
        elif 'quality column < 80' in rule.criteria:
            pass
        elif 'WS SD column outside range' in rule.criteria:
            for c in [cc for cc in ds.channels if ds.channels[cc].kind == 'speed_sd']:
                v = _to_num(ds.df[c])
                mask = mask | ((v < 0) | (v > 6))
        return mask

    def _test_rules(self):
        ds = self._ds
        checked = self.applicable.checked()
        rows = []
        for rule in self.DEFAULT_RULES:
            if rule.name not in checked:
                continue
            mask = self._rule_mask(rule)
            rows.append((rule.name, int(mask.sum()), int(mask.sum())))
        self.res_table.setRowCount(len(rows))
        for r, (name, caught, newly) in enumerate(rows):
            self.res_table.setItem(r, 0, QTableWidgetItem(name))
            self.res_table.setItem(r, 1, QTableWidgetItem(str(caught)))
            self.res_table.setItem(r, 2, QTableWidgetItem(str(newly)))

    def _execute_rules(self):
        checked = self.applicable.checked()
        total = 0
        for rule in self.DEFAULT_RULES:
            if rule.name not in checked:
                continue
            mask = self._rule_mask(rule)
            self._ds.apply_flag(rule.flag_name, mask)
            total += int(mask.sum())
        self._info = f'Executed rules, flagged {total} time steps'
        self._test_rules()


# ------------------------------------------------------------------ 4. Flag Tower Shading
class FlagTowerShadowDialog(QDialog):
    """塔影标记：风速仪对 + 扇区 + 中位数比/散点比双图。"""

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Flag Tower Shading'))
        self.resize(1100, 720)
        self._ds = ds
        self._info = ''

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr('Wind speed sensor pairs:')))
        self.pair_combo = QComboBox()
        speeds = _speed_cols(ds)
        for i in range(0, len(speeds) - 1, 2):
            self.pair_combo.addItem(f'{_col_disp(ds, speeds[i])} | {_col_disp(ds, speeds[i+1])}')
        top.addWidget(self.pair_combo)
        top.addSpacing(20)
        top.addWidget(QLabel(tr('Flag to apply:')))
        self.flag_combo = QComboBox()
        for n in ds.flag_registry:
            self.flag_combo.addItem(n)
        top.addWidget(self.flag_combo)
        top.addStretch(1)
        root.addLayout(top)

        form = QFormLayout()
        self.dir_combo = QComboBox()
        for c in _dir_cols(ds):
            self.dir_combo.addItem(_col_disp(ds, c), c)
        self.gen_rules = QCheckBox(tr('Generate flag rules for this sensor pair'))
        self.gen_rules.setChecked(True)
        form.addRow('Direction sensor to use in flag rules:', self.dir_combo)
        form.addRow(self.gen_rules)
        root.addLayout(form)

        self.plot_cart = QRadioButton(tr('Cartesian'))
        self.plot_polar = QRadioButton(tr('Polar'))
        self.plot_cart.setChecked(True)
        hh = QHBoxLayout()
        hh.addWidget(QLabel(tr('Plot:')))
        hh.addWidget(self.plot_cart)
        hh.addWidget(self.plot_polar)
        hh.addStretch(1)
        root.addLayout(hh)

        # 扇区设置
        sec = QHBoxLayout()
        sec.addWidget(QLabel(tr('Sector 1 center:')))
        self.sec1_c = QDoubleSpinBox(); self.sec1_c.setRange(0, 360); self.sec1_c.setValue(65)
        sec.addWidget(self.sec1_c)
        sec.addWidget(QLabel(tr('width:')))
        self.sec1_w = QDoubleSpinBox(); self.sec1_w.setRange(0, 360); self.sec1_w.setValue(30)
        sec.addWidget(self.sec1_w)
        sec.addWidget(QLabel(tr('apply to:')))
        self.sec1_t = QComboBox()
        for c in speeds:
            self.sec1_t.addItem(_col_disp(ds, c), c)
        sec.addWidget(self.sec1_t)
        sec.addSpacing(20)
        sec.addWidget(QLabel(tr('Sector 2 center:')))
        self.sec2_c = QDoubleSpinBox(); self.sec2_c.setRange(0, 360); self.sec2_c.setValue(165)
        sec.addWidget(self.sec2_c)
        sec.addWidget(QLabel(tr('width:')))
        self.sec2_w = QDoubleSpinBox(); self.sec2_w.setRange(0, 360); self.sec2_w.setValue(30)
        sec.addWidget(self.sec2_w)
        sec.addWidget(QLabel(tr('apply to:')))
        self.sec2_t = QComboBox()
        for c in speeds:
            self.sec2_t.addItem(_col_disp(ds, c), c)
        sec.addWidget(self.sec2_t)
        sec.addStretch(1)
        root.addLayout(sec)

        self.plot_median = PlotCanvas('tower_median')
        self.plot_median.setMinimumHeight(220)
        root.addWidget(self.plot_median)
        self.plot_ratio = PlotCanvas('tower_ratio')
        self.plot_ratio.setMinimumHeight(220)
        root.addWidget(self.plot_ratio)

        self.rule_text = QLabel(tr('Generated flag rules will appear here.'))
        self.rule_text.setWordWrap(True)
        root.addWidget(self.rule_text)

        bb = QHBoxLayout()
        bb.addWidget(QLabel(tr('Help')))
        bb.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('Execute Flag Rules'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._execute)
        bb.addWidget(cancel)
        bb.addWidget(ok)
        root.addLayout(bb)

        self.pair_combo.currentIndexChanged.connect(self._refresh)
        self.sec1_c.valueChanged.connect(self._refresh)
        self.sec1_w.valueChanged.connect(self._refresh)
        self.sec2_c.valueChanged.connect(self._refresh)
        self.sec2_w.valueChanged.connect(self._refresh)
        self._refresh()

    def _pair_cols(self):
        txt = self.pair_combo.currentText()
        if '|' not in txt:
            return None, None
        a, b = txt.split('|', 1)
        return _disp_col(self._ds, a.strip()), _disp_col(self._ds, b.strip())

    def _sector_mask(self, c, w, dir_col):
        ds = self._ds
        d = _to_num(ds.df[dir_col])
        half = w / 2
        if c - half < 0:
            return ((d >= 0) & (d <= c + half)) | ((d >= 360 + (c - half)) & (d <= 360))
        if c + half > 360:
            return ((d >= c - half) & (d <= 360)) | ((d >= 0) & (d <= (c + half) - 360))
        return (d >= c - half) & (d <= c + half)

    def _refresh(self):
        ds = self._ds
        c1, c2 = self._pair_cols()
        if not c1 or not c2 or c1 not in ds.df.columns or c2 not in ds.df.columns:
            return
        dir_col = self.dir_combo.currentData()
        s1 = _to_num(ds.df[c1]); s2 = _to_num(ds.df[c2])
        valid = s1.notna() & s2.notna()
        ratio = (s1 / s2).where(valid)
        # 中位数比按风向 30 度 bin
        if dir_col and dir_col in ds.df.columns:
            d = _to_num(ds.df[dir_col]).where(valid)
            bins = np.arange(0, 361, 30)
            centers = 0.5 * (bins[:-1] + bins[1:])
            medians = []
            for lo, hi in zip(bins[:-1], bins[1:]):
                m = (d >= lo) & (d < hi)
                medians.append(float(ratio[m].median()) if m.any() else np.nan)
            self.plot_median.plot_line(centers, medians, xlabel='Sector Midpoint (deg)', ylabel='Median Ratio')
            self.plot_median.set_title(f'Median Ratio of {_col_disp(ds, c1)} to {_col_disp(ds, c2)}')
            self.plot_ratio.plot_scatter(d.values, ratio.values,
                                         xlabel='Direction (deg)', ylabel='Ratio')
            self.plot_ratio.set_title(f'Ratio of {_col_disp(ds, c1)} to {_col_disp(ds, c2)}')
        lines = []
        flag = self.flag_combo.currentText()
        dir_disp = _col_disp(ds, dir_col) if dir_col else ''
        for c, w, t in [(self.sec1_c.value(), self.sec1_w.value(), self.sec1_t.currentData()),
                        (self.sec2_c.value(), self.sec2_w.value(), self.sec2_t.currentData())]:
            lines.append(f"Apply '{flag}' to {_col_disp(ds, t)} where {dir_disp} is within range {c-w/2:.0f} to {c+w/2:.0f}")
        self.rule_text.setText('\n'.join(lines))

    def _execute(self):
        ds = self._ds
        dir_col = self.dir_combo.currentData()
        if not dir_col:
            return
        flag = self.flag_combo.currentText()
        total = 0
        for c, w, t in [(self.sec1_c.value(), self.sec1_w.value(), self.sec1_t.currentData()),
                        (self.sec2_c.value(), self.sec2_w.value(), self.sec2_t.currentData())]:
            mask = self._sector_mask(c, w, dir_col)
            ds.apply_flag(flag, mask)
            total += int(mask.sum())
        self._info = f'Applied {flag} to {total} time steps'
        self.accept()


# ------------------------------------------------------------------ 5. Inspect and Remove Flags
class InspectFlagsDialog(QDialog):
    """检查并移除标记：筛选 + 通道 + 时序/统计 + 取消标记。"""

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Inspect and Remove Flags'))
        self.resize(1100, 720)
        self._ds = ds
        self._info = ''

        root = QHBoxLayout(self)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)

        lv.addWidget(QLabel(tr('Filter criteria:')))
        self.include_hidden = QCheckBox(tr('Include hidden columns'))
        self.show_segments = QCheckBox(tr('Show list of segments'))
        lv.addWidget(self.include_hidden)
        lv.addWidget(self.show_segments)

        self.flag_list = _CheckList('Flag types:')
        self.flag_list.add_items(list(ds.flag_registry.keys()) + ['Synthesized'])
        lv.addWidget(self.flag_list)

        self.cols = _CheckList('Columns:')
        self.cols.add_items([_col_disp(ds, c) for c in ds.channels.keys()])
        lv.addWidget(self.cols)

        lv.addWidget(QLabel(tr('Display:')))
        self.disp_ts = QRadioButton(tr('Time series graph')); self.disp_ts.setChecked(True)
        self.disp_overall = QRadioButton(tr('Overall flag statistics'))
        self.disp_year = QRadioButton(tr('Flag statistics by year'))
        self.disp_month = QRadioButton(tr('Flag statistics by month'))
        bg = QButtonGroup(self)
        for rb in (self.disp_ts, self.disp_overall, self.disp_year, self.disp_month):
            bg.addButton(rb)
            lv.addWidget(rb)

        self.lbl_sel = QLabel(tr('You have selected 0 flagged segments'))
        lv.addWidget(self.lbl_sel)
        self.btn_unflag = QPushButton(tr('Unflag These Segments'))
        self.btn_unflag.clicked.connect(self._unflag)
        lv.addWidget(self.btn_unflag)
        lv.addStretch(1)

        self.plot = PlotCanvas('inspect_flags')
        self.plot.setMinimumSize(650, 520)
        root.addWidget(left)
        root.addWidget(self.plot, 1)

        bb = QHBoxLayout()
        bb.addWidget(QLabel(tr('Help')))
        bb.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        bb.addWidget(cancel)
        bb.addWidget(ok)
        lv.addLayout(bb)

        self.disp_ts.toggled.connect(self._refresh)
        self.disp_overall.toggled.connect(self._refresh)
        self.disp_year.toggled.connect(self._refresh)
        self.disp_month.toggled.connect(self._refresh)
        self.flag_list.list.itemChanged.connect(self._refresh)
        self.cols.list.itemChanged.connect(self._refresh)
        self._refresh()

    def _selected_mask(self) -> pd.Series:
        ds = self._ds
        flags = self.flag_list.checked()
        mask = pd.Series(False, index=ds.df.index)
        for f in flags:
            if f == 'Synthesized':
                for c in ds.channels:
                    if 'Synthesized' in c or ds.channels[c].kind == 'synthetic':
                        pass
            elif f in ds.flag_masks:
                mask = mask | ds.flag_masks[f]
        return mask

    def _refresh(self):
        ds = self._ds
        mask = self._selected_mask()
        n = int(mask.sum())
        self.lbl_sel.setText(f'You have selected {n} flagged segments')
        cols = [_disp_col(ds, d) for d in self.cols.checked()]
        if not cols:
            cols = _numeric_cols(ds)[:3]
        if self.disp_ts.isChecked():
            series = []
            for c in cols:
                if c in ds.df.columns:
                    s = _to_num(ds.df[c])
                    series.append((_col_disp(ds, c), ds.df.index, s))
            self.plot.plot_lines(series, xlabel='Time', ylabel='Value')
        elif self.disp_overall.isChecked():
            counts = {f: int(s.sum()) for f, s in ds.flag_masks.items()}
            self.plot.plot_bar(list(counts.keys()), list(counts.values()),
                               xlabel='Flag', ylabel='Count')
        elif self.disp_year.isChecked():
            years = ds.df.index.year
            data = {y: int(mask[years == y].sum()) for y in sorted(years.unique())}
            self.plot.plot_bar([str(y) for y in data.keys()], list(data.values()),
                               xlabel='Year', ylabel='Flagged')
        else:
            months = ds.df.index.to_period('M')
            data = {str(m): int(mask[months == m].sum()) for m in months.unique()}
            self.plot.plot_bar(list(data.keys()), list(data.values()),
                               xlabel='Month', ylabel='Flagged')

    def _unflag(self):
        mask = self._selected_mask()
        for f in self.flag_list.checked():
            if f in self._ds.flag_masks:
                self._ds.remove_flag(f, mask)
        self._info = f'Unflagged {int(mask.sum())} time steps'
        self._refresh()


# ------------------------------------------------------------------ 6. Define Flags
class DefineFlagsDialog(QDialog):
    """定义标记类型。"""

    def __init__(self, ds: Dataset | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Define Flags'))
        self.resize(720, 480)
        self._ds = ds

        root = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ['Name', 'Color', 'Include In Calculations', 'Show In Graphs'])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)

        btn_lay = QHBoxLayout()
        self.btn_edit = QPushButton(tr('Edit...'))
        self.btn_add = QPushButton(tr('Add...'))
        self.btn_del = QPushButton(tr('Delete...'))
        self.btn_fav = QPushButton(tr('Add to Favorites'))
        self.btn_import = QPushButton(tr('Import from Favorites...'))
        btn_lay.addWidget(self.btn_edit)
        btn_lay.addWidget(self.btn_add)
        btn_lay.addWidget(self.btn_del)
        btn_lay.addStretch(1)
        btn_lay.addWidget(self.btn_fav)
        btn_lay.addWidget(self.btn_import)
        root.addLayout(btn_lay)

        root.addWidget(QLabel(tr('Special purpose flags')))
        grid = QGridLayout()
        self.sp_tower = QComboBox()
        self.sp_invalid = QComboBox()
        self.sp_synth = QComboBox()
        for cb in (self.sp_tower, self.sp_invalid, self.sp_synth):
            cb.setEditable(False)
        grid.addWidget(QLabel(tr('Tower shading')), 0, 0)
        grid.addWidget(self.sp_tower, 0, 1)
        grid.addWidget(QLabel(tr('Invalid data')), 1, 0)
        grid.addWidget(self.sp_invalid, 1, 1)
        grid.addWidget(QLabel(tr('Synthetic data')), 2, 0)
        grid.addWidget(self.sp_synth, 2, 1)
        root.addLayout(grid)

        bb = QHBoxLayout()
        bb.addWidget(QLabel(tr('Help')))
        bb.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        bb.addWidget(cancel)
        bb.addWidget(ok)
        root.addLayout(bb)

        self._load()

    def _load(self):
        reg = self._ds.flag_registry if self._ds else {}
        self.table.setRowCount(len(reg))
        for r, f in enumerate(reg.values()):
            self.table.setItem(r, 0, QTableWidgetItem(f.name))
            self.table.setCellWidget(r, 1, _ColorBlock(f.color))
            inc = QTableWidgetItem('Yes' if f.include_in_calcs else 'No')
            inc.setFlags(inc.flags() | Qt.ItemIsUserCheckable)
            inc.setCheckState(Qt.Checked if f.include_in_calcs else Qt.Unchecked)
            self.table.setItem(r, 2, inc)
            show = QTableWidgetItem('Yes' if f.show_in_graphs else 'No')
            show.setFlags(show.flags() | Qt.ItemIsUserCheckable)
            show.setCheckState(Qt.Checked if f.show_in_graphs else Qt.Unchecked)
            self.table.setItem(r, 3, show)
        self._reload_special_combos()

    def _reload_special_combos(self):
        names = [self.table.item(r, 0).text() for r in range(self.table.rowCount())]
        for cb, default in ((self.sp_tower, 'Tower shading'),
                            (self.sp_invalid, 'Invalid'),
                            (self.sp_synth, 'Synthesized')):
            cb.clear()
            cb.addItems(names)
            cb.setCurrentText(default if default in names else (names[0] if names else ''))

    def _on_ok(self):
        if self._ds is None:
            self.accept()
            return
        reg = {}
        for r in range(self.table.rowCount()):
            name = self.table.item(r, 0).text()
            color = '#ff6b35'
            cw = self.table.cellWidget(r, 1)
            if cw:
                # 从样式表解析颜色太繁琐，保留原值
                color = getattr(cw, '_color', '#ff6b35')
            inc = self.table.item(r, 2).checkState() == Qt.Checked
            show = self.table.item(r, 3).checkState() == Qt.Checked
            reg[name] = Flag(name, color, inc, show)
        self._ds.flag_registry = reg
        self._ds._ensure_default_flags()
        self.accept()


# ------------------------------------------------------------------ 7. Define Favorite Flags
class DefineFavoriteFlagsDialog(DefineFlagsDialog):
    """定义常用标记（界面与 Define Flags 一致，但 favorite=True）。"""

    def __init__(self, ds: Dataset | None = None, parent=None):
        super().__init__(ds, parent)
        self.setWindowTitle(tr('Define Favorite Flags'))


# ------------------------------------------------------------------ 8. View Favorite Flag Rules
class ViewFavoriteFlagRulesDialog(QDialog):
    """查看常用标记规则表。"""

    def __init__(self, ds: Dataset | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('View Favorite Flag Rules'))
        self.resize(900, 520)

        root = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ['Name', 'Flag', 'Search Criteria', 'Columns To Flag'])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)

        rules = FlagWithRulesDialog.DEFAULT_RULES
        fav = [r for r in rules if r.favorite] or rules
        self.table.setRowCount(len(fav))
        for r, rule in enumerate(fav):
            self.table.setItem(r, 0, QTableWidgetItem(rule.name))
            self.table.setItem(r, 1, QTableWidgetItem(rule.flag_name))
            self.table.setItem(r, 2, QTableWidgetItem(rule.criteria))
            self.table.setItem(r, 3, QTableWidgetItem(rule.columns))

        bb = QHBoxLayout()
        bb.addWidget(QLabel(tr('Help')))
        bb.addStretch(1)
        self.btn_del = QPushButton(tr('Delete...'))
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        self.btn_del.clicked.connect(self._delete)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        bb.addWidget(self.btn_del)
        bb.addWidget(cancel)
        bb.addWidget(ok)
        root.addLayout(bb)

    def _delete(self):
        rows = sorted({r.row() for r in self.table.selectedItems()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
