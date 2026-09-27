"""分析 Tab 实现（拆分自 analysis_tabs，S2）。"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractSpinBox,QCheckBox, QComboBox, QDoubleSpinBox,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton,
                               QScrollArea, QScrollBar, QSizePolicy, QSpinBox,
                               QSplitter, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout,
                               QWidget)

from core.dataset import (KIND_DIR, KIND_PRES, KIND_RH, KIND_SPEED,
                                  KIND_SPEED_SD, KIND_TEMP, Dataset)
from core.project import Project
from ui.modules.diurnal_widget import DiurnalWidget
from ui.modules.histogram_widget import HistogramWidget
from ui.modules.plot import PlotCanvas, _EPOCH_ORDINAL
from ui.modules.scatter_widget import ScatterWidget
from ui.modules.tables_widget import TablesWidget
from ui.modules.wind_rose_widget import WindRoseWidget
from core.i18n import tr

from ._common import (AnalysisTab)

class WindRoseTab(AnalysisTab):
    """独立风玫瑰 Tab：完整控制栏（Display/Versus/Sectors/Data/Format/属性）。"""

    def __init__(self):
        super().__init__()
        self.c_rose = WindRoseWidget(show_toolbar=True)
        self._layout.addWidget(self.c_rose, 1)

    def set_project(self, project: Project):
        self.project = project
        self.c_rose.set_project(project)

    def refresh(self):
        # 数据可能在 Tab 创建后才载入（如先打开 WindAnaly 再通过菜单载入），
        # 切换/刷新时重新注入 project，让 WindRoseWidget 获取当前 active_dataset 并重绘。
        if self.project is not None:
            self.c_rose.set_project(self.project)


# ---------------------------------------------------------------------------
# 4) Diurnal Profile
# ---------------------------------------------------------------------------
class DiurnalTab(AnalysisTab):
    """独立日变化廓线 Tab：完整控制面板（Data column/Display/Format/Filter by）。"""

    def __init__(self):
        super().__init__()
        self.c_diurnal = DiurnalWidget()
        self._layout.addWidget(self.c_diurnal, 1)

    def set_project(self, project: Project):
        self.project = project
        self.c_diurnal.set_project(project)

    def refresh(self):
        # 数据可能在 Tab 创建后才载入；切换/刷新时重新注入 project
        if self.project is not None:
            self.c_diurnal.set_project(self.project)


# ---------------------------------------------------------------------------
# 5) Histogram
# ---------------------------------------------------------------------------
class HistogramTab(AnalysisTab):
    """独立频率分布 Tab：Display/Versus/Primary bins/Filter by 完整控制面板。"""

    def __init__(self):
        super().__init__()
        self.c_hist = HistogramWidget()
        self._layout.addWidget(self.c_hist, 1)

    def set_project(self, project: Project):
        self.project = project
        self.c_hist.set_project(project)

    def refresh(self):
        # 数据可能在 Tab 创建后才载入；切换/刷新时重新注入 project
        if self.project is not None:
            self.c_hist.set_project(self.project)


# ---------------------------------------------------------------------------
# 6) Scatter Plot
# ---------------------------------------------------------------------------
class ScatterTab(AnalysisTab):
    """独立散点图 Tab：Plot/versus/Color code by/Filter by/Results 完整面板。"""

    def __init__(self):
        super().__init__()
        self.c_scatter = ScatterWidget()
        self._layout.addWidget(self.c_scatter, 1)

    def set_project(self, project: Project):
        self.project = project
        self.c_scatter.set_project(project)

    def refresh(self):
        # 数据可能在 Tab 创建后才载入；切换/刷新时重新注入 project
        if self.project is not None:
            self.c_scatter.set_project(self.project)


# ---------------------------------------------------------------------------
# 7) Tables
# ---------------------------------------------------------------------------
class TablesTab(AnalysisTab):
    """独立统计表格 Tab：25 种表型 + Settings/Filter by + Export Table。"""

    def __init__(self):
        super().__init__()
        self.c_tables = TablesWidget()
        self._layout.addWidget(self.c_tables, 1)

    def set_project(self, project: Project):
        self.project = project
        self.c_tables.set_project(project)

    def refresh(self):
        # 数据可能在 Tab 创建后才载入；切换/刷新时重新注入 project
        if self.project is not None:
            self.c_tables.set_project(self.project)
