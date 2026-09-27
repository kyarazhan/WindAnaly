"""Revise 菜单 7 个核心对话框（WindAnaly）。

按 Windographer 4.x 对话框布局重构：
1) Apply Scale and Offset: 左侧通道勾选 + 右侧时间范围/Scale/Offset + 公式
2) Apply Time Shift: Current/New start time 双行
3) Delete Data: 左侧通道勾选 + 右侧删除方式/时间范围/Flag 下拉 + Flag 选择
4) Fill Gaps: 左侧方法/范围 + 中间通道勾选 + 右侧统计表 + 底部时间线覆盖热力图
5) Fix Quantization: Data column/Display/Modify 选项 + 左右直方图 + 信息提示
6) Combine Anemometers: 双通道列表 + 方法 + Hide original
7) Vertical Extrapolation: Tab + Synthesize 勾选 + 高度表 + Power law exponent 下拉 + 源列表 + 范围限制 + Flag 下拉

全部对接 Dataset.df，确认后就地修改并写回 project；取消不落盘。
"""

from __future__ import annotations

import copy
import math

import numpy as np
import pandas as pd
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateTimeEdit,
    QDialog, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QRadioButton, QSpinBox, QSplitter, QStackedWidget,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.dataset import Channel, Dataset
from core.i18n import language, tr
from core.io_import import build_canon_name
from ui.modules.analysis_tabs import actual_name, display_name
from ui.modules.plot import PlotCanvas


# ------------------------------------------------------------------ 工具函数
_NUMERIC_KINDS = {'speed', 'dir', 'temp', 'pres', 'rh', 'ti',
                  'synthetic', 'speed_sd'}


def _all_cols(ds: Dataset) -> list[str]:
    return list(ds.channels.keys())


def _numeric_cols(ds: Dataset) -> list[str]:
    return [c.name for c in ds.channels.values() if c.kind in _NUMERIC_KINDS]


def _to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors='coerce')


def _col_from_display(ds: Dataset, disp: str) -> str:
    for c in ds.channels:
        if display_name(c) == disp:
            return c
    return disp


def _interp(series: pd.Series, method: str) -> pd.Series:
    s = _to_num(series)
    if method == 'linear':
        s = s.interpolate(method='linear', limit_direction='both')
    elif method == 'time':
        s = s.interpolate(method='time', limit_direction='both')
    elif method == 'ffill':
        s = s.ffill().bfill()
    elif method == 'bfill':
        s = s.bfill().ffill()
    elif method == 'spline':
        s = s.interpolate(method='spline', order=2, limit_direction='both')
    elif method == 'mean':
        s = s.fillna(s.mean())
    return s


# ------------------------------------------------------------------ 可复用组件
class _CheckList(QWidget):
    """带「全选」复选框 + 多选列表的可复用组件。"""

    def __init__(self, title: str = '', parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.sel_all = QCheckBox(tr('全选'))
        self.sel_all.stateChanged.connect(self._on_all)
        top.addWidget(self.sel_all)
        top.addStretch(1)
        if title:
            top.addWidget(QLabel(title))
            top.addStretch(1)
        lay.addLayout(top)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.MultiSelection)
        lay.addWidget(self.list, 1)

    def add_items(self, names: list[str]):
        for n in names:
            it = QListWidgetItem(display_name(n))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, n)
            self.list.addItem(it)

    def _on_all(self, state):
        chk = Qt.Checked if state == Qt.Checked.value else Qt.Unchecked
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(chk)

    def checked(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole) or actual_name(it.text()))
        return out

    def set_checked(self, names: set[str]):
        name_set = set(names)
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in name_set
                             else Qt.Unchecked)


class _DateTimeRow(QWidget):
    """标签 + 日期 + 时间的组合行。"""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(label))
        self.date = QDateTimeEdit()
        self.date.setDisplayFormat('yyyy/M/d')
        self.date.setCalendarPopup(True)
        self.time = QDateTimeEdit()
        self.time.setDisplayFormat('HH:mm')
        lay.addWidget(self.date)
        lay.addWidget(self.time)
        lay.addStretch(1)

    def set_dt(self, ts: pd.Timestamp):
        self.date.setDateTime(ts.to_pydatetime())
        self.time.setDateTime(ts.to_pydatetime())

    def get_dt(self) -> pd.Timestamp:
        d = self.date.dateTime().toPython()
        t = self.time.dateTime().toPython()
        return pd.Timestamp(d.replace(hour=t.hour, minute=t.minute,
                                      second=t.second))


def _ok_cancel_help(lay, ok_slot, help_text: str = ''):
    """在布局底部添加 Help + Cancel + OK。"""
    btns = QHBoxLayout()
    btns.addStretch(1)
    help_btn = QPushButton(tr('Help'))
    if help_text:
        help_btn.clicked.connect(
            lambda: QMessageBox.information(None, 'Help', help_text))
    cancel = QPushButton(tr('Cancel'))
    ok = QPushButton('OK')
    ok.setObjectName('primaryBtn')
    cancel.clicked.connect(lambda: None)
    ok.clicked.connect(ok_slot)
    btns.addWidget(help_btn)
    btns.addWidget(cancel)
    btns.addWidget(ok)
    lay.addLayout(btns)
    return help_btn, cancel, ok


# ------------------------------------------------------------------ 1. 比例与偏移
class ApplyScaleOffsetDialog(QDialog):
    HELP = ('Apply a linear transform: NewValue = Offset + (OldValue * Scale). '
            'Select one or more data columns, choose whether to modify all '
            'time steps or only a time segment, then click OK.')

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('应用比例与偏移'))
        self.resize(680, 460)
        self._ds = ds

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        main = QHBoxLayout()
        # 左侧：通道列表
        self.cols = _CheckList('选择要修改的数据列')
        self.cols.add_items(_all_cols(ds))
        main.addWidget(self.cols, 1)

        # 右侧：时间与参数
        right = QVBoxLayout()
        grp_range = QGroupBox(tr('修改范围'))
        vg = QVBoxLayout(grp_range)
        self.rb_all = QRadioButton(tr('修改全部时间步'))
        self.rb_seg = QRadioButton(tr('修改指定时间段'))
        self.rb_all.setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self.rb_all)
        bg.addButton(self.rb_seg)
        vg.addWidget(self.rb_all)
        vg.addWidget(self.rb_seg)
        self.seg0 = _DateTimeRow('Start time')
        self.seg1 = _DateTimeRow('End time')
        vg.addWidget(self.seg0)
        vg.addWidget(self.seg1)
        self._set_seg_enabled(False)
        self.rb_all.toggled.connect(lambda c: self._set_seg_enabled(not c))
        self.rb_seg.toggled.connect(lambda c: self._set_seg_enabled(c))
        right.addWidget(grp_range)

        grp_val = QGroupBox(tr('数值变换'))
        fg = QFormLayout(grp_val)
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-1e9, 1e9)
        self.offset.setDecimals(4)
        self.offset.setValue(0.0)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(-1e6, 1e6)
        self.scale.setDecimals(4)
        self.scale.setValue(1.0)
        fg.addRow('Offset:', self.offset)
        fg.addRow('Scale:', self.scale)
        self.formula = QLabel('NewValue = Offset + (OldValue * Scale)')
        self.formula.setStyleSheet('color:#5a6573; font-size:11px;')
        fg.addRow(self.formula)
        right.addWidget(grp_val)
        right.addStretch(1)

        main.addLayout(right, 1)
        lay.addLayout(main, 1)

        # 按钮
        btns = QHBoxLayout()
        btns.addStretch(1)
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, 'Help', self.HELP))
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(help_btn)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        # 默认时间范围
        if not ds.df.empty:
            t0 = pd.Timestamp(ds.df.index[0])
            t1 = pd.Timestamp(ds.df.index[-1])
            self.seg0.set_dt(t0)
            self.seg1.set_dt(t1)

    def _set_seg_enabled(self, on: bool):
        self.seg0.setEnabled(on)
        self.seg1.setEnabled(on)

    def _mask(self) -> pd.Series:
        if self.rb_all.isChecked() or self._ds.df.empty:
            return pd.Series(True, index=self._ds.df.index)
        a = self.seg0.get_dt()
        b = self.seg1.get_dt()
        return (self._ds.df.index >= a) & (self._ds.df.index <= b)

    def _on_ok(self):
        cols = self.cols.checked()
        # 过滤非数值列
        numeric = set(_numeric_cols(self._ds))
        cols = [c for c in cols if c in numeric]
        if not cols:
            QMessageBox.warning(self, tr('无通道'),
                                tr('请至少勾选一个数值通道'))
            return
        scale = self.scale.value()
        offset = self.offset.value()
        mask = self._mask()
        for col in cols:
            if col not in self._ds.df.columns:
                continue
            vals = _to_num(self._ds.df.loc[mask, col])
            self._ds.df.loc[mask, col] = offset + vals * scale
        self._info = (f'已对 {len(cols)} 个通道应用 '
                      f'Offset={offset}, Scale={scale}')
        self.accept()


