"""delete_data.py：见 _common 与 shim。"""
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

from ._common import (_all_cols, _CheckList, _DateTimeRow)

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
