"""绘图引擎共享常量与工具（调色板/色带/时间轴/LOD 抽稀）。"""
from __future__ import annotations
"""PlotCanvas：QPainter 自绘图表控件（零新增依赖）。

支持：plot_line / plot_bar / plot_scatter / plot_polar(风玫瑰) / plot_table
      / plot_heatmap(数据覆盖·DMap) / plot_box(箱线图)。
布局采用 "10% padding" 原则：
  - X 轴标签在下 8%，Y 轴在左 8%，标题在上 5%。
  - 实际绘图区 = rect 剩余内部。
颜色遵循中文工程报告习惯：风速蓝、风向绿、温度橙、气压紫、湿度青。
"""


import math
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetrics, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPushButton,
                               QSizePolicy, QSpinBox, QTabWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from core.i18n import tr




PALETTE = [
    QColor('#2c7be5'),  # 蓝
    QColor('#27ae60'),  # 绿
    QColor('#f39c12'),  # 橙
    QColor('#9b59b6'),  # 紫
    QColor('#17a2b8'),  # 青
    QColor('#e74c3c'),  # 红
    QColor('#6c757d'),  # 灰
]

# 热力图色带（自低到高的插值节点）
CMAPS = {
    # 蓝白：数据覆盖/单调量
    'blue': ['#f4f8fd', '#9ec6f0', '#2c7be5', '#12457f'],
    # 风速色带：深蓝→青→绿→黄→红（工程报告常见）
    'wind': ['#26418f', '#2c7be5', '#17a2b8', '#27ae60',
             '#f1c40f', '#f39c12', '#e74c3c'],
    # 有效率：红(差)→黄→绿(好)
    'coverage': ['#e74c3c', '#f39c12', '#f7dc6f', '#27ae60'],
}


# 1970-01-01 的 Python proleptic Gregorian ordinal
_EPOCH_ORDINAL = 719163


def _coerce_x_axis(x):
    """将 datetime64 / datetime / Timestamp 的 x 轴统一转为 ordinal 数值。

    返回 (x_numeric, auto_fmt)：
      - x_numeric：ordinal 整数数组（与 _draw_axes 的 xtick_fmt='date'
        用 datetime.fromordinal 还原一致）；非日期则为原数组。
      - auto_fmt：检测到日期时为 'date'，否则为 None。
    调用方可用 ``xtick_fmt = xtick_fmt or auto_fmt`` 自动启用日期轴。
    y 轴始终为数值，不受影响。
    """
    arr = np.asarray(x)
    # datetime64[*]（含 DatetimeIndex 经 np.asarray 后）
    # 用秒级分辨率换算为「带小数的 ordinal」，保留日内分辨率，
    # 这样时间序列可放大到 1 天以内；刻度标签取 int(t) 还原日期，不受影响。
    if arr.dtype.kind == 'M':
        secs = arr.astype('datetime64[s]').astype('int64')
        ordinals = secs / 86400.0 + _EPOCH_ORDINAL
        ordinals = ordinals.astype(float)
        try:
            ordinals[np.isnat(arr)] = np.nan
        except TypeError:
            pass
        return ordinals, 'date'
    # object 数组内含 datetime.datetime / pd.Timestamp
    if arr.dtype.kind == 'O' and arr.size:
        sample = arr.ravel()[0]
        if isinstance(sample, (datetime, pd.Timestamp)):
            out = []
            for v in arr.ravel():
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    out.append(np.nan)
                else:
                    ts = pd.Timestamp(v)
                    frac = (ts.hour * 3600 + ts.minute * 60 + ts.second) / 86400.0
                    out.append(ts.toordinal() + frac)
            return np.array(out, dtype=float), 'date'
    return arr, None


def _decimate_xy(x, y, nbins):
    """按像素列做 min/max 包络抽稀（LOD），保证视觉峰值不丢失。

    x 需为升序且已剔除 NaN；每列输出 (x, ymin) 与 (x, ymax) 两个点，
    点数 ≤ 2*nbins。用于 5 万点级时间序列的快速重绘。
    """
    n = x.size
    if nbins < 2 or n <= nbins * 2:
        return x, y
    x0 = float(x[0])
    x1 = float(x[-1])
    if not (x1 > x0) or not (np.isfinite(x0) and np.isfinite(x1)):
        return x, y
    idx = ((x - x0) * (nbins - 1) / (x1 - x0)).astype(np.int64)
    np.clip(idx, 0, nbins - 1, out=idx)
    starts = np.searchsorted(idx, np.arange(nbins), side='left')
    counts = np.diff(np.append(starts, n))
    keep = counts > 0
    seg = starts[keep]
    if seg.size == 0:
        return x, y
    ymin = np.minimum.reduceat(y, seg)
    ymax = np.maximum.reduceat(y, seg)
    bin_x = x0 + (x1 - x0) * np.arange(nbins)[keep] / (nbins - 1)
    out_x = np.empty(2 * bin_x.size)
    out_y = np.empty(2 * bin_x.size)
    out_x[0::2] = bin_x
    out_x[1::2] = bin_x
    out_y[0::2] = ymin
    out_y[1::2] = ymax
    return out_x, out_y


def _root_base(a: np.ndarray) -> np.ndarray:
    """回溯到 ndarray 的根底数组，用于 LOD 缓存的稳定身份标识。"""
    seen = 0
    while a.base is not None and seen < 8:
        a = a.base
        seen += 1
    return a