# ------------------------------------------------------------------ 2. 时移
class ApplyTimeShiftDialog(QDialog):
    """Apply Time Shift.

    What would you like to do? / Shift columns / Time interval / Steps.
    """

    def __init__(self, ds, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Apply Time Shift'))
        self.resize(640, 520)
        self._ds = ds
        self._info = ''

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        left = QVBoxLayout()
        left.addWidget(QLabel(tr('What would you like to do?')))
        self.rb_all = QRadioButton(tr('Shift the entire data set in time'))
        self.rb_seg = QRadioButton(tr('Shift a particular data segment in time'))
        self.rb_all.setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self.rb_all)
        bg.addButton(self.rb_seg)
        left.addWidget(self.rb_all)
        left.addWidget(self.rb_seg)

        left.addWidget(QLabel(tr('Shift the following data columns...')))
        self.chk_select_all = QCheckBox(tr('Select all'))
        self.chk_select_all.setChecked(True)
        self.chk_select_all.stateChanged.connect(self._toggle_all)
        left.addWidget(self.chk_select_all)

        self.col_listw = QListWidget()
        self.col_listw.setSelectionMode(QAbstractItemView.NoSelection)
        for c in ds.df.columns:
            item = QListWidgetItem(display_name(c))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.col_listw.addItem(item)
        left.addWidget(self.col_listw, 1)
        root.addLayout(left, 0)

        right = QVBoxLayout()
        right.addWidget(QLabel(tr('in the following time interval...')))
        iv_gb = QGroupBox()
        iv_form = QFormLayout(iv_gb)
        iv_form.setSpacing(4)
        from PySide6.QtCore import QDateTime
        self.dt_start = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDisplayFormat('yyyy/M/d HH:mm')
        self.dt_end = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_end.setCalendarPopup(True)
        self.dt_end.setDisplayFormat('yyyy/M/d HH:mm')
        self.rb_all.toggled.connect(self._toggle_interval)
        self._toggle_interval(True)
        iv_form.addRow(tr('Start time'), self.dt_start)
        iv_form.addRow(tr('End time'), self.dt_end)
        right.addWidget(iv_gb)

        by_gb = QGroupBox()
        by_form = QFormLayout(by_gb)
        by_form.setSpacing(4)
        self.sp_steps = QSpinBox()
        self.sp_steps.setRange(-999999, 999999)
        by_form.addRow(tr('by'), self.sp_steps)
        by_form.addRow(QLabel(tr('time steps')))
        self.rb_fwd = QRadioButton(tr('forward in time'))
        self.rb_bwd = QRadioButton(tr('backward in time'))
        self.rb_fwd.setChecked(True)
        by_form.addRow(self.rb_fwd)
        by_form.addRow(self.rb_bwd)
        right.addWidget(by_gb)
        right.addStretch(1)
        root.addLayout(right, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, tr('Help'),
            tr('Shift the selected data columns in time by the specified '
               'number of time steps, forward or backward.')))
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('OK'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(help_btn)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

        self._init_time_range()

    def _toggle_interval(self, entire_mode):
        # 整体时移时无需指定时间区间
        self.dt_start.setEnabled(not entire_mode)
        self.dt_end.setEnabled(not entire_mode)

    def _toggle_all(self, state):
        checked = state == Qt.Checked
        for i in range(self.col_listw.count()):
            self.col_listw.item(i).setCheckState(
                Qt.Checked if checked else Qt.Unchecked)

    def _init_time_range(self):
        if self._ds.df.empty:
            return
        t0 = pd.Timestamp(self._ds.df.index[0])
        t1 = pd.Timestamp(self._ds.df.index[-1])
        from PySide6.QtCore import QDate, QDateTime, QTime

        def _qdt(ts):
            return QDateTime(QDate(ts.year, ts.month, ts.day),
                             QTime(ts.hour, ts.minute))

        self.dt_start.setDateTime(_qdt(t0))
        self.dt_end.setDateTime(_qdt(t1))

    def _selected_columns(self):
        cols = []
        for i in range(self.col_listw.count()):
            item = self.col_listw.item(i)
            if item.checkState() == Qt.Checked:
                cols.append(item.text())
        return cols

    def _on_ok(self):
        if self._ds.df.empty:
            self.reject()
            return
        steps = self.sp_steps.value()
        if steps == 0:
            QMessageBox.warning(self, tr('No shift'),
                                tr('Please enter a non-zero number of steps'))
            return
        cols = []
        for i in range(self.col_listw.count()):
            item = self.col_listw.item(i)
            if item.checkState() == Qt.Checked:
                cols.append(actual_name(item.text()))
        if not cols:
            QMessageBox.warning(self, tr('No columns'),
                                tr('Please select columns to shift'))
            return

        dt_min = 10.0
        try:
            diffs = np.diff(np.asarray(self._ds.df.index)
                            .astype('datetime64[s]').astype('int64')) / 60.0
            diffs = diffs[diffs > 0]
            if len(diffs):
                dt_min = float(np.median(diffs))
        except Exception:
            pass
        td = pd.Timedelta(minutes=steps * dt_min)

        df = self._ds.df
        if self.rb_all.isChecked():
            new_index = df.index + td
            df.index = new_index
            if len(self._ds.flags) == len(new_index):
                self._ds.flags.index = new_index
            for periods in self._ds.calibrations.values():
                for per in periods:
                    if per.get('start'):
                        per['start'] = str(pd.Timestamp(per['start']) + td)
                    if per.get('end'):
                        per['end'] = str(pd.Timestamp(per['end']) + td)
            self._info = f'{tr("Time shift")}: {td}'
        else:
            start = pd.Timestamp(self.dt_start.dateTime().toPython())
            end = pd.Timestamp(self.dt_end.dateTime().toPython())
            in_iv = (df.index >= start) & (df.index <= end)
            if not in_iv.any():
                QMessageBox.warning(self, tr('No data'),
                                    tr('No data in the selected time interval'))
                return
            n_shift = 0
            for col in cols:
                if col not in df.columns:
                    continue
                vals = df.loc[in_iv, col].copy()
                src_idx = df.index[in_iv]
                df.loc[in_iv, col] = np.nan
                for si, ni in zip(src_idx, src_idx + td):
                    if ni in df.index:
                        df.at[ni, col] = vals.loc[si]
                        n_shift += 1
            df.sort_index(inplace=True)
            self._info = f'{tr("Time shift")}: {len(cols)} cols, {n_shift} pts, {td}'
        self.accept()

    def result_info(self):
        return self._info


class DeleteDataDialog(QDialog):
    HELP = ('Delete selected columns entirely, or delete data points from '
            'selected columns within a date/time range and/or based on flags.')

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('删除数据'))
        self.resize(720, 520)
        self._ds = ds

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        main = QHBoxLayout()
        # 左侧通道列表
        self.cols = _CheckList('选择数据列：')
        self.cols.add_items(_all_cols(ds))
        main.addWidget(self.cols, 1)

        # 右侧选项
        right = QVBoxLayout()
        grp = QGroupBox(tr('操作'))
        gv = QVBoxLayout(grp)
        self.rb_del_cols = QRadioButton(tr('删除所选列'))
        self.rb_del_points = QRadioButton(tr('删除所选列中的数据点'))
        self.rb_del_cols.setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self.rb_del_cols)
        bg.addButton(self.rb_del_points)
        gv.addWidget(self.rb_del_cols)
        gv.addWidget(self.rb_del_points)
        right.addWidget(grp)

        # 时间范围
        self.tr_w = QWidget()
        tr = QFormLayout(self.tr_w)
        tr.setContentsMargins(0, 0, 0, 0)
        self.t0 = _DateTimeRow('from')
        self.t1 = _DateTimeRow('to')
        tr.addRow(self.t0)
        tr.addRow(self.t1)
        right.addWidget(self.tr_w)

        # Flag 选项
        self.flag_combo = QComboBox()
        self.flag_combo.addItems([
            tr('无视标记状态'),
            tr('仅删除被标记为...的数据点'),
            tr('仅删除未被标记为...的数据点'),
        ])
        self.flag_combo.currentIndexChanged.connect(self._on_flag_mode)
        right.addWidget(QLabel(tr('标记过滤：')))
        right.addWidget(self.flag_combo)

        self.flag_list = QListWidget()
        self.flag_list.setMaximumHeight(90)
        for f in ('Synthesized', 'Icing', 'Invalid', 'Low quality',
                  'Tower shading'):
            it = QListWidgetItem(f)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.flag_list.addItem(it)
        right.addWidget(self.flag_list)

        self.warn = QLabel()
        self.warn.setStyleSheet('color:#c0392b; font-size:11px;')
        right.addWidget(self.warn)

        right.addStretch(1)
        main.addLayout(right, 1)
        lay.addLayout(main, 1)

        # 按钮
        btns = QHBoxLayout()
        btns.addStretch(1)
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, 'Help', self.HELP))
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(help_btn)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        # 默认时间
        if not ds.df.empty:
            self.t0.set_dt(pd.Timestamp(ds.df.index[0]))
            self.t1.set_dt(pd.Timestamp(ds.df.index[-1]))
        self._on_mode()
        self.rb_del_cols.toggled.connect(self._on_mode)
        self.rb_del_points.toggled.connect(self._on_mode)

    def _on_mode(self):
        points = self.rb_del_points.isChecked()
        self.tr_w.setEnabled(points)
        self.flag_combo.setEnabled(points)
        self.flag_list.setEnabled(points)
        self.warn.setEnabled(points)
        self._on_flag_mode()

    def _on_flag_mode(self):
        points = self.rb_del_points.isChecked()
        idx = self.flag_combo.currentIndex()
        need_flag = points and idx in (1, 2)
        self.flag_list.setEnabled(need_flag)
        if need_flag and not self._checked_flags():
            self.warn.setText('⚠ You must choose at least one flag.')
        else:
            self.warn.setText('')

    def _checked_flags(self) -> list[str]:
        out = []
        for i in range(self.flag_list.count()):
            it = self.flag_list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.text())
        return out

    def _on_ok(self):
        df = self._ds.df
        if self.rb_del_cols.isChecked():
            cols = self.cols.checked()
            if not cols:
                QMessageBox.warning(self, tr('未选择'), tr('请勾选要删除的通道'))
                return
            for c in cols:
                if c in df.columns:
                    df.drop(columns=[c], inplace=True)
                self._ds.channels.pop(c, None)
                self._ds.calibrations.pop(c, None)
            self._info = f'已删除 {len(cols)} 个通道'
            self.accept()
            return

        # 删除数据点
        cols = self.cols.checked()
        if not cols:
            QMessageBox.warning(self, tr('未选择'), tr('请勾选要删除的通道'))
            return
        a = self.t0.get_dt()
        b = self.t1.get_dt()
        mask = (df.index >= a) & (df.index <= b)
        idx = self.flag_combo.currentIndex()
        if idx == 1:
            flags = self._checked_flags()
            if not flags:
                QMessageBox.warning(self, tr('未选择标记'),
                                    tr('请选择至少一个标记'))
                return
            flag_mask = self._ds.flags if len(self._ds.flags) == len(df) else pd.Series(False, index=df.index)
            mask = mask & flag_mask
        elif idx == 2:
            flags = self._checked_flags()
            if not flags:
                QMessageBox.warning(self, tr('未选择标记'),
                                    tr('请选择至少一个标记'))
                return
            flag_mask = self._ds.flags if len(self._ds.flags) == len(df) else pd.Series(False, index=df.index)
            mask = mask & (~flag_mask)

        n = int(mask.sum())
        if n == 0:
            QMessageBox.information(self, tr('无匹配'), tr('没有符合条件的数据点'))
            return
        df.drop(df.index[mask], inplace=True)
        if len(self._ds.flags) == len(df) + n:
            self._ds.flags = self._ds.flags[~mask]
        self._info = f'已从 {len(cols)} 个通道删除 {n} 个时间点'
        self.accept()


