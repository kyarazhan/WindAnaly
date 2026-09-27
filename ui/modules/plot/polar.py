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



from ._common import (PALETTE)


class PolarPlotMixin:
    def _draw_polar(self, p: QPainter, rect: QRectF):
        data = self._data or {}
        sectors_param = data.get('sectors', 16)
        freq = np.asarray(data.get('freq', []), dtype=float)
        labels = data.get('labels')
        calm = data.get('calm', 0.0)
        display_type = data.get('display_type', 'frequency')
        unit = data.get('unit', '%')
        styles = data.get('styles') or []
        radial_max = data.get('radial_max')
        radial_min = data.get('radial_min', 0.0)
        inner_circle_pct = data.get('inner_circle_pct', 0.0)
        fill_factor = data.get('fill_factor', 0.85)
        show_legend = data.get('show_legend', True)
        default_line_style = data.get('line_style', 'solid')
        default_marker = data.get('marker')
        center_deg = data.get('center_deg')

        is_scatter = display_type == 'scatter_plot'

        # 扇区数 & 中心角
        if (hasattr(sectors_param, '__len__') and not isinstance(sectors_param, str)
                and not is_scatter):
            center_deg = np.asarray(sectors_param, dtype=float)
            n = len(center_deg)
        else:
            n = int(sectors_param)
            if center_deg is None or len(center_deg) != n:
                center_deg = np.arange(n) * (360.0 / n) + 180.0 / n

        # scatter_plot：freq 是 (N,2) 的 [dir, value]
        if is_scatter:
            self._draw_polar_scatter(p, rect, freq, calm, unit,
                                     radial_max, radial_min, inner_circle_pct,
                                     styles, n, center_deg)
            return

        # freq 统一成 (n, k)
        if freq.ndim == 2:
            k = freq.shape[1]
            freq2 = freq
        else:
            k = 1
            freq2 = freq.reshape(-1, 1)
        if freq2.shape[0] != n:
            n = freq2.shape[0]
            center_deg = np.arange(n) * (360.0 / n) + 180.0 / n

        k = max(k, 1)
        labels = [str(labels[i]) if labels and i < len(labels) else f'Series {i+1}'
                  for i in range(k)]

        # 补齐 styles 到 k 个
        while len(styles) < k:
            styles.append({})

        # 径向范围
        finite_vals = freq2[np.isfinite(freq2)]
        data_max = float(finite_vals.max()) if finite_vals.size else 0.0
        data_min = float(finite_vals.min()) if finite_vals.size else 0.0
        if radial_max is None:
            _, max_r, _ = self._nice_limits(0, max(data_max, 1.0), pad=0.05)
        else:
            max_r = float(radial_max)
        if max_r <= 0:
            max_r = 1.0
        min_r = float(radial_min)

        cx = rect.left() + rect.width() / 2
        cy = rect.top() + rect.height() / 2
        max_radius = min(rect.width(), rect.height()) / 2 - 34
        radius = max(20, max_radius * fill_factor)

        # 同心圆网格 + 径向刻度
        p.setFont(QFont('Microsoft YaHei', 7))
        for i in range(1, 6):
            r = radius * i / 5
            p.setPen(QPen(QColor('#d5dbe2'), 0.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)
            val = min_r + (max_r - min_r) * i / 5
            txt = self._fmt_rose_tick(val, unit)
            p.setPen(QColor('#8c96a5'))
            p.drawText(QRectF(cx + 3, cy - r - 8, 54, 12),
                       Qt.AlignLeft | Qt.AlignVCenter, txt)

        # 径向线 + 角度标注（用扇区边界角，与 Windographer 一致）
        sector_width = 360.0 / n
        p.setPen(QColor('#cdd4dc'))
        for i in range(n):
            ang_deg = i * sector_width
            ang = math.radians(90 - ang_deg)
            px = cx + radius * math.cos(ang)
            py = cy - radius * math.sin(ang)
            p.drawLine(int(cx), int(cy), int(px), int(py))
        p.setPen(QColor('#4a5460'))
        p.setFont(QFont('Microsoft YaHei', 8))
        for i in range(n):
            ang_deg = i * sector_width
            ang = math.radians(90 - ang_deg)
            px = cx + (radius + 14) * math.cos(ang)
            py = cy - (radius + 14) * math.sin(ang)
            txt = f'{ang_deg:.0f}°'
            is_main = abs(ang_deg % 90) < 1e-6
            if is_main:
                p.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
            p.drawText(QRectF(px - 18, py - 8, 36, 16), Qt.AlignCenter, txt)
            if is_main:
                p.setFont(QFont('Microsoft YaHei', 8))

        # 内圆（静风）
        if calm > 0 or inner_circle_pct > 0:
            cr = radius * inner_circle_pct / 100.0
            if cr < 2 and calm > 0:
                cr = radius * min(calm / max_r, 1.0) * 0.85 + 4
            if cr >= 2:
                p.setBrush(QColor(231, 76, 60, 90))
                p.setPen(QPen(QColor('#e74c3c'), 0.8))
                p.drawEllipse(QPointF(cx, cy), cr, cr)
                p.setPen(QColor('#e74c3c'))
                p.setFont(QFont('Microsoft YaHei', 7))
                p.drawText(QRectF(cx - 24, cy + cr + 1, 48, 12),
                           Qt.AlignCenter, f'{calm:.1f}%')

        # 画各系列
        for j in range(k):
            st = styles[j]
            if st.get('visible', True) is False:
                continue
            color = self._parse_color(st.get('color'), PALETTE[j % len(PALETTE)])
            rose_style = st.get('rose_style', 'filled_line')
            lw = max(0.5, float(st.get('line_width', 1.6)))
            ls = self._qt_pen_style(st.get('line_style', default_line_style))
            marker = st.get('marker', default_marker)
            marker_size = float(st.get('marker_size', 4))
            alpha = int(st.get('fill_alpha', 45))

            pts = []
            for i in range(n):
                ang = math.radians(90 - center_deg[i])
                v = freq2[i, j]
                r = 0.0 if not math.isfinite(v) else radius * (v - min_r) / (max_r - min_r)
                r = max(0.0, min(r, radius))
                pts.append((ang, r, v))

            if rose_style in ('filled', 'filled_line'):
                poly = [QPointF(cx + r * math.cos(ang),
                                cy - r * math.sin(ang))
                        for ang, r, _ in pts]
                if poly:
                    poly.append(poly[0])
                    pen = QPen(color, lw) if rose_style == 'filled_line' else QPen(Qt.NoPen)
                    pen.setStyle(ls)
                    p.setPen(pen)
                    p.setBrush(QColor(color.red(), color.green(), color.blue(), alpha))
                    p.drawPolygon(poly)
            elif rose_style == 'line':
                poly = [QPointF(cx + r * math.cos(ang),
                                cy - r * math.sin(ang))
                        for ang, r, _ in pts]
                if poly:
                    poly.append(poly[0])
                    pen = QPen(color, lw)
                    pen.setStyle(ls)
                    p.setPen(pen)
                    p.setBrush(Qt.NoBrush)
                    p.drawPolygon(poly)
            elif rose_style == 'bar':
                pen = QPen(color, lw)
                pen.setStyle(ls)
                p.setPen(pen)
                p.setBrush(QColor(color.red(), color.green(), color.blue(), alpha))
                half = math.pi / n
                for ang, r, _ in pts:
                    path = QPainterPath()
                    path.moveTo(cx, cy)
                    path.arcTo(cx - r, cy - r, r * 2, r * 2,
                               math.degrees(ang - half) - 90,
                               math.degrees(half * 2))
                    path.closeSubpath()
                    p.drawPath(path)

            if marker:
                self._draw_markers(p, cx, cy, pts, marker, marker_size, color)

        # 图例
        if show_legend and labels:
            legend_items = [labels[j] for j in range(k)
                            if styles[j].get('visible', True) is not False
                            and styles[j].get('show_in_legend', True) is not False]
            if legend_items:
                self._draw_legend(p, rect, legend_items)

    def _draw_polar_scatter(self, p, rect, pts_data, calm, unit,
                            radial_max, radial_min, inner_circle_pct,
                            styles, n, center_deg):
        """scatter_plot：极坐标散点（direction vs value）。"""
        if pts_data.ndim != 2 or pts_data.shape[1] != 2:
            self._draw_empty(p, self.width(), self.height())
            return
        dirs = pts_data[:, 0]
        vals = pts_data[:, 1]
        valid = np.isfinite(dirs) & np.isfinite(vals) & (dirs >= 0) & (dirs < 360)
        dirs = dirs[valid]
        vals = vals[valid]
        if len(dirs) == 0:
            self._draw_empty(p, self.width(), self.height())
            return

        data_max = float(vals.max())
        data_min = float(vals.min())
        if radial_max is None:
            _, max_r, _ = self._nice_limits(0, max(data_max, 1.0), pad=0.05)
        else:
            max_r = float(radial_max)
        min_r = float(radial_min)

        cx = rect.left() + rect.width() / 2
        cy = rect.top() + rect.height() / 2
        max_radius = min(rect.width(), rect.height()) / 2 - 34
        radius = max(20, max_radius * 0.85)

        # 网格
        p.setFont(QFont('Microsoft YaHei', 7))
        for i in range(1, 6):
            r = radius * i / 5
            p.setPen(QPen(QColor('#d5dbe2'), 0.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)
            val = min_r + (max_r - min_r) * i / 5
            p.setPen(QColor('#8c96a5'))
            p.drawText(QRectF(cx + 3, cy - r - 8, 54, 12),
                       Qt.AlignLeft | Qt.AlignVCenter, self._fmt_rose_tick(val, unit))

        # 径向线 + 角度标注（用扇区边界角，与 Windographer 一致）
        sector_width = 360.0 / n
        p.setPen(QColor('#cdd4dc'))
        for i in range(n):
            ang_deg = i * sector_width
            ang = math.radians(90 - ang_deg)
            px = cx + radius * math.cos(ang)
            py = cy - radius * math.sin(ang)
            p.drawLine(int(cx), int(cy), int(px), int(py))
        p.setPen(QColor('#4a5460'))
        p.setFont(QFont('Microsoft YaHei', 8))
        for i in range(n):
            ang_deg = i * sector_width
            ang = math.radians(90 - ang_deg)
            px = cx + (radius + 14) * math.cos(ang)
            py = cy - (radius + 14) * math.sin(ang)
            txt = f'{ang_deg:.0f}°'
            is_main = abs(ang_deg % 90) < 1e-6
            if is_main:
                p.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
            p.drawText(QRectF(px - 18, py - 8, 36, 16), Qt.AlignCenter, txt)
            if is_main:
                p.setFont(QFont('Microsoft YaHei', 8))

        if calm > 0 or inner_circle_pct > 0:
            cr = radius * inner_circle_pct / 100.0
            if cr < 2 and calm > 0:
                cr = radius * min(calm / max_r, 1.0) * 0.85 + 4
            if cr >= 2:
                p.setBrush(QColor(231, 76, 60, 90))
                p.setPen(QPen(QColor('#e74c3c'), 0.8))
                p.drawEllipse(QPointF(cx, cy), cr, cr)

        # 散点
        st = styles[0] if styles else {}
        color = self._parse_color(st.get('color'), PALETTE[0])
        marker = st.get('marker') or 'circle'
        marker_size = float(st.get('marker_size', 3))
        p.setPen(QPen(color, 1))
        p.setBrush(color)
        rads = np.radians(90 - dirs)
        rr = np.clip((vals - min_r) / (max_r - min_r), 0, 1) * radius
        px = cx + rr * np.cos(rads)
        py = cy - rr * np.sin(rads)
        self._draw_marker_points(p, px, py, marker, marker_size, color)

    @staticmethod
    def _fmt_rose_tick(v: float, unit: str) -> str:
        if abs(v) >= 100:
            return f'{v:.0f}{unit}'
        if abs(v) >= 10:
            return f'{v:.1f}{unit}'.rstrip('0').rstrip('.') + unit
        return f'{v:.2f}{unit}'.rstrip('0').rstrip('.') + unit
