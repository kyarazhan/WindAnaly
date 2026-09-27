"""绘图引擎拆分模块（B4，装饰器感知重建）。"""
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





class ViewMixin:
    def _effective_range(self, x: bool = True):
        """返回当前 effective 范围（若未缩放则返回数据全范围）。"""
        axis = 'x' if x else 'y'
        lo_key, hi_key = f'{axis}min', f'{axis}max'
        lo = self._view[lo_key] if self._view[lo_key] is not None else self._data_bounds[lo_key]
        hi = self._view[hi_key] if self._view[hi_key] is not None else self._data_bounds[hi_key]
        return lo, hi

    def _pixel_to_data(self, px: float, py: float, rect: QRectF):
        """将绘图区像素坐标转换为数据坐标。"""
        x_lo, x_hi = self._effective_range(x=True)
        y_lo, y_hi = self._effective_range(x=False)
        dx = x_lo + (px - rect.left()) / rect.width() * (x_hi - x_lo) if rect.width() else x_lo
        dy = y_lo + (rect.bottom() - py) / rect.height() * (y_hi - y_lo) if rect.height() else y_lo
        return dx, dy

    def _data_to_pixel(self, dx: float, dy: float, rect: QRectF):
        """将数据坐标转换为绘图区像素坐标。"""
        x_lo, x_hi = self._effective_range(x=True)
        y_lo, y_hi = self._effective_range(x=False)
        if abs(x_hi - x_lo) < 1e-12:
            px = rect.left()
        else:
            px = rect.left() + rect.width() * (dx - x_lo) / (x_hi - x_lo)
        if abs(y_hi - y_lo) < 1e-12:
            py = rect.bottom()
        else:
            py = rect.bottom() - rect.height() * (dy - y_lo) / (y_hi - y_lo)
        return px, py

    def _reset_view(self):
        self._view = {'xmin': None, 'xmax': None, 'ymin': None, 'ymax': None}
        b = self._data_bounds
        self.viewChanged.emit(b['xmin'], b['xmax'], b['ymin'], b['ymax'])
        self.update()

    def x_range(self) -> tuple[float, float]:
        """返回当前 x 轴视图范围（数据坐标）。"""
        return self._effective_range(x=True)

    def x_data_range(self) -> tuple[float, float]:
        """返回 x 轴数据全范围。"""
        return self._data_bounds['xmin'], self._data_bounds['xmax']

    def set_x_range(self, xmin: float, xmax: float):
        """仅设置 x 轴范围，y 轴保持当前。"""
        y_lo, y_hi = self._effective_range(x=False)
        self._set_view(xmin, xmax, y_lo, y_hi)

    def _fit_view(self):
        self._reset_view()

    def _zoom_in(self):
        self._zoom_center(1.25)

    def _zoom_out(self):
        self._zoom_center(0.8)

    def _zoom_center(self, factor: float):
        left, right, top, bottom = self._plot_margins()
        rect = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        self._zoom_at(rect.center().x(), rect.center().y(), factor)

    def _zoom_at(self, px: float, py: float, factor: float):
        """以像素点 (px,py) 为中心缩放 factor 倍（factor>1 放大）。"""
        left, right, top, bottom = self._plot_margins()
        rect = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        if not rect.contains(px, py):
            px, py = rect.center().x(), rect.center().y()
        dx, dy = self._pixel_to_data(px, py, rect)
        x_lo, x_hi = self._effective_range(x=True)
        y_lo, y_hi = self._effective_range(x=False)
        b = self._data_bounds
        # 缩小到超过全范围时直接复位，X/Y 一起回到初始状态，避免残留空白
        if factor < 1 and (x_hi - x_lo) / factor >= (b['xmax'] - b['xmin']) * 0.999:
            self._reset_view()
            return
        new_xlo = dx - (dx - x_lo) / factor
        new_xhi = dx + (x_hi - dx) / factor
        new_ylo = dy - (dy - y_lo) / factor
        new_yhi = dy + (y_hi - dy) / factor
        self._set_view(new_xlo, new_xhi, new_ylo, new_yhi)

    @staticmethod
    def _clamp_window(lo, hi, b_lo, b_hi):
        """把 [lo,hi] 平移式钳进 [b_lo,b_hi]，保持窗口跨度不被压缩。"""
        span = hi - lo
        b_span = b_hi - b_lo
        if span >= b_span or span <= 0:
            return b_lo, b_hi
        if lo < b_lo:
            lo, hi = b_lo, b_lo + span
        if hi > b_hi:
            hi, lo = b_hi, b_hi - span
        return lo, hi

    def _set_view(self, xmin: float, xmax: float, ymin: float, ymax: float):
        """设置视图范围，并限制在数据边界内（贴边时整体平移，跨度不变）。"""
        b = self._data_bounds
        xmin, xmax = self._clamp_window(xmin, xmax, b['xmin'], b['xmax'])
        ymin, ymax = self._clamp_window(ymin, ymax, b['ymin'], b['ymax'])
        if xmax - xmin < 1e-9:
            xmax = xmin + 1e-9
        if ymax - ymin < 1e-9:
            ymax = ymin + 1e-9
        self._view = {'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax}
        self.viewChanged.emit(xmin, xmax, ymin, ymax)
        self.update()

    def wheelEvent(self, event):
        if self._kind not in ('line', 'lines', 'scatter'):
            return super().wheelEvent(event)
        left, right, top, bottom = self._plot_margins()
        rect = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        pos = event.position()
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self._zoom_at(pos.x(), pos.y(), factor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._kind in ('line', 'lines', 'scatter'):
            left, right, top, bottom = self._plot_margins()
            rect = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
            if rect.contains(event.position()):
                self._panning = True
                self._pan_anchor = event.position()
                self._pan_view0 = dict(self._view)
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_anchor is not None:
            pos = event.position()
            dx_px = pos.x() - self._pan_anchor.x()
            dy_px = pos.y() - self._pan_anchor.y()
            left, right, top, bottom = self._plot_margins()
            rect = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
            x_lo, x_hi = self._effective_range(x=True)
            y_lo, y_hi = self._effective_range(x=False)
            dx_data = -dx_px / rect.width() * (x_hi - x_lo) if rect.width() else 0
            dy_data = dy_px / rect.height() * (y_hi - y_lo) if rect.height() else 0
            v0 = self._pan_view0 or {}
            xlo = (v0.get('xmin') if v0.get('xmin') is not None else self._data_bounds['xmin']) + dx_data
            xhi = (v0.get('xmax') if v0.get('xmax') is not None else self._data_bounds['xmax']) + dx_data
            ylo = (v0.get('ymin') if v0.get('ymin') is not None else self._data_bounds['ymin']) + dy_data
            yhi = (v0.get('ymax') if v0.get('ymax') is not None else self._data_bounds['ymax']) + dy_data
            self._set_view(xlo, xhi, ylo, yhi)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            self._pan_anchor = None
            self._pan_view0 = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._kind in ('line', 'lines', 'scatter'):
            self._reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction(QAction('Fit / Reset view', self, triggered=self._reset_view))
        menu.addAction(QAction(tr('Properties...'), self, triggered=self._show_properties))
        menu.addSeparator()
        menu.addAction(QAction(tr('Copy Bitmap'), self, triggered=self._copy_bitmap))
        menu.addAction(QAction(tr('Export Image...'), self, triggered=self._export_image))
        menu.addAction(QAction(tr('Export Data...'), self, triggered=self._export_data))
        menu.exec(self.mapToGlobal(pos))