# ------------------------------------------------------------------ 4. 填补缺失值
class CoverageTimeline(QWidget):
    """原版风格的数据覆盖时间线：每通道一行色带，缺测处留白形成白色竖线。

    set_data 一次性把每通道时间轴降采样为固定桶数（时间比例位置），
    之后 paintEvent 只做快速绘制，勾选变化不重新计算。
    """

    PALETTE = ['#1f4e79', '#7b241c', '#7d6608', '#ca6f1e', '#2471a3',
               '#839192', '#148f77', '#7d3c98', '#b7950b', '#a04000',
               '#1e8449', '#2874a6', '#943126', '#6e2c00', '#4a235a',
               '#34495e', '#884313', '#196f3d']

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, np.ndarray]] = []
        self._t0 = None
        self._t1 = None

    def set_data(self, df: pd.DataFrame, cols: list[str], buckets: int = 1000):
        """每通道一次向量化降采样：桶 = 时间比例分格，值 = 有效率。"""
        self._rows = []
        self._t0 = self._t1 = None
        n = len(df)
        if n == 0 or not isinstance(df.index, pd.DatetimeIndex):
            self.update()
            return
        self._t0 = pd.Timestamp(df.index[0])
        self._t1 = pd.Timestamp(df.index[-1])
        buckets = max(20, min(buckets, n))
        tv = df.index.asi8.astype(np.float64)
        t0v, t1v = float(tv[0]), float(tv[-1])
        span = max(t1v - t0v, 1.0)
        bidx = np.clip(((tv - t0v) / span * buckets).astype(np.int64),
                       0, buckets - 1)
        cnt = np.bincount(bidx, minlength=buckets).astype(np.float64)
        for col in cols:
            if col not in df.columns:
                continue
            pres = pd.notna(df[col].to_numpy()).astype(np.float64)
            s = np.bincount(bidx, weights=pres, minlength=buckets)
            frac = np.divide(s, cnt, out=np.zeros(buckets), where=cnt > 0)
            self._rows.append((display_name(col), frac))
        self.update()

    def paintEvent(self, ev):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#ffffff'))
        if not self._rows or self._t0 is None:
            painter.end()
            return
        w = self.width()
        label_w = min(210, max(120, w // 5))
        top = 4
        bottom = 30
        h = max(self.height() - top - bottom, 10)
        n_rows = len(self._rows)
        row_h = max(3.0, min(26.0, h / n_rows))
        font = QFont(self.font())
        font.setPointSizeF(7.5)
        painter.setFont(font)
        span = max((self._t1 - self._t0).total_seconds(), 1.0)
        plot_w = w - label_w - 6

        def tx(ts):
            return (label_w + (pd.Timestamp(ts) - self._t0).total_seconds()
                    / span * plot_w)

        # 月份网格线与标签
        months = pd.date_range(self._t0.replace(day=1), self._t1, freq='MS')
        painter.setPen(QPen(QColor('#d5d8dc'), 1))
        for m in months:
            x = tx(m)
            painter.drawLine(int(x), top, int(x), int(top + h))
        # 每行色带（连续有效桶合并为矩形，缺测桶留白）
        buckets = len(self._rows[0][1])
        bx = plot_w / buckets
        for ri, (label, frac) in enumerate(self._rows):
            y = top + ri * row_h
            color = QColor(self.PALETTE[ri % len(self.PALETTE)])
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            present = np.flatnonzero(frac >= 0.5)
            if len(present):
                splits = np.flatnonzero(np.diff(present) > 1)
                starts = np.r_[present[0], present[splits + 1]]
                ends = np.r_[present[splits], present[-1]]
                for s, e in zip(starts, ends):
                    painter.drawRect(QRectF(label_w + s * bx, y + 1.0,
                                            (e - s + 1) * bx, row_h - 2.0))
            painter.setPen(QColor('#2c3e50'))
            painter.drawText(QRectF(0, y, label_w - 6, row_h),
                             Qt.AlignRight | Qt.AlignVCenter, label)
        # 月份名 + 年份
        painter.setPen(QColor('#566573'))
        for m in months:
            x = tx(m)
            painter.drawText(QRectF(x - 16, top + h + 2, 34, 12),
                             Qt.AlignCenter, m.strftime('%b'))
        for yr in sorted({m.year for m in months}):
            ya = max(self._t0, pd.Timestamp(yr, 1, 1))
            yb = min(self._t1, pd.Timestamp(yr, 12, 31, 23, 59))
            xc = (tx(ya) + tx(yb)) / 2
            painter.drawText(QRectF(xc - 24, top + h + 14, 48, 12),
                             Qt.AlignCenter, str(yr))
        painter.end()


class FillGapsDialog(QDialog):
    HELP = ('Choose an action, select the data columns to fill, then click '
            'Fill Gaps. The timeline below shows data coverage before '
            'filling; white stripes mark missing segments.')

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Fill Gaps'))
        self.resize(980, 640)
        self._ds = ds
        self._cols_all = _numeric_cols(ds)
        self._nan_count: dict[str, int] = {}
        self._runs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        self._dt_hours = 1.0
        self._info = ''

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        top = QHBoxLayout()
        # 左侧：动作与范围（对齐原版）
        left = QVBoxLayout()
        left.addWidget(QLabel(tr('What action should Windographer perform?')))
        self.rb_recon = QRadioButton(
            tr('Reconstruct using data from other heights where available'))
        self.rb_synth = QRadioButton(
            tr('Reconstruct, then fill remaining gaps with synthetic data'))
        self.rb_recon.setChecked(True)
        self._bg_action = QButtonGroup(self)
        self._bg_action.addButton(self.rb_recon)
        self._bg_action.addButton(self.rb_synth)
        left.addWidget(self.rb_recon)
        left.addWidget(self.rb_synth)
        left.addSpacing(12)
        left.addWidget(QLabel(tr('Fill gaps in')))
        self.rb_all = QRadioButton(tr('all time steps'))
        self.rb_seg = QRadioButton(tr('particular time segment'))
        self.rb_all.setChecked(True)
        self._bg_range = QButtonGroup(self)
        self._bg_range.addButton(self.rb_all)
        self._bg_range.addButton(self.rb_seg)
        left.addWidget(self.rb_all)
        left.addWidget(self.rb_seg)
        self.seg0 = _DateTimeRow(tr('Start time'))
        self.seg1 = _DateTimeRow(tr('End time'))
        left.addWidget(self.seg0)
        left.addWidget(self.seg1)
        self.chk_flag = QCheckBox(tr('Flag gap filled segments with'))
        self.chk_flag.setChecked(True)
        self.flag_gap = QComboBox()
        self.flag_gap.addItems(['Synthesized', 'Icing', 'Invalid',
                                'Low quality', 'Tower shading'])
        fl = QHBoxLayout()
        fl.addWidget(self.chk_flag)
        fl.addWidget(self.flag_gap, 1)
        left.addLayout(fl)
        left.addStretch(1)
        top.addLayout(left, 1)

        # 中间：通道勾选列表（全部默认勾选）
        mid = QVBoxLayout()
        mid.addWidget(QLabel(tr('Fill gaps in the following data columns:')))
        self.chk_sel_all = QCheckBox(tr('Select all'))
        self.chk_sel_all.setChecked(True)
        self.chk_sel_all.stateChanged.connect(self._on_select_all)
        mid.addWidget(self.chk_sel_all)
        self.col_listw = QListWidget()
        self.col_listw.setSelectionMode(QAbstractItemView.NoSelection)
        self.col_listw.setUniformItemSizes(True)
        for c in self._cols_all:
            item = QListWidgetItem(display_name(c))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, c)
            self.col_listw.addItem(item)
        self.col_listw.itemChanged.connect(self._queue_update)
        mid.addWidget(self.col_listw, 1)
        top.addLayout(mid, 1)

        # 右侧：统计表
        stats_w = QWidget()
        sl = QVBoxLayout(stats_w)
        sl.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(7, 3)
        self.table.setHorizontalHeaderLabels([
            tr('Statistic'), tr('Entire Data Set'), tr('Selected Subset')])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        sl.addWidget(self.table)
        top.addWidget(stats_w, 1)
        lay.addLayout(top, 1)

        # 底部：时间线（仅打开时计算一次，与勾选无关）
        self.timeline = CoverageTimeline()
        self.timeline.setMinimumHeight(210)
        lay.addWidget(self.timeline, 1)

        # 按钮
        btns = QHBoxLayout()
        btns.addStretch(1)
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, tr('Help'), tr(self.HELP)))
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('Fill Gaps...'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(help_btn)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        # 事件：勾选/区间变化 → 250ms 防抖后仅刷新统计表（毫秒级）
        self.rb_all.toggled.connect(self._on_range_mode)
        self._range_widgets = (self.seg0.date, self.seg0.time,
                               self.seg1.date, self.seg1.time)
        for wgt in self._range_widgets:
            wgt.dateTimeChanged.connect(self._queue_update)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_stats)

        if not ds.df.empty:
            self.seg0.set_dt(pd.Timestamp(ds.df.index[0]))
            self.seg1.set_dt(pd.Timestamp(ds.df.index[-1]))
        self._set_seg_enabled(False)
        self._build_cache()
        self.timeline.set_data(ds.df, self._cols_all)
        self._update_stats()

    # ---- 交互 ----
    def _on_select_all(self, state):
        chk = Qt.Checked if state == Qt.Checked else Qt.Unchecked
        for i in range(self.col_listw.count()):
            self.col_listw.item(i).setCheckState(chk)

    def _on_range_mode(self, all_mode):
        self._set_seg_enabled(not all_mode)
        self._queue_update()

    def _set_seg_enabled(self, on: bool):
        self.seg0.setEnabled(on)
        self.seg1.setEnabled(on)

    def _queue_update(self, *args):
        self._timer.start()

    def _checked_cols(self) -> list[str]:
        out = []
        for i in range(self.col_listw.count()):
            it = self.col_listw.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    # ---- 一次性缓存（向量化，毫秒级）----
    def _build_cache(self):
        df = self._ds.df
        if df.empty or not isinstance(df.index, pd.DatetimeIndex):
            return
        if len(df) > 1:
            diffs = pd.Series(df.index).diff().dropna()
            self._dt_hours = max(pd.Timedelta(
                diffs.median()).total_seconds() / 3600.0, 1e-9)
        for col in self._cols_all:
            if col not in df.columns:
                continue
            miss = pd.isna(df[col].to_numpy())
            self._nan_count[col] = int(miss.sum())
            m8 = miss.astype(np.int8)
            d = np.diff(m8)
            starts = np.flatnonzero(d == 1) + 1
            ends = np.flatnonzero(d == -1) + 1
            if miss[0]:
                starts = np.r_[0, starts]
            if miss[-1]:
                ends = np.r_[ends, m8.size]
            self._runs[col] = (starts, ends)

    def _row_range(self) -> tuple[int, int]:
        n = len(self._ds.df)
        if self.rb_all.isChecked() or n == 0:
            return 0, n
        idx = self._ds.df.index
        a = int(idx.searchsorted(pd.Timestamp(self.seg0.get_dt())))
        b = int(idx.searchsorted(pd.Timestamp(self.seg1.get_dt()),
                                 side='right'))
        return a, max(b, a)

    # ---- 统计（选择变化时仅做向量运算，O(k) 汇总 + 区间裁剪）----
    def _gap_stats(self, cols: list[str], i0: int, i1: int) -> tuple:
        n_gaps = 0
        lens = []
        for col in cols:
            r = self._runs.get(col)
            if r is None:
                continue
            s, e = r
            sel = (s < i1) & (e > i0)
            if not sel.any():
                continue
            ss = np.clip(s[sel], i0, i1)
            ee = np.clip(e[sel], i0, i1)
            n_gaps += int(sel.sum())
            lens.append((ee - ss) * self._dt_hours)
        if n_gaps:
            all_lens = np.concatenate(lens)
            return n_gaps, float(all_lens.mean()), float(all_lens.min()), \
                float(all_lens.max())
        return 0, 0.0, 0.0, 0.0

    def _update_stats(self):
        df = self._ds.df
        cols = self._checked_cols()
        n = len(df)
        if not cols or n == 0:
            self.table.setRowCount(0)
            return
        k = len(cols)
        i0, i1 = self._row_range()
        span = max(i1 - i0, 0)

        total_all = n * k
        miss_all = sum(self._nan_count.get(c, 0) for c in cols)
        comp_all = 100.0 * (total_all - miss_all) / total_all if total_all else 0.0
        g_all = self._gap_stats(cols, 0, n)

        total_sub = span * k
        miss_sub = 0
        for c in cols:
            if c in df.columns:
                miss_sub += int(pd.isna(df[c].to_numpy()[i0:i1]).sum())
        comp_sub = (100.0 * (total_sub - miss_sub) / total_sub
                    if total_sub else 0.0)
        g_sub = self._gap_stats(cols, i0, i1)

        rows = [
            (tr('Total data points'), f'{total_all:,}', f'{total_sub:,}'),
            (tr('Missing data points'), f'{miss_all:,}', f'{miss_sub:,}'),
            (tr('Data completeness (%)'), f'{comp_all:.1f}', f'{comp_sub:.1f}'),
            (tr('Number of gaps'), f'{g_all[0]:,}', f'{g_sub[0]:,}'),
            (tr('Mean gap length (hr)'), f'{g_all[1]:.1f}', f'{g_sub[1]:.1f}'),
            (tr('Shortest gap (hr)'), f'{g_all[2]:.1f}', f'{g_sub[2]:.1f}'),
            (tr('Longest gap (hr)'), f'{g_all[3]:.1f}', f'{g_sub[3]:.1f}'),
        ]
        self.table.setRowCount(len(rows))
        for r, (name, a, b) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(a))
            self.table.setItem(r, 2, QTableWidgetItem(b))

    # ---- 执行 ----
    def _reconstruct(self, col: str, i0: int, i1: int, synth: bool):
        """用同类其它高度通道重建，synth=True 时再线性填补剩余缺测。"""
        ds = self._ds
        df = ds.df
        seg = df[col].iloc[i0:i1].copy()
        ch = ds.channels.get(col)
        others = []
        for c in self._cols_all:
            if c == col or c not in df.columns:
                continue
            oc = ds.channels.get(c)
            if oc is not None and ch is not None and oc.kind == ch.kind:
                others.append(c)
        h0 = ch.height if ch is not None else None
        others.sort(key=lambda c: abs(
            (ds.channels[c].height or 0) - (h0 or 0)))
        for oc in others:
            need = pd.isna(seg.to_numpy())
            if not need.any():
                break
            src = df[oc].iloc[i0:i1]
            ok_vals = src.to_numpy()[need]
            good = ~pd.isna(ok_vals)
            idx = np.flatnonzero(need)[good]
            seg.iloc[idx] = src.to_numpy()[need][good]
        if synth:
            seg = _interp(seg, 'linear')
        return seg

    def _on_ok(self):
        cols = self._checked_cols()
        if not cols:
            QMessageBox.warning(self, tr('No columns'),
                                tr('Please select at least one data column'))
            return
        df = self._ds.df
        if df.empty:
            self.reject()
            return
        i0, i1 = self._row_range()
        use_recon = self.rb_recon.isChecked()
        n_fill = 0
        for col in cols:
            if col not in df.columns:
                continue
            before = int(pd.isna(df[col].to_numpy()[i0:i1]).sum())
            if before == 0:
                continue
            filled = self._reconstruct(col, i0, i1, synth=not use_recon)
            df.iloc[i0:i1, df.columns.get_loc(col)] = filled.to_numpy()
            after = int(pd.isna(df[col].to_numpy()[i0:i1]).sum())
            n_fill += before - after
        self._info = tr('Filled {} data points in {} columns',
                        n_fill, len(cols))
        self.accept()

    def result_info(self):
        return self._info


