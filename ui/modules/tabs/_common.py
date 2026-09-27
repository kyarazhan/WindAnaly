"""各 Tab 共享的助手、常量与 AnalysisTab 基类（S2 拆分聚集）。"""
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


def ts_ordinals(index) -> np.ndarray:
    """DatetimeIndex → 带小数的 ordinal（秒级分辨率），全向量化。

    旧实现用 ``index.map(pd.Timestamp.toordinal)``，5 万点约 84 ms/通道，
    是时间序列页卡顿的主因；这里降到约 1 ms。
    """
    try:
        secs = np.asarray(index).astype('datetime64[s]').astype('int64')
    except (TypeError, ValueError):
        return np.asarray([pd.Timestamp(v).toordinal() for v in index],
                          dtype=float)
    return secs / 86400.0 + _EPOCH_ORDINAL


# 通道规范名 → 中文显示名映射
_KIND_CN = {
    'Speed': '风速', 'Dir': '风向', 'Temp': '气温', 'Pres': '气压',
    'RH': '相对湿度', 'other': '其它',
}
_STAT_CN = {
    'Avg': '均值', 'SD': '标准差', 'Min': '最小', 'Max': '最大', 'Gust': '阵风',
}
_ORIENT_CN = {
    'NE': '东北', 'NW': '西北', 'SE': '东南', 'SW': '西南',
    'N': '北', 'E': '东', 'S': '南', 'W': '西',
}


def display_name(name: str) -> str:
    """通道/列名保持英文规范名，不转中文，便于外部软件识别。"""
    return name


def actual_name(display: str) -> str:
    """与 display_name 对偶；现 display 已为规范名，直接返回。"""
    return display


class AnalysisTab(QWidget):
    """分析 Tab 基类：提供统一的项目注入和常用控件创建方法。"""

    def __init__(self):
        super().__init__()
        self.project: Project | None = None
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(10)

    def set_project(self, project: Project):
        self.project = project
        self.refresh()

    def refresh(self):
        """子类实现：project 数据或选择变化时重绘。"""

    def active_dataset(self) -> Dataset | None:
        if self.project is None:
            return None
        return self.project.active_dataset

    def channel_names(self, kind: str | None = None) -> list[str]:
        ds = self.active_dataset()
        if ds is None:
            return []
        if kind is None:
            return list(ds.channels.keys())
        return [c.name for c in ds.channels.values() if c.kind == kind]

    def series(self, name: str) -> pd.Series:
        ds = self.active_dataset()
        if ds is None or name not in ds.df.columns:
            return pd.Series(dtype=float)
        s = ds.df[name].astype(float)
        if not isinstance(s.index, pd.DatetimeIndex):
            idx = pd.to_datetime(ds.df.index, errors='coerce')
            s.index = idx
        return s

    def _keep_mask(self, ds: Dataset | None) -> pd.Series | None:
        """根据「标记/未标记」勾选返回保留行掩码；无标记或全选时返回 None。

        约定：cb_unflagged（未标记数据）默认勾选 → 默认显示未剔除行；
        cb_flag（标记）勾选 → 仅显示被剔除行；两者同勾/同不勾 → 全部。"""
        if ds is None or not ds.flags.any():
            return None
        f = getattr(self, 'cb_flag', None)
        u = getattr(self, 'cb_unflagged', None)
        show_flag = bool(f.isChecked()) if f is not None else False
        show_unflag = bool(u.isChecked()) if u is not None else True
        if show_flag and not show_unflag:
            return ds.flags
        if show_unflag and not show_flag:
            return ~ds.flags
        return None

    def build_group(self, title: str) -> QGroupBox:
        g = QGroupBox(title)
        # margin-top 为标题留出空间，padding-top 让内容从标题下方开始，避免重叠
        g.setStyleSheet(
            'QGroupBox { font-weight: bold; margin-top: 10px; padding-top: 8px; }'
            'QGroupBox::title { subcontrol-origin: margin; left: 6px; padding: 0 3px; }'
        )
        return g

    def add_row(self, layout, label: str, widget: QWidget):
        h = QHBoxLayout()
        h.setSpacing(6)
        h.addWidget(QLabel(label))
        h.addWidget(widget, 1)
        layout.addLayout(h)

    def make_checkbox_list(self, names: list[str], vertical: bool = True):
        """创建一组 QCheckBox；界面显示中文，内部保留规范名。"""
        container = QWidget()
        if vertical:
            lay = QVBoxLayout(container)
        else:
            lay = QHBoxLayout(container)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        boxes = {}
        for n in names:
            cb = QCheckBox(display_name(n))
            cb.setProperty('actual_name', n)
            boxes[n] = cb
            lay.addWidget(cb)
        lay.addStretch(1)
        return container, boxes
