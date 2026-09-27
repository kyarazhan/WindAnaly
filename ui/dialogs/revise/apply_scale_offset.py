"""apply_scale_offset.py：见 _common 与 shim。"""
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

from ._common import (_all_cols, _numeric_cols, _to_num, _CheckList, _DateTimeRow)

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