# ------------------------------------------------------------------ 5. 修复量化（原版 Fix Quantization）
class FixQuantizationDialog(QDialog):
    HELP = ('Detect quantization in a data column and add small random '
            'offsets to each data point so the distribution no longer '
            'shows empty bins. The left histogram shows the original data; '
            'the right shows the randomized data.')

    ORIG_COLOR = '#1f4e79'    # 原版：原始数据深蓝
    FIX_COLOR = '#8f5900'     # 原版：修改后数据棕黄

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Fix Quantization'))
        self.resize(900, 580)
        self._ds = ds
        self._step: float = 1.0
        self._month: pd.Timestamp | None = None
        self._info = ''
        self._orig_disp: pd.Series | None = None
        self._fixed_disp: pd.Series | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        # ---- 顶部：第一行 Data column + Modify；第二行 Display（对齐原版）----
        top = QGridLayout()
        top.setHorizontalSpacing(14)
        top.addWidget(QLabel(tr('Data column:')), 0, 0)
        self.channel = QComboBox()
        self.channel.addItems([display_name(c) for c in _numeric_cols(ds)])
        self.channel.setMinimumContentsLength(24)
        self.channel.currentIndexChanged.connect(self._update)
        top.addWidget(self.channel, 0, 1)
        top.setColumnStretch(1, 1)

        grp_mod = QGroupBox(tr('Modify'))
        mv = QVBoxLayout(grp_mod)
        hm = QHBoxLayout()
        self.m_all = QRadioButton(tr('all time steps'))
        self.m_int = QRadioButton(tr('only the interval:'))
        self.m_all.setChecked(True)
        self._bg_mod = QButtonGroup(self)
        self._bg_mod.addButton(self.m_all)
        self._bg_mod.addButton(self.m_int)
        hm.addWidget(self.m_all)
        hm.addWidget(self.m_int)
        hm.addStretch(1)
        mv.addLayout(hm)
        iv = QGridLayout()
        iv.addWidget(QLabel(tr('from')), 0, 0)
        self.int0 = _DateTimeRow('')
        iv.addWidget(self.int0, 0, 1)
        iv.addWidget(QLabel(tr('to')), 1, 0)
        self.int1 = _DateTimeRow('')
        iv.addWidget(self.int1, 1, 1)
        mv.addLayout(iv)
        top.addWidget(grp_mod, 0, 2, 2, 1)

        grp_disp = QGroupBox(tr('Display'))
        dh = QHBoxLayout(grp_disp)
        self.d_freq = QRadioButton(tr('frequency distributions'))
        self.d_time = QRadioButton(tr('time series graph'))
        self.d_freq.setChecked(True)
        self._bg_disp = QButtonGroup(self)
        self._bg_disp.addButton(self.d_freq)
        self._bg_disp.addButton(self.d_time)
        dh.addWidget(self.d_freq)
        dh.addWidget(self.d_time)
        top.addWidget(grp_disp, 1, 0, 1, 2)
        lay.addLayout(top)

        # ---- 图表区：频率=左右双直方图；时序=单图叠加 + 月份导航 ----
        self.stack = QStackedWidget()
        freq_w = QWidget()
        fh = QHBoxLayout(freq_w)
        fh.setContentsMargins(0, 0, 0, 0)
        self.c_orig = PlotCanvas(tr('Original Data'))
        self.c_fixed = PlotCanvas(tr('Modified Data'))
        for c in (self.c_orig, self.c_fixed):
            c.setMinimumHeight(240)
            fh.addWidget(c, 1)
        self.stack.addWidget(freq_w)

        time_w = QWidget()
        tv = QVBoxLayout(time_w)
        tv.setContentsMargins(0, 0, 0, 0)
        self.c_both = PlotCanvas('')
        tv.addWidget(self.c_both, 1)
        nav = QHBoxLayout()
        self.btn_prev_m = QPushButton('◀')
        self.btn_prev_m.setFixedWidth(34)
        self.btn_next_m = QPushButton('▶')
        self.btn_next_m.setFixedWidth(34)
        self.lbl_month = QLabel('')
        self.lbl_month.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        nav.addWidget(self.btn_prev_m)
        nav.addWidget(self.btn_next_m)
        nav.addWidget(self.lbl_month, 1)
        tv.addLayout(nav)
        self.stack.addWidget(time_w)
        lay.addWidget(self.stack, 1)
        self.btn_prev_m.clicked.connect(lambda: self._shift_month(-1))
        self.btn_next_m.clicked.connect(lambda: self._shift_month(1))

        # ---- 底部：Help + 信息提示 + Cancel/OK（同原版一行）----
        bottom = QHBoxLayout()
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, tr('Help'), tr(self.HELP)))
        bottom.addWidget(help_btn)
        info_icon = QLabel('ⓘ')
        info_icon.setStyleSheet('color:#2c7be5; font-size:16px;')
        bottom.addWidget(info_icon)
        self.info_lbl = QLabel()
        self.info_lbl.setStyleSheet('color:#5a6573; font-size:11px;')
        self.info_lbl.setWordWrap(True)
        bottom.addWidget(self.info_lbl, 1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('OK'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        bottom.addWidget(cancel)
        bottom.addWidget(ok)
        lay.addLayout(bottom)

        # ---- 事件 ----
        self.d_freq.toggled.connect(lambda _c: self._update())
        self.m_all.toggled.connect(lambda _c: self._update())
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._update)
        for wgt in (self.int0.date, self.int0.time, self.int1.date, self.int1.time):
            wgt.dateTimeChanged.connect(self._debounce.start)

        if not ds.df.empty:
            self.int0.set_dt(pd.Timestamp(ds.df.index[0]))
            self.int1.set_dt(pd.Timestamp(ds.df.index[-1]))
        self._update()

    # ---- 基础 ----
    def _col(self) -> str | None:
        if self.channel.count() == 0:
            return None
        return _col_from_display(self._ds, self.channel.currentText())

    def _mask(self) -> pd.Series:
        if self.m_all.isChecked() or self._ds.df.empty:
            return pd.Series(True, index=self._ds.df.index)
        a = self.int0.get_dt()
        b = self.int1.get_dt()
        return (self._ds.df.index >= a) & (self._ds.df.index <= b)

    def _detect_step(self, s: pd.Series) -> float:
        vals = s.dropna().sort_values().unique()
        if len(vals) < 2:
            return 1.0
        diffs = np.diff(vals)
        diffs = diffs[diffs > 1e-12]
        if len(diffs) == 0:
            return 1.0
        from collections import Counter
        rounded = np.round(diffs, decimals=max(
            0, 3 - int(math.log10(max(diffs.min(), 1e-9)))))
        step = float(Counter(rounded).most_common(1)[0][0])
        if step <= 0:
            step = float(np.median(diffs))
        return max(step, 1e-6)

    def _fixed(self, s: pd.Series, step: float, col: str) -> pd.Series:
        # 固定随机种子：同一列每次预览噪声一致（原版行为：预览稳定）
        rng = np.random.default_rng(abs(hash(col)) % (2 ** 32))
        noise = rng.uniform(-step / 2, step / 2, size=len(s))
        return s + noise

    def _unit_of(self, col: str) -> str:
        return next((c.units for c in self._ds.channels.values()
                     if c.name == col), '')

    # ---- 绘制 ----
    def _hist_density(self, s: pd.Series):
        """返回 (edges, density%)：密度 = 占比% / 单位宽度，同原版
        Frequency Density (%/m/s) 轴。"""
        vals = s.dropna()
        if len(vals) == 0:
            return np.array([0.0, 1.0]), np.array([])
        lo, hi = float(vals.min()), float(vals.max())
        if hi <= lo:
            hi = lo + max(abs(lo) * 0.1, 1.0)
        edges = np.linspace(lo, hi, 41)
        counts, _ = np.histogram(vals, bins=edges)
        bin_w = edges[1] - edges[0]
        dens = counts / max(len(vals), 1) / bin_w * 100.0
        return edges, dens

    def _draw_freq(self, col: str):
        unit = self._unit_of(col)
        ylabel = tr('Frequency Density') + (f' (%/{unit})' if unit else ' (%)')
        xlabel = display_name(col) + (f' ({unit})' if unit else '')
        edges, dens_o = self._hist_density(self._orig_disp)
        _, dens_f = self._hist_density(self._fixed_disp)
        for canvas, dens, color, title in (
                (self.c_orig, dens_o, self.ORIG_COLOR, tr('Original Data')),
                (self.c_fixed, dens_f, self.FIX_COLOR, tr('Modified Data'))):
            canvas.set_title(title)
            canvas.plot_histogram(edges, dens, xlabel=xlabel, ylabel=ylabel,
                                  color=color)

    def _month_title(self, m: pd.Timestamp) -> str:
        if language() == 'en':
            names = ['January', 'February', 'March', 'April', 'May', 'June',
                     'July', 'August', 'September', 'October', 'November',
                     'December']
            return f'{names[m.month - 1]} {m.year}'
        return f'{m.year}年{m.month}月'

    def _init_month(self):
        if self._month is None and self._orig_disp is not None \
                and len(self._orig_disp):
            t0 = self._orig_disp.index[0]
            self._month = pd.Timestamp(t0.year, t0.month, 1)

    def _shift_month(self, k: int):
        if self._month is None:
            return
        m = self._month.month + k
        y = self._month.year
        if m == 0:
            m, y = 12, y - 1
        elif m == 13:
            m, y = 1, y + 1
        self._month = pd.Timestamp(y, m, 1)
        self._draw_time()

    def _draw_time(self):
        if self._month is None or self._orig_disp is None:
            return
        col = self._cur_col
        m0 = self._month
        m1 = m0 + pd.offsets.MonthBegin(1)
        o = self._orig_disp[(self._orig_disp.index >= m0)
                            & (self._orig_disp.index < m1)]
        f = self._fixed_disp[(self._fixed_disp.index >= m0)
                             & (self._fixed_disp.index < m1)]
        title = self._month_title(m0)
        self.c_both.set_title(title)
        self.lbl_month.setText(title)

        # x = 月内日 + 一天内的时刻比例（1..31 数轴，同原版）
        def dayx(index):
            return (index.day
                    + (index.hour * 60 + index.minute) / 1440.0).to_numpy()

        lbl_o = f'{display_name(col)} ({tr("original")})'
        lbl_f = f'{display_name(col)} ({tr("modified")})'
        self.c_both.set_series_color(lbl_o, self.ORIG_COLOR)
        self.c_both.set_series_color(lbl_f, self.FIX_COLOR)
        self.c_both.plot_lines(
            [(lbl_o, dayx(o.index), o.to_numpy()),
             (lbl_f, dayx(f.index), f.to_numpy())],
            ylabel=self._unit_of(col), xtick_step=2)

    # ---- 刷新 ----
    def _update(self):
        col = self._col()
        if col is None or col not in self._ds.df.columns:
            self.c_orig.clear(tr('No data'))
            self.c_fixed.clear(tr('No data'))
            self.c_both.clear(tr('No data'))
            return
        self._cur_col = col
        s = _to_num(self._ds.df[col])
        self._step = self._detect_step(s)
        mask = self._mask()
        self._orig_disp = s[mask]
        self._fixed_disp = self._fixed(s, self._step, col)[mask]
        self._month = None
        if self.d_freq.isChecked():
            self.stack.setCurrentIndex(0)
            self._draw_freq(col)
        else:
            self.stack.setCurrentIndex(1)
            self._init_month()
            self._draw_time()

        ratio = s.nunique() / max(len(s.dropna()), 1)
        if ratio < 0.1:
            msg = tr('Your data is highly quantized. This operation will '
                     'have a significant effect on your data.')
        elif ratio < 0.3:
            msg = tr('Your data shows moderate quantization. This operation '
                     'may have a moderate effect on your data.')
        else:
            msg = tr('Your data is not very highly quantized. Using this '
                     'window will likely not have a significant effect on '
                     'your data.')
        self.info_lbl.setText(f'{msg} (detected step ≈ {self._step:.4g})')

    # ---- 执行 ----
    def _on_ok(self):
        col = self._col()
        if not col or col not in self._ds.df.columns:
            return
        s = _to_num(self._ds.df[col])
        self._step = self._detect_step(s)
        mask = self._mask()
        fixed = self._fixed(s, self._step, col)
        self._ds.df.loc[mask, col] = fixed.where(mask, s)
        self._info = tr('Quantization fixed: {} (step {})',
                        display_name(col), f'{self._step:.4g}')
        self.accept()

    def result_info(self):
        return self._info


# ------------------------------------------------------------------ 6. 组合风速仪
class CombineSensorsDialog(QDialog):
    HELP = ('Select a first and second anemometer, choose a combination '
            'method, and optionally hide the original columns.')

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('组合风速仪'))
        self.resize(640, 420)
        self._ds = ds

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        main = QHBoxLayout()
        # First Anemometer
        g1 = QGroupBox(tr('First Anemometer'))
        v1 = QVBoxLayout(g1)
        self.list1 = QListWidget()
        self.list1.setSelectionMode(QAbstractItemView.SingleSelection)
        v1.addWidget(self.list1)
        main.addWidget(g1, 1)

        # Second Anemometer
        g2 = QGroupBox(tr('Second Anemometer'))
        v2 = QVBoxLayout(g2)
        self.list2 = QListWidget()
        self.list2.setSelectionMode(QAbstractItemView.SingleSelection)
        v2.addWidget(self.list2)
        main.addWidget(g2, 1)

        # Method
        g3 = QGroupBox(tr('Combination Method'))
        v3 = QVBoxLayout(g3)
        self.method = QComboBox()
        self.method.addItems(['average', 'primary', 'minimum', 'maximum'])
        v3.addWidget(self.method)
        v3.addStretch(1)
        main.addWidget(g3, 1)

        lay.addLayout(main, 1)

        self.hide_orig = QCheckBox(tr('Hide original data columns'))
        lay.addWidget(self.hide_orig)

        # 填充风速列表
        speeds = [c.name for c in ds.channels.values() if c.kind == 'speed']
        for c in speeds:
            self.list1.addItem(display_name(c))
            self.list2.addItem(display_name(c))

        btns = QHBoxLayout()
        btns.addStretch(1)
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, 'Help', self.HELP))
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(help_btn)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _sel(self, lst: QListWidget) -> str | None:
        it = lst.currentItem()
        if not it:
            return None
        return _col_from_display(self._ds, it.text())

    def _on_ok(self):
        c1 = self._sel(self.list1)
        c2 = self._sel(self.list2)
        if not c1 or not c2:
            QMessageBox.warning(self, tr('通道不足'), tr('请选择两个风速通道'))
            return
        if c1 == c2:
            QMessageBox.warning(self, tr('通道重复'), tr('两个通道不能相同'))
            return
        df = self._ds.df
        s1 = _to_num(df[c1])
        s2 = _to_num(df[c2])
        method = self.method.currentText()
        if method == 'average':
            res = pd.concat([s1, s2], axis=1).mean(axis=1, min_count=1)
        elif method == 'primary':
            res = s1.fillna(s2)
        elif method == 'minimum':
            res = pd.concat([s1, s2], axis=1).min(axis=1)
        else:
            res = pd.concat([s1, s2], axis=1).max(axis=1)
        out = f'Combined {display_name(c1)}'
        if out in df.columns:
            out = f'Combined {c1}'
        df[out] = res
        src = self._ds.channels.get(c1)
        ch = Channel(
            name=out,
            kind=src.kind if src else 'speed',
            height=src.height if src else None,
            units=src.units if src else '',
            role='Combined')
        self._ds.channels[out] = ch
        if self.hide_orig.isChecked():
            for c in (c1, c2):
                if c in df.columns:
                    df.drop(columns=[c], inplace=True)
                self._ds.channels.pop(c, None)
                self._ds.calibrations.pop(c, None)
        self._info = f'已组合 {display_name(c1)} + {display_name(c2)}（{method}）'
        self.accept()


