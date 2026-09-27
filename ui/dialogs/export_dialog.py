"""Export Data 对话框：支持多种风资源软件格式导出。

布局参考 Windographer 4.0.28 Export Data 对话框：紧凑三栏，底部文件预览。
各格式选项卡实现位于 ui/dialogs/export/ 包（B3 拆分）。
"""
from __future__ import annotations

import math
import os
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QRadioButton, QSizePolicy, QSpinBox, QStackedWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QDoubleSpinBox,
)

from core.dataset import KIND_DIR, KIND_SPEED, Dataset
from core.i18n import tr
from ui.dialogs.compare_dialogs import (
    _col_disp, _dir_cols, _height_of, _numeric_cols, _speed_cols,
)
from ui.dialogs.export.time_series import _TimeSeriesTab
from ui.dialogs.export.wasp import _WasPTab
from ui.dialogs.export.windsim import _WindSimTab
from ui.dialogs.export.meteodyn import _MeteodynWTTab
from ui.dialogs.export.openwind import _OpenwindTab
from ui.dialogs.export.windfarmer import _WindFarmerTab
from ui.dialogs.export.epe import _EPETab
from ui.dialogs.export.mgm import _MGMTab
from ui.dialogs.export.sam import _SAMTab
from ui.dialogs.export.xml_meta import _XMLMetadataTab


class ExportDataDialog(QDialog):
    """导出数据主对话框。"""

    _TABS = [
        ('Time Series', _TimeSeriesTab),
        ('WAsP .tab', _WasPTab),
        ('WindSim', _WindSimTab),
        ('Meteodyn WT', _MeteodynWTTab),
        ('Openwind', _OpenwindTab),
        ('WindFarmer', _WindFarmerTab),
        ('EPE', _EPETab),
        ('MGM', _MGMTab),
        ('SAM', _SAMTab),
        ('XML Metadata', _XMLMetadataTab),
    ]

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.setWindowTitle(tr('Export Data'))
        self.resize(1000, 700)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self.tabs = QTabWidget()
        self._tab_widgets = []
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont('Consolas', 9))
        for title, cls in self._TABS:
            w = cls(self.ds, self.preview)
            self.tabs.addTab(w, title)
            self._tab_widgets.append(w)
        lay.addWidget(self.tabs, stretch=3)
        # 单一共享预览面板（位于主对话框底部，随活动选项卡刷新）
        # 关键点：预览 QTextEdit 只在此处加入布局一次，避免被各选项卡
        # 的 addWidget 反复 reparent 到最后创建的选项卡中导致可见页空白。
        g_preview = QGroupBox(tr('File preview'))
        v_preview = QVBoxLayout(g_preview)
        v_preview.setContentsMargins(4, 4, 4, 4)
        v_preview.addWidget(self.preview)
        lay.addWidget(g_preview, stretch=2)
        self.btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Save)
        self.btns.button(QDialogButtonBox.StandardButton.Save).setText(tr('Export...'))
        self.btns.rejected.connect(self.reject)
        self.btns.accepted.connect(self._export_current)
        lay.addWidget(self.btns)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(0)

    def _on_tab_changed(self, idx: int):
        w = self._tab_widgets[idx]
        if hasattr(w, '_update_preview'):
            w._update_preview()

    def _export_current(self):
        w = self._tab_widgets[self.tabs.currentIndex()]
        if not w.do_export(self):
            return
        self.accept()