# ------------------------------------------------------------------ 7. 垂直外推
class VerticalExtrapolationDialog(QDialog):
    """Vertical Extrapolation：原版布局。

    左（共享）：Synthesize 复选 + 目标高度表（20 行）+ Flag new columns；
    右：Speed | Direction | Temperature 三个 Tab；
    Speed 幂律指数 8 种模式（每时间步计算 / 常数 / 月 / 小时 / 方向扇区 /
    月×小时 / 扇区×月 / 扇区×小时），指数表按数据预填中位数并可编辑。
    """

    ALPHA_MODES = [
        'Calculate in each time step',
        'Specify as a constant',
        'Specify by month',
        'Specify by hour of day',
        'Specify by direction sector',
        'Specify by month and hour of day',
        'Specify by direction sector and month',
        'Specify by direction sector and hour of day',
    ]
    MONTH_LB = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Vertical Extrapolation'))
        self.resize(1000, 640)
        self._ds = ds
        self._info = ''
        # 原版行为：外推源列表只列平均值（Avg）通道；SD 列由外推自动生成
        self._speed_src = [c.name for c in ds.channels.values()
                           if c.kind == 'speed'
                           and (c.role or 'Avg') == 'Avg']
        self._dir_src = [c.name for c in ds.channels.values()
                         if c.kind == 'dir'
                         and (c.role or 'Avg') == 'Avg']
        self._temp_src = [c.name for c in ds.channels.values()
                          if c.kind == 'temp'
                          and (c.role or 'Avg') == 'Avg']
        self._alpha_cache = None      # 每时间步 alpha（惰性）
        self._sector_prefilled_n = 0

        root = QVBoxLayout(self)
        body = QHBoxLayout()

        # ---- 左（共享）：Synthesize + 高度表 + Flag ----
        left = QWidget()
        left.setFixedWidth(230)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)
        lv.addWidget(QLabel(tr('Synthesize:')))
        self.chk_speed = QCheckBox(tr('Wind speed'))
        self.chk_speed.setChecked(True)
        self.chk_dir = QCheckBox(tr('Wind direction'))
        self.chk_dir.setChecked(True)
        self.chk_temp = QCheckBox(tr('Temperature'))
        self.chk_temp.setChecked(True)
        lv.addWidget(self.chk_speed)
        lv.addWidget(self.chk_dir)
        lv.addWidget(self.chk_temp)
        lv.addSpacing(10)
        lv.addWidget(QLabel(tr('for these heights:')))
        self.heights = QTableWidget(20, 2)
        self.heights.setHorizontalHeaderLabels(['#', tr('Height (m)')])
        self.heights.verticalHeader().setVisible(False)
        self.heights.setColumnWidth(0, 34)
        self.heights.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        default_h = self._default_target_height()
        for r in range(20):
            self.heights.setItem(r, 0, QTableWidgetItem(str(r + 1)))
            if r == 0 and default_h:
                self.heights.setItem(r, 1, QTableWidgetItem(f'{default_h:.1f}'))
        lv.addWidget(self.heights, 1)
        lv.addSpacing(8)
        self.chk_flag_new = QCheckBox(tr('Flag new columns with'))
        self.chk_flag_new.setChecked(True)
        lv.addWidget(self.chk_flag_new)
        self.flag_new = QComboBox()
        self.flag_new.addItems(['Synthesized', 'Icing', 'Invalid',
                                'Low quality', 'Tower shading'])
        lv.addWidget(self.flag_new)
        lv.addStretch(1)
        body.addWidget(left)

        # ---- 右：三个 Tab ----
        tabs = QTabWidget()
        tabs.addTab(self._build_speed_tab(), tr('Speed'))
        tabs.addTab(self._build_dir_tab(), tr('Direction'))
        tabs.addTab(self._build_temp_tab(), tr('Temperature'))
        body.addWidget(tabs, 1)
        root.addLayout(body, 1)

        btns = QHBoxLayout()
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, tr('Help'), tr(self.HELP)))
        btns.addWidget(help_btn)
        btns.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('Synthesize Data & Append To Data Set...'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

        self._prefill_tables()
        self._prefill_veer_tables()
        self._prefill_grad_tables()

    # ---------- 构建 Speed Tab ----------
    def _build_speed_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        top = QGridLayout()
        top.addWidget(QLabel(tr('Power law exponent')), 0, 0)
        self.alpha_method = QComboBox()
        for m in self.ALPHA_MODES:
            self.alpha_method.addItem(tr(m))
        top.addWidget(self.alpha_method, 0, 1)
        top.setColumnStretch(1, 1)
        v.addLayout(top)

        # Extrapolate from（模式 2-8 共享行）
        self.ex_row_w = QWidget()
        exh = QHBoxLayout(self.ex_row_w)
        exh.setContentsMargins(0, 0, 0, 0)
        exh.addWidget(QLabel(tr('Extrapolate from')))
        self.ref_combo = self._src_combo(self._speed_src)
        exh.addWidget(self.ref_combo)
        exh.addStretch(1)

        # Direction sensor + sectors（扇区模式共享行）
        self.sector_row_w = QWidget()
        seh = QHBoxLayout(self.sector_row_w)
        seh.setContentsMargins(0, 0, 0, 0)
        seh.addWidget(QLabel(tr('Direction sensor')))
        self.dir_combo = self._src_combo(self._dir_src)
        seh.addWidget(self.dir_combo)
        seh.addWidget(QLabel(tr('Direction sectors')))
        self.sector_spin = QSpinBox()
        self.sector_spin.setRange(1, 36)
        self.sector_spin.setValue(16)
        seh.addWidget(self.sector_spin)
        seh.addStretch(1)
        self.sector_spin.valueChanged.connect(
            lambda _v: self._on_sectors_changed())

        # 模式 1：Calculate in each time step
        p1 = QWidget()
        p1h = QHBoxLayout(p1)
        p1l = QVBoxLayout()
        p1l.addWidget(QLabel(tr('Calculate from')))
        self.src_speed = self._src_check_list(self._speed_src)
        p1l.addWidget(self.src_speed, 1)
        p1h.addLayout(p1l, 1)
        p1r = QVBoxLayout()
        self.chk_restrict = QCheckBox(
            tr('Restrict power law exponent to a range'))
        self.chk_restrict.setChecked(True)
        p1r.addWidget(self.chk_restrict)
        form = QFormLayout()
        self.alpha_min = QDoubleSpinBox()
        self.alpha_min.setRange(-1, 2)
        self.alpha_min.setDecimals(3)
        self.alpha_min.setValue(-0.05)
        self.alpha_max = QDoubleSpinBox()
        self.alpha_max.setRange(-1, 2)
        self.alpha_max.setDecimals(3)
        self.alpha_max.setValue(1.0)
        form.addRow(tr('Min. value'), self.alpha_min)
        form.addRow(tr('Max. value'), self.alpha_max)
        p1r.addLayout(form)
        p1r.addStretch(1)
        p1h.addLayout(p1r)

        # 模式 2：constant
        p2 = QWidget()
        p2v = QVBoxLayout(p2)
        p2v.addWidget(QLabel(tr('Enter constant power law exponent')))
        f2 = QFormLayout()
        self.alpha_const = QDoubleSpinBox()
        self.alpha_const.setRange(-1, 2)
        self.alpha_const.setDecimals(6)
        self.alpha_const.setValue(self._default_alpha())
        f2.addRow(tr('Constant power law exponent'), self.alpha_const)
        p2v.addLayout(f2)
        p2v.addStretch(1)

        # 模式 3-8 的指数表
        self.tbl_month = self._make_table(12, 2, 'Month', self.MONTH_LB)
        cap_month = self._wrap(self.tbl_month,
                               tr('Enter power law exponent by month'))
        hour_lb = [f'{h:02d}:00- {h + 1:02d}:00' for h in range(24)]
        self.tbl_hour = self._make_table(24, 2, 'Hour', hour_lb)
        cap_hour = self._wrap(self.tbl_hour,
                              tr('Enter power law exponent by hour of day'))
        self.tbl_sector = self._make_table(16, 2, 'Direction Sector', None)
        cap_sector = self._wrap(
            self.tbl_sector,
            tr('Enter power law exponent by direction sector'))
        self.tbl_month_hour = self._make_table(
            24, 13, 'Hour', self.MONTH_LB)
        cap_mh = self._wrap(
            self.tbl_month_hour,
            tr('Enter power law exponent by month and hour of day'))
        self.tbl_sector_month = self._make_table(
            16, 13, 'Direction Sector', self.MONTH_LB)
        cap_sm = self._wrap(
            self.tbl_sector_month,
            tr('Enter power law exponent by direction sector and month'))
        self.tbl_sector_hour = self._make_table(
            16, 25, 'Direction Sector', hour_lb)
        cap_sh = self._wrap(
            self.tbl_sector_hour,
            tr('Enter power law exponent by hour of day and direction sector'))

        self.mode_stack = QStackedWidget()
        for pg in (p1, p2, cap_month, cap_hour, cap_sector,
                   cap_mh, cap_sm, cap_sh):
            self.mode_stack.addWidget(pg)
        v.addWidget(self.ex_row_w)
        v.addWidget(self.sector_row_w)
        v.addWidget(self.mode_stack, 1)

        def _on_mode(i):
            self.ex_row_w.setVisible(i != 0)
            self.sector_row_w.setVisible(i in (4, 6, 7))
            self.mode_stack.setCurrentIndex(i)
            if i in (4, 6, 7):
                self._on_sectors_changed()

        self.alpha_method.currentIndexChanged.connect(_on_mode)
        _on_mode(0)
        return w

    def _make_table(self, rows: int, cols: int, first_header: str,
                    col_headers) -> QTableWidget:
        """cols=2 → 标签列+单指数列；cols>2 → 标签列+多列。"""
        tbl = QTableWidget(rows, cols)
        if cols == 2:
            tbl.setHorizontalHeaderLabels(
                [first_header, f'Power Law\nExponent'])
        else:
            tbl.setHorizontalHeaderLabels([first_header] + list(col_headers))
        tbl.verticalHeader().setVisible(False)
        # 标签列
        for r in range(rows):
            if cols == 2:
                lb = col_headers[r] if col_headers else ''
            else:
                lb = ''
            if lb:
                it = QTableWidgetItem(lb)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                tbl.setItem(r, 0, it)
        if cols > 2:
            tbl.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeToContents)
        return tbl

    def _wrap(self, table: QTableWidget, caption: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel(caption))
        v.addWidget(table)
        return w

    # ---------- 构建 Direction / Temperature Tab ----------
    def _build_dir_tab(self) -> QWidget:
        """Direction Tab：风向切变率（Wind veer rate，°/100m），6 种模式。"""
        w = QWidget()
        v = QVBoxLayout(w)
        top = QGridLayout()
        top.addWidget(QLabel(tr('Wind veer rate')), 0, 0)
        self.veer_method = QComboBox()
        for m in ('Calculate in each time step', 'Specify as a constant',
                  'Specify by month', 'Specify by hour of day',
                  'Specify by direction sector',
                  'Specify by month and hour of day',
                  'Specify by direction sector and month',
                  'Specify by direction sector and hour of day'):
            self.veer_method.addItem(tr(m))
        top.addWidget(self.veer_method, 0, 1)
        top.setColumnStretch(1, 1)
        v.addLayout(top)

        # Extrapolate from（模式 2-6 共享行）
        self.ex_dir_row_w = QWidget()
        exh = QHBoxLayout(self.ex_dir_row_w)
        exh.setContentsMargins(0, 0, 0, 0)
        exh.addWidget(QLabel(tr('Extrapolate from')))
        self.veer_ref = self._src_combo(self._dir_src)
        exh.addWidget(self.veer_ref)
        exh.addStretch(1)

        # Direction sensor + sectors（扇区模式共享行）
        self.sector_row_dir_w = QWidget()
        seh = QHBoxLayout(self.sector_row_dir_w)
        seh.setContentsMargins(0, 0, 0, 0)
        seh.addWidget(QLabel(tr('Direction sensor')))
        self.dir_sensor_combo = self._src_combo(self._dir_src)
        seh.addWidget(self.dir_sensor_combo)
        seh.addWidget(QLabel(tr('Direction sectors')))
        self.veer_sector_spin = QSpinBox()
        self.veer_sector_spin.setRange(1, 36)
        self.veer_sector_spin.setValue(16)
        seh.addWidget(self.veer_sector_spin)
        seh.addStretch(1)
        self.veer_sector_spin.valueChanged.connect(
            lambda _v: self._on_veer_sectors_changed())

        # 模式 1：Calculate in each time step
        p1 = QWidget()
        p1h = QHBoxLayout(p1)
        p1l = QVBoxLayout()
        p1l.addWidget(QLabel(tr('Calculate from')))
        self.src_dir = self._src_check_list(self._dir_src)
        p1l.addWidget(self.src_dir, 1)
        p1h.addLayout(p1l, 1)
        p1r = QVBoxLayout()
        self.chk_veer_restrict = QCheckBox(
            tr('Restrict wind veer rate to a range'))
        self.chk_veer_restrict.setChecked(True)
        p1r.addWidget(self.chk_veer_restrict)
        vf = QFormLayout()
        self.veer_min = QDoubleSpinBox()
        self.veer_min.setRange(-1000, 1000)
        self.veer_min.setValue(-200)
        self.veer_max = QDoubleSpinBox()
        self.veer_max.setRange(-1000, 1000)
        self.veer_max.setValue(200)
        vf.addRow(tr('Min. value (\u2191100m)'), self.veer_min)
        vf.addRow(tr('Max. value (\u2191100m)'), self.veer_max)
        p1r.addLayout(vf)
        p1r.addStretch(1)
        p1h.addLayout(p1r)

        # 模式 2：constant
        p2 = QWidget()
        p2v = QVBoxLayout(p2)
        p2v.addWidget(QLabel(tr('Enter constant wind veer rate')))
        f2 = QFormLayout()
        self.veer_const = QDoubleSpinBox()
        self.veer_const.setRange(-1000, 1000)
        self.veer_const.setDecimals(4)
        self.veer_const.setValue(self._default_veer())
        f2.addRow(tr('Constant wind veer rate (\u2191100m)'), self.veer_const)
        p2v.addLayout(f2)
        p2v.addStretch(1)

        hour_lb = [f'{h:02d}:00- {h + 1:02d}:00' for h in range(24)]
        self.tbl_veer_month = self._make_table(12, 2, 'Month', self.MONTH_LB)
        cap_m = self._wrap(self.tbl_veer_month,
                           tr('Enter wind veer rate by month'))
        self.tbl_veer_hour = self._make_table(24, 2, 'Hour', hour_lb)
        cap_h = self._wrap(self.tbl_veer_hour,
                           tr('Enter wind veer rate by hour of day'))
        self.tbl_veer_sector = self._make_table(16, 2, 'Direction Sector', None)
        cap_s = self._wrap(self.tbl_veer_sector,
                           tr('Enter wind veer rate by direction sector'))
        self.tbl_veer_mh = self._make_table(24, 13, 'Hour', self.MONTH_LB)
        cap_mh = self._wrap(self.tbl_veer_mh,
                            tr('Enter wind veer rate by month and hour of day'))
        self.tbl_veer_sm = self._make_table(16, 13, 'Direction Sector',
                                            self.MONTH_LB)
        cap_sm = self._wrap(
            self.tbl_veer_sm,
            tr('Enter wind veer rate by direction sector and month'))
        self.tbl_veer_sh = self._make_table(16, 25, 'Direction Sector', hour_lb)
        cap_sh = self._wrap(
            self.tbl_veer_sh,
            tr('Enter wind veer rate by direction sector and hour of day'))

        self.veer_stack = QStackedWidget()
        for pg in (p1, p2, cap_m, cap_h, cap_s, cap_mh, cap_sm, cap_sh):
            self.veer_stack.addWidget(pg)
        v.addWidget(self.ex_dir_row_w)
        v.addWidget(self.sector_row_dir_w)
        v.addWidget(self.veer_stack, 1)

        def _on_veer_mode(i):
            self.ex_dir_row_w.setVisible(i != 0)
            self.sector_row_dir_w.setVisible(i in (4, 6, 7))
            self.veer_stack.setCurrentIndex(i)
            if i == 4:
                self._on_veer_sectors_changed()

        self.veer_method.currentIndexChanged.connect(_on_veer_mode)
        _on_veer_mode(0)
        return w

    def _checked_dir_src(self) -> list[tuple[str, float]]:
        out = []
        for i in range(self.src_dir.count()):
            it = self.src_dir.item(i)
            if it.checkState() == Qt.Checked:
                col = it.data(Qt.UserRole)
                ch = self._ds.channels.get(col)
                if ch is not None and ch.height and col in self._ds.df.columns:
                    out.append((col, float(ch.height)))
        return out

    def _veer_step_rates(self) -> np.ndarray:
        """每个时间步的风向切变率（°/100m）。

        以最低层方向为基准，把各层方向按圆周差展开后对高度做线性拟合，
        斜率 ×100。"""
        srcs = sorted(self._checked_dir_src(), key=lambda x: x[1])
        idx = self._ds.df.index
        if len(srcs) < 2:
            return np.full(len(idx), np.nan)
        base_col, base_z = srcs[0]
        d_base = _to_num(self._ds.df[base_col]).to_numpy()
        z_rel = np.array([z for _, z in srcs]) - base_z
        D = np.column_stack([_to_num(self._ds.df[c]).to_numpy()
                             for c, _ in srcs])
        deltas = (D - d_base[:, None] + 180) % 360 - 180
        valid = np.isfinite(deltas).all(axis=1)
        m = np.where(valid, np.nanmean(deltas, axis=1), 0)
        mz = z_rel.mean()
        num = np.nansum((deltas - m[:, None]) * (z_rel - mz), axis=1)
        den = float(((z_rel - mz) ** 2).sum())
        slope = num / den if den else np.full(len(idx), np.nan)
        slope = np.asarray(slope, dtype=float)
        slope[~np.isfinite(slope)] = np.nan
        return slope * 100.0

    def _default_veer(self) -> float:
        v = self._veer_step_rates()
        v = v[np.isfinite(v)]
        return float(np.clip(np.median(v), -200, 200)) if len(v) else 3.16

    def _on_veer_sectors_changed(self):
        n = self.veer_sector_spin.value()
        for r in range(min(n, self.tbl_veer_sector.rowCount())):
            it = QTableWidgetItem(self._sector_label(r, n))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.tbl_veer_sector.setItem(r, 0, it)
        for r in range(min(n, self.tbl_veer_sm.rowCount())):
            it = QTableWidgetItem(self._sector_label(r, n))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.tbl_veer_sm.setItem(r, 0, it)
        for r in range(min(n, self.tbl_veer_sh.rowCount())):
            it = QTableWidgetItem(self._sector_label(r, n))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.tbl_veer_sh.setItem(r, 0, it)
        self._prefill_veer_tables()

    def _prefill_veer_tables(self):
        """按数据预填切变率表（每桶中位数）；只填空白格。"""
        rates = self._veer_step_rates()
        if not np.isfinite(rates).any():
            return
        idx = self._ds.df.index
        fill_1d(self.tbl_veer_month,
                [float(np.nanmedian(rates[idx.month == m]))
                 for m in range(1, 13)])
        fill_1d(self.tbl_veer_hour,
                [float(np.nanmedian(rates[idx.hour == h]))
                 for h in range(24)])
        n = self.veer_sector_spin.value()
        dcol = self.dir_sensor_combo.currentData()
        if not dcol or dcol not in self._ds.df.columns:
            return
        sec = self._sector_index(
            _to_num(self._ds.df[dcol]).to_numpy(), n)
        fill_1d(self.tbl_veer_sector,
                [float(np.nanmedian(rates[sec == i])) for i in range(n)])
        months = idx.month.values - 1
        hours = idx.hour.values
        fill_2d(self.tbl_veer_mh,
                [[float(np.nanmedian(rates[(hours == h) & (months == m)]))
                  for m in range(12)] for h in range(24)])
        fill_2d(self.tbl_veer_sm,
                [[float(np.nanmedian(rates[(sec == i) & (months == m)]))
                  for m in range(12)] for i in range(n)])
        fill_2d(self.tbl_veer_sh,
                [[float(np.nanmedian(rates[(sec == i) & (hours == h)]))
                  for h in range(24)] for i in range(n)])

    def _find_dir_sd(self, ref_col: str) -> str | None:
        """找参考风向通道的同高度 SD 列（关联优先，同高度匹配兜底）。"""
        ch = self._ds.channels.get(ref_col)
        if ch is not None and ch.sd_col and ch.sd_col in self._ds.df.columns:
            return ch.sd_col
        if ch is None:
            return None
        for c2, c in self._ds.channels.items():
            if c.kind == 'dir' and c.role == 'SD' \
                    and (c.height or -1) == (ch.height or -1) \
                    and c2 in self._ds.df.columns:
                return c2
        return None

    def _veer_lookup(self) -> np.ndarray:
        """按当前切变率模式为每个时间步生成 veer（°/100m）。"""
        idx = self._ds.df.index
        mode = self.veer_method.currentIndex()
        n = len(idx)
        if mode == 1:
            return np.full(n, self.veer_const.value())
        months = idx.month.values - 1
        hours = idx.hour.values
        if mode == 2:
            col = read_col(self.tbl_veer_month)
            return np.array([col[m] for m in months])
        if mode == 3:
            col = read_col(self.tbl_veer_hour)
            return np.array([col[h] for h in hours])
        n_sec = self.veer_sector_spin.value()
        dcol = self.dir_sensor_combo.currentData()
        dirs = _to_num(self._ds.df[dcol]).to_numpy() if dcol else None
        if dirs is None:
            return np.full(n, np.nan)
        sec = self._sector_index(dirs, n_sec)
        if mode == 4:
            col = read_col(self.tbl_veer_sector)
            return np.array([col[s] for s in sec])
        if mode == 5:
            mat = read_mat(self.tbl_veer_mh)
            return np.array([mat[hours[i], months[i]] for i in range(n)])
        if mode == 6:
            mat = read_mat(self.tbl_veer_sm)
            return np.array([mat[sec[i], months[i]] for i in range(n)])
        if mode == 7:
            mat = read_mat(self.tbl_veer_sh)
            return np.array([mat[sec[i], hours[i]] for i in range(n)])
        return np.full(n, np.nan)

    def _build_temp_tab(self) -> QWidget:
        """Temperature Tab：温度梯度（Temperature gradient，°C/100m），8 模式。"""
        w = QWidget()
        v = QVBoxLayout(w)
        top = QGridLayout()
        top.addWidget(QLabel(tr('Temperature gradient')), 0, 0)
        self.grad_method = QComboBox()
        for m in self.ALPHA_MODES:
            self.grad_method.addItem(tr(m))
        top.addWidget(self.grad_method, 0, 1)
        top.setColumnStretch(1, 1)
        v.addLayout(top)

        self.ex_temp_row_w = QWidget()
        exh = QHBoxLayout(self.ex_temp_row_w)
        exh.setContentsMargins(0, 0, 0, 0)
        exh.addWidget(QLabel(tr('Extrapolate from')))
        self.temp_ref = self._src_combo(self._temp_src)
        exh.addWidget(self.temp_ref)
        exh.addStretch(1)

        self.sector_row_temp_w = QWidget()
        seh = QHBoxLayout(self.sector_row_temp_w)
        seh.setContentsMargins(0, 0, 0, 0)
        seh.addWidget(QLabel(tr('Direction sensor')))
        self.grad_dir_combo = self._src_combo(self._dir_src)
        seh.addWidget(self.grad_dir_combo)
        seh.addWidget(QLabel(tr('Direction sectors')))
        self.grad_sector_spin = QSpinBox()
        self.grad_sector_spin.setRange(1, 36)
        self.grad_sector_spin.setValue(16)
        seh.addWidget(self.grad_sector_spin)
        seh.addStretch(1)
        self.grad_sector_spin.valueChanged.connect(
            lambda _v: self._on_grad_sectors_changed())

        # 模式 1：Calculate in each time step
        p0 = QWidget()
        p0h = QHBoxLayout(p0)
        p0l = QVBoxLayout()
        p0l.addWidget(QLabel(tr('Calculate from')))
        self.src_temp = self._src_check_list(self._temp_src)
        p0l.addWidget(self.src_temp, 1)
        p0h.addLayout(p0l, 1)
        p0r = QVBoxLayout()
        self.chk_grad_restrict = QCheckBox(
            tr('Restrict temperature gradient to a range'))
        self.chk_grad_restrict.setChecked(True)
        p0r.addWidget(self.chk_grad_restrict)
        gf = QFormLayout()
        self.grad_min = QDoubleSpinBox()
        self.grad_min.setRange(-10, 10)
        self.grad_min.setValue(-5)
        self.grad_max = QDoubleSpinBox()
        self.grad_max.setRange(-10, 10)
        self.grad_max.setValue(5)
        gf.addRow(tr('Min. value'), self.grad_min)
        gf.addRow(tr('Max. value'), self.grad_max)
        p0r.addLayout(gf)
        p0r.addStretch(1)
        p0h.addLayout(p0r)

        # 模式 2：constant（默认 -0.65 °C/100m）
        p2 = QWidget()
        p2v = QVBoxLayout(p2)
        p2v.addWidget(QLabel(tr('Enter constant temperature gradient')))
        f2 = QFormLayout()
        self.grad_const = QDoubleSpinBox()
        self.grad_const.setRange(-10, 10)
        self.grad_const.setDecimals(3)
        self.grad_const.setValue(self._default_grad())
        f2.addRow(tr('Constant temperature gradient (°C/100m)'),
                  self.grad_const)
        p2v.addLayout(f2)
        p2v.addStretch(1)

        hour_lb = [f'{h:02d}:00- {h + 1:02d}:00' for h in range(24)]
        self.tbl_grad_month = self._make_table(12, 2, 'Month', self.MONTH_LB)
        cap_m = self._wrap(self.tbl_grad_month,
                           tr('Enter temperature gradient by month'))
        self.tbl_grad_hour = self._make_table(24, 2, 'Hour', hour_lb)
        cap_h = self._wrap(self.tbl_grad_hour,
                           tr('Enter temperature gradient by hour of day'))
        self.tbl_grad_sector = self._make_table(16, 2, 'Direction Sector', None)
        cap_s = self._wrap(self.tbl_grad_sector,
                           tr('Enter temperature gradient by direction sector'))
        self.tbl_grad_mh = self._make_table(24, 13, 'Hour', self.MONTH_LB)
        cap_mh = self._wrap(self.tbl_grad_mh,
                            tr('Enter temperature gradient by month and hour of day'))
        self.tbl_grad_sm = self._make_table(16, 13, 'Direction Sector', self.MONTH_LB)
        cap_sm = self._wrap(self.tbl_grad_sm,
                            tr('Enter temperature gradient by direction sector and month'))
        self.tbl_grad_sh = self._make_table(16, 25, 'Direction Sector', hour_lb)
        cap_sh = self._wrap(self.tbl_grad_sh,
                            tr('Enter temperature gradient by hour of day and direction sector'))

        self.grad_stack = QStackedWidget()
        for pg in (p0, p2, cap_m, cap_h, cap_s, cap_mh, cap_sm, cap_sh):
            self.grad_stack.addWidget(pg)
        v.addWidget(self.ex_temp_row_w)
        v.addWidget(self.sector_row_temp_w)
        v.addWidget(self.grad_stack, 1)

        def _on_grad_mode(i):
            self.ex_temp_row_w.setVisible(i != 0)
            self.sector_row_temp_w.setVisible(i in (4, 6, 7))
            self.grad_stack.setCurrentIndex(i)
            if i in (4, 6, 7):
                self._on_grad_sectors_changed()

        self.grad_method.currentIndexChanged.connect(_on_grad_mode)
        _on_grad_mode(1)
        return w

    def _checked_temp_src(self) -> list[tuple[str, float]]:
        out = []
        for i in range(self.src_temp.count()):
            it = self.src_temp.item(i)
            if it.checkState() == Qt.Checked:
                col = it.data(Qt.UserRole)
                ch = self._ds.channels.get(col)
                if ch is not None and ch.height and col in self._ds.df.columns:
                    out.append((col, float(ch.height)))
        return out

    def _grad_step(self) -> np.ndarray:
        """每个时间步的温度梯度（°C/100m）：T 对 z 线性拟合 ×100。"""
        srcs = sorted(self._checked_temp_src(), key=lambda x: x[1])
        idx = self._ds.df.index
        if len(srcs) < 2:
            return np.full(len(idx), np.nan)
        z = np.array([h for _, h in srcs])
        mz = z.mean()
        T = np.column_stack([_to_num(self._ds.df[c]).to_numpy()
                             for c, _ in srcs])
        mT = np.nanmean(T, axis=1)
        num = np.nansum((T - mT[:, None]) * (z - mz), axis=1)
        den = float(((z - mz) ** 2).sum())
        grad = num / den * 100.0 if den else np.full(len(idx), np.nan)
        grad = np.asarray(grad, dtype=float)
        grad[~np.isfinite(grad)] = np.nan
        return grad

    def _default_grad(self) -> float:
        g = self._grad_step()
        g = g[np.isfinite(g)]
        return float(np.clip(np.median(g), -10, 10)) if len(g) else -0.65

    def _on_grad_sectors_changed(self):
        n = self.grad_sector_spin.value()
        for r in range(min(n, self.tbl_grad_sector.rowCount())):
            it = QTableWidgetItem(self._sector_label(r, n))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.tbl_grad_sector.setItem(r, 0, it)
        self._prefill_grad_tables()

    def _prefill_grad_tables(self):
        grads = self._grad_step()
        if not np.isfinite(grads).any():
            return
        idx = self._ds.df.index
        fill_1d(self.tbl_grad_month,
                [float(np.nanmedian(grads[idx.month == m]))
                 for m in range(1, 13)])
        fill_1d(self.tbl_grad_hour,
                [float(np.nanmedian(grads[idx.hour == h]))
                 for h in range(24)])
        n = self.grad_sector_spin.value()
        dcol = self.grad_dir_combo.currentData()
        if not dcol or dcol not in self._ds.df.columns:
            return
        sec = self._sector_index(
            _to_num(self._ds.df[dcol]).to_numpy(), n)
        fill_1d(self.tbl_grad_sector,
                [float(np.nanmedian(grads[sec == i])) for i in range(n)])
        months = idx.month.values - 1
        hours = idx.hour.values
        fill_2d(self.tbl_grad_mh,
                [[float(np.nanmedian(grads[(hours == h) & (months == m)]))
                  for m in range(12)] for h in range(24)])
        fill_2d(self.tbl_grad_sm,
                [[float(np.nanmedian(grads[(sec == i) & (months == m)]))
                  for m in range(12)] for i in range(n)])
        fill_2d(self.tbl_grad_sh,
                [[float(np.nanmedian(grads[(sec == i) & (hours == h)]))
                  for h in range(24)] for i in range(n)])

    def _grad_lookup(self) -> np.ndarray:
        idx = self._ds.df.index
        mode = self.grad_method.currentIndex()
        n = len(idx)
        if mode == 1:
            return np.full(n, self.grad_const.value())
        months = idx.month.values - 1
        hours = idx.hour.values
        if mode == 2:
            col = read_col(self.tbl_grad_month)
            return np.array([col[m] for m in months])
        if mode == 3:
            col = read_col(self.tbl_grad_hour)
            return np.array([col[h] for h in hours])
        n_sec = self.grad_sector_spin.value()
        dcol = self.grad_dir_combo.currentData()
        dirs = _to_num(self._ds.df[dcol]).to_numpy() if dcol else None
        if dirs is None:
            return np.full(n, np.nan)
        sec = self._sector_index(dirs, n_sec)
        if mode == 4:
            col = read_col(self.tbl_grad_sector)
            return np.array([col[s] for s in sec])
        if mode == 5:
            mat = read_mat(self.tbl_grad_mh)
            return np.array([mat[hours[i], months[i]] for i in range(n)])
        if mode == 6:
            mat = read_mat(self.tbl_grad_sm)
            return np.array([mat[sec[i], months[i]] for i in range(n)])
        if mode == 7:
            mat = read_mat(self.tbl_grad_sh)
            return np.array([mat[sec[i], hours[i]] for i in range(n)])
        return np.full(n, np.nan)

    def _auto_sd(self, zt: float, res: pd.Series, ref_col: str,
                 v_ref: pd.Series):
        """按参考高度的风速比值缩放参考 SD 列，自动生成 zt 高度 SD 列。"""
        ch = self._ds.channels.get(ref_col)
        sd_ref = None
        if ch is not None and ch.sd_col and ch.sd_col in self._ds.df.columns:
            sd_ref = ch.sd_col
        elif ch is not None:
            for c2, c in self._ds.channels.items():
                if c.kind == 'speed' and c.role == 'SD' \
                        and (c.height or -1) == (ch.height or -1) \
                        and c2 in self._ds.df.columns:
                    sd_ref = c2
                    break
        if not sd_ref:
            return
        out = build_canon_name('Speed', zt, '', 'SD')
        if out in self._ds.df.columns:
            return
        vr = v_ref.copy()
        vr[vr.abs() < 0.05] = np.nan
        self._ds.df[out] = _to_num(self._ds.df[sd_ref]) * (res / vr)
        self._ds.channels[out] = Channel(name=out, kind='speed', height=zt,
                                         units='m/s', role='SD')

    # ---------- 工具 ----------
    def _src_check_list(self, cols: list[str]) -> QListWidget:
        lst = QListWidget()
        lst.setSelectionMode(QAbstractItemView.NoSelection)
        for c in cols:
            it = QListWidgetItem(display_name(c))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, c)
            lst.addItem(it)
        return lst

    def _src_combo(self, cols: list[str]) -> QComboBox:
        combo = QComboBox()
        for c in cols:
            combo.addItem(display_name(c), c)
        return combo

    def _default_target_height(self) -> float:
        hs = [c.height for c in self._ds.channels.values()
              if c.kind == 'speed' and c.height]
        if not hs:
            return 160.0
        return max(round(max(hs) * 1.33 / 10) * 10, max(hs) + 10)

    def _checked_speed_src(self) -> list[tuple[str, float]]:
        out = []
        for i in range(self.src_speed.count()):
            it = self.src_speed.item(i)
            if it.checkState() == Qt.Checked:
                col = it.data(Qt.UserRole)
                ch = self._ds.channels.get(col)
                if ch is not None and ch.height and col in self._ds.df.columns:
                    out.append((col, float(ch.height)))
        return out

    def _step_alphas(self) -> np.ndarray:
        """每个时间步的幂律指数（对勾选源做 ln v ~ ln z 拟合，向量化）。"""
        if self._alpha_cache is not None:
            return self._alpha_cache
        srcs = self._checked_speed_src()
        idx = self._ds.df.index
        if len(srcs) < 2:
            self._alpha_cache = np.full(len(idx), np.nan)
            return self._alpha_cache
        z = np.array([h for _, h in srcs])
        lz = np.log(z)
        mz = lz.mean()
        V = np.column_stack([_to_num(self._ds.df[c]).to_numpy()
                             for c, _ in srcs])
        with np.errstate(all='ignore'):
            L = np.log(V)
        mL = np.nanmean(L, axis=1)
        num = np.nansum((L - mL[:, None]) * (lz - mz), axis=1)
        den = float(((lz - mz) ** 2).sum())
        alpha = num / den if den else np.full(len(idx), np.nan)
        alpha[~np.isfinite(alpha)] = np.nan
        self._alpha_cache = alpha
        return self._alpha_cache

    def _default_alpha(self) -> float:
        a = self._step_alphas()
        a = a[~np.isnan(a)]
        return float(np.median(a)) if len(a) else 0.14

    def _sector_index(self, dirs: np.ndarray, n: int) -> np.ndarray:
        width = 360.0 / n
        return (np.floor(((dirs + width / 2) % 360) / width)).astype(int) % n

    def _sector_label(self, i: int, n: int) -> str:
        width = 360.0 / n
        lo = (i * width - width / 2) % 360
        hi = ((i + 1) * width - width / 2) % 360
        return f'{lo:.2f}°- {hi:.2f}°'

    def _on_sectors_changed(self):
        """扇区数变化：重建扇区表行标签，空白格按数据预填。"""
        n = self.sector_spin.value()
        for tbl in (self.tbl_sector, self.tbl_sector_month,
                    self.tbl_sector_hour):
            for r in range(min(n, tbl.rowCount())):
                it = QTableWidgetItem(self._sector_label(r, n))
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                tbl.setItem(r, 0, it)
        self._prefill_sector_tables()

    def _prefill_tables(self):
        """按数据预填各指数表（每桶中位数 alpha）；只填空白格。"""
        alpha = self._step_alphas()
        if not np.isfinite(alpha).any():
            return
        idx = self._ds.df.index
        fill_1d(self.tbl_month, [float(np.nanmedian(alpha[idx.month == m]))
                                 for m in range(1, 13)])
        fill_1d(self.tbl_hour, [float(np.nanmedian(alpha[idx.hour == h]))
                                for h in range(24)])
        self._prefill_sector_tables()
        months = idx.month.values - 1
        hours = idx.hour.values
        fill_2d(self.tbl_month_hour,
                [[float(np.nanmedian(alpha[(hours == h) & (months == m)]))
                  for m in range(12)] for h in range(24)])

    def _prefill_sector_tables(self):
        alpha = self._step_alphas()
        if not np.isfinite(alpha).any():
            return
        n = self.sector_spin.value()
        idx = self._ds.df.index
        dcol = self.dir_combo.currentData()
        if not dcol or dcol not in self._ds.df.columns:
            return
        dirs = _to_num(self._ds.df[dcol]).to_numpy()
        sec = self._sector_index(dirs, n)
        months = idx.month.values - 1
        hours = idx.hour.values
        fill_1d(self.tbl_sector,
                [float(np.nanmedian(alpha[sec == i])) for i in range(n)])
        fill_2d(self.tbl_sector_month,
                [[float(np.nanmedian(alpha[(sec == i) & (months == m)]))
                  for m in range(12)] for i in range(n)])
        fill_2d(self.tbl_sector_hour,
                [[float(np.nanmedian(alpha[(sec == i) & (hours == h)]))
                  for h in range(24)] for i in range(n)])

    # ---------- 执行 ----------
    def _read_heights(self) -> list[float]:
        out = []
        for r in range(self.heights.rowCount()):
            it = self.heights.item(r, 1)
            if it and it.text().strip():
                try:
                    v = float(it.text().strip())
                    if v > 0:
                        out.append(v)
                except ValueError:
                    pass
        return out

    def _alpha_lookup(self) -> np.ndarray:
        """按当前模式为每个时间步生成 alpha 数组。"""
        idx = self._ds.df.index
        mode = self.alpha_method.currentIndex()
        n = len(idx)
        if mode == 1:
            return np.full(n, self.alpha_const.value())
        months = idx.month.values - 1
        hours = idx.hour.values
        if mode == 2:
            col = read_col(self.tbl_month)
            return np.array([col[m] for m in months])
        if mode == 3:
            col = read_col(self.tbl_hour)
            return np.array([col[h] for h in hours])
        n_sec = self.sector_spin.value()
        dcol = self.dir_combo.currentData()
        dirs = _to_num(self._ds.df[dcol]).to_numpy() if dcol else None
        if dirs is None:
            return np.full(n, np.nan)
        sec = self._sector_index(dirs, n_sec)
        if mode == 4:
            col = read_col(self.tbl_sector)
            return np.array([col[s] for s in sec])
        if mode == 5:
            mat = read_mat(self.tbl_month_hour)
            return np.array([mat[hours[i], months[i]] for i in range(n)])
        if mode == 6:
            mat = read_mat(self.tbl_sector_month)
            return np.array([mat[sec[i], months[i]] for i in range(n)])
        if mode == 7:
            mat = read_mat(self.tbl_sector_hour)
            return np.array([mat[sec[i], hours[i]] for i in range(n)])
        return np.full(n, np.nan)

    def _on_ok(self):
        ds = self._ds
        heights = self._read_heights()
        if not heights:
            QMessageBox.warning(self, tr('参数不足'),
                                tr('请至少指定一个源高度和一个目标高度'))
            return
        idx = ds.df.index
        generated = []

        # ---- Wind speed ----
        if self.chk_speed.isChecked():
            mode = self.alpha_method.currentIndex()
            if mode == 0:
                srcs = self._checked_speed_src()
                if len(srcs) < 2:
                    QMessageBox.warning(self, tr('参数不足'),
                                        tr('至少需要两层风速'))
                    return
                z = np.array([h for _, h in srcs])
                lz = np.log(z)
                mz = lz.mean()
                V = np.column_stack([_to_num(ds.df[c]).to_numpy()
                                     for c, _ in srcs])
                with np.errstate(all='ignore'):
                    L = np.log(V)
                valid = np.isfinite(L).all(axis=1)
                mL = np.where(valid, np.nanmean(L, axis=1), 0)
                num = np.nansum((L - mL[:, None]) * (lz - mz), axis=1)
                den = float(((lz - mz) ** 2).sum())
                alpha = np.where(valid, num / den if den else np.nan, np.nan)
                if self.chk_restrict.isChecked():
                    alpha = np.clip(alpha, self.alpha_min.value(),
                                    self.alpha_max.value())
                a_int = np.where(valid, mL - alpha * mz, np.nan)
                ref0, z_ref0 = srcs[0]
                v_ref0 = _to_num(ds.df[ref0])
                for zt in heights:
                    res = pd.Series(np.exp(a_int + alpha * np.log(zt)),
                                    index=idx)
                    out = build_canon_name('Speed', zt, '', 'Avg')
                    if not self._emit(out, res, 'speed', zt):
                        return
                    generated.append(out)
                    self._auto_sd(zt, res, ref0, v_ref0)
            else:
                ref = self.ref_combo.currentData()
                if not ref or ref not in ds.df.columns:
                    QMessageBox.warning(self, tr('参数不足'),
                                        tr('请至少指定一个源高度和一个目标高度'))
                    return
                z_ref = ds.channels[ref].height or 10.0
                v_ref = _to_num(ds.df[ref])
                alpha_t = self._alpha_lookup()
                for zt in heights:
                    res = v_ref * (zt / z_ref) ** alpha_t
                    out = build_canon_name('Speed', zt, '', 'Avg')
                    if not self._emit(out, res, 'speed', zt):
                        return
                    generated.append(out)
                    self._auto_sd(zt, res, ref, v_ref)

        # ---- Wind direction ----
        if self.chk_dir.isChecked():
            ref = self.veer_ref.currentData()
            if not ref or ref not in ds.df.columns:
                QMessageBox.warning(self, tr('参数不足'),
                                    tr('请勾选 Wind direction'))
                return
            z_ref = ds.channels[ref].height or 10.0
            d_ref = _to_num(ds.df[ref]).to_numpy()
            mode = self.veer_method.currentIndex()
            if mode == 0:
                rates = self._veer_step_rates()
                if self.chk_veer_restrict.isChecked():
                    rates = np.clip(rates, self.veer_min.value(),
                                    self.veer_max.value())
            else:
                rates = self._veer_lookup()
            sd_ref = self._find_dir_sd(ref)
            for zt in heights:
                d_h = (d_ref + rates * (zt - z_ref) / 100.0) % 360.0
                res = pd.Series(d_h, index=idx)
                out = build_canon_name('Dir', zt, '', 'Avg')
                if not self._emit(out, res, 'dir', zt):
                    return
                generated.append(out)
                if sd_ref:
                    sd_out = build_canon_name('Dir', zt, '', 'SD')
                    if sd_out not in ds.df.columns:
                        ds.df[sd_out] = ds.df[sd_ref]
                        ds.channels[sd_out] = Channel(
                            name=sd_out, kind='dir', height=zt, units='deg',
                            role='SD')

        # ---- Temperature ----
        if self.chk_temp.isChecked():
            ref = self.temp_ref.currentData()
            if not ref or ref not in ds.df.columns:
                QMessageBox.warning(self, tr('参数不足'),
                                    tr('请勾选 Temperature'))
                return
            z_ref = ds.channels[ref].height or 10.0
            t_ref = _to_num(ds.df[ref])
            mode = self.grad_method.currentIndex()
            if mode == 0:
                srcs = sorted(self._checked_temp_src(), key=lambda x: x[1])
                if len(srcs) < 2:
                    QMessageBox.warning(self, tr('参数不足'),
                                        tr('至少需要两层温度'))
                    return
                z = np.array([h for _, h in srcs])
                mz = z.mean()
                T = np.column_stack([_to_num(ds.df[c]).to_numpy()
                                     for c, _ in srcs])
                mT = np.nanmean(T, axis=1)
                num = np.nansum((T - mT[:, None]) * (z - mz), axis=1)
                den = float(((z - mz) ** 2).sum())
                grad = np.where(num is not None,
                                num / den * 100.0 if den else np.nan, np.nan)
                grad = np.asarray(grad, dtype=float)
                grad[~np.isfinite(grad)] = np.nan
                if self.chk_grad_restrict.isChecked():
                    grad = np.clip(grad, self.grad_min.value(),
                                   self.grad_max.value())
                b_int = np.where(np.isfinite(grad),
                                 mT - (grad / 100.0) * mz, np.nan)
                for zt in heights:
                    res = pd.Series(b_int + (grad / 100.0) * zt, index=idx)
                    out = build_canon_name('Temp', zt, '', 'Avg')
                    if not self._emit(out, res, 'temp', zt):
                        return
                    generated.append(out)
            else:
                grad_t = self._grad_lookup()
                for zt in heights:
                    res = t_ref + grad_t * (zt - z_ref) / 100.0
                    out = build_canon_name('Temp', zt, '', 'Avg')
                    if not self._emit(out, res, 'temp', zt):
                        return
                    generated.append(out)

        self._info = tr('已生成外推通道') + f' ({len(generated)})'
        self.accept()

    def _emit(self, out: str, res: pd.Series, kind: str, zt: float) -> bool:
        df = self._ds.df
        if out in df.columns:
            QMessageBox.warning(None, tr('重名'),
                                tr('输出通道「{}」已存在', out))
            return False
        units = {'speed': 'm/s', 'dir': 'deg', 'temp': '°C'}.get(kind, '')
        df[out] = res
        self._ds.channels[out] = Channel(name=out, kind=kind, height=zt,
                                         units=units, role='Avg')
        return True

    def result_info(self):
        return self._info


def fill_1d(tbl: QTableWidget, values: list[float]):
    """填充第 1 列指数；空白格才填（保留用户编辑），NaN 跳过。"""
    for r, v in enumerate(values):
        if r >= tbl.rowCount() or v is None or not np.isfinite(v):
            continue
        old = tbl.item(r, 1)
        if old is not None and old.text().strip():
            continue
        tbl.setItem(r, 1, QTableWidgetItem(f'{v:.4g}'))


def fill_2d(tbl: QTableWidget, mat: list[list[float]]):
    for r, row in enumerate(mat):
        if r >= tbl.rowCount():
            continue
        for c, v in enumerate(row):
            if c + 1 >= tbl.columnCount():
                continue
            if v is None or not np.isfinite(v):
                continue
            old = tbl.item(r, c + 1)
            if old is not None and old.text().strip():
                continue
            tbl.setItem(r, c + 1, QTableWidgetItem(f'{v:.4g}'))


def read_col(tbl: QTableWidget) -> list[float]:
    out = []
    for r in range(tbl.rowCount()):
        it = tbl.item(r, 1)
        try:
            out.append(float(it.text()) if it else np.nan)
        except (ValueError, TypeError):
            out.append(np.nan)
    return out


def read_mat(tbl: QTableWidget) -> list[list[float]]:
    out = []
    for r in range(tbl.rowCount()):
        row = []
        for c in range(1, tbl.columnCount()):
            it = tbl.item(r, c)
            try:
                row.append(float(it.text()) if it else np.nan)
            except (ValueError, TypeError):
                row.append(np.nan)
        out.append(row)
    return np.array(out, dtype=float)
