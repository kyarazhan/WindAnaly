"""PlotCanvas 门面：状态、公共 API 与绘制分发（B4 拆分）。"""
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



from ._common import (_coerce_x_axis)
from .cartesian import CartesianPlotMixin
from .exporting import ExportingMixin
from .polar import PolarPlotMixin
from .view import ViewMixin


class PlotCanvas(ViewMixin, ExportingMixin, PolarPlotMixin, CartesianPlotMixin, QWidget):
    """自绘图表控件。"""

    # xmin, xmax, ymin, ymax（数据坐标）
    viewChanged = Signal(float, float, float, float)

    def __init__(self, title: str = ''):
        super().__init__()
        self.title = title
        # 导出数据时的文件头（对齐原版英文标题，独立于屏幕标题）
        self.export_header = title
        self._kind = 'empty'
        self._data: dict = {}
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        # 背景：浅灰（与 #eef1f5 主题一致）
        self.setStyleSheet('background-color:#eef1f5;')
        self._show_grid = True
        # 缩放/平移视图状态（仅对 line/lines/bar/scatter 有效）
        self._view = {'xmin': None, 'xmax': None, 'ymin': None, 'ymax': None}
        self._data_bounds = {'xmin': 0.0, 'xmax': 1.0, 'ymin': 0.0, 'ymax': 1.0}
        self._panning = False
        self._pan_anchor = None          # 平移起始像素点
        self._pan_view0 = None           # 平移起始视图
        # LOD（抽稀）缓存：(series_idx, nbins, id(root), n, i0, i1) -> (x, y)
        self._lod_cache = {}
        # 图表属性（Properties 对话框维护）
        self._props = {
            'xlabel': '', 'ylabel': '', 'y2label': '',
            'xunit': '', 'yunit': '', 'y2unit': '',
            'xaxis_log': False, 'yaxis_log': False, 'y2axis_log': False,
            'xaxis_min': None, 'xaxis_max': None,
            'yaxis_min': None, 'yaxis_max': None,
            'y2axis_min': None, 'y2axis_max': None,
            'grid_major': True, 'grid_minor': True,
            'font_size': 10,
            'channel_styles': {},  # label -> {'color', 'line_width', 'marker', ...}
        }
        # 导出图片时临时覆盖的显示开关（ExportImageDialog 使用）
        self._export_flags = {
            'show_title': True,
            'show_xlabel': True,
            'show_ylabel': True,
            'show_legend': True,
        }
        # 右击「Properties...」回调：风玫瑰等专用图可覆盖为打开自己的属性对话框，
        # 默认（None）打开通用 PlotPropertiesDialog。
        self.properties_handler = None
        self._build_toolbar()

    def set_export_flags(self, show_title=True, show_xlabel=True,
                         show_ylabel=True, show_legend=True):
        """临时设置导出时的显示开关；调用 reset_export_flags() 恢复。"""
        self._export_flags.update({
            'show_title': show_title,
            'show_xlabel': show_xlabel,
            'show_ylabel': show_ylabel,
            'show_legend': show_legend,
        })
        self.update()

    def reset_export_flags(self):
        """恢复默认导出显示开关。"""
        self._export_flags.update({
            'show_title': True,
            'show_xlabel': True,
            'show_ylabel': True,
            'show_legend': True,
        })
        self.update()

    # ---- 高层 API ----
    def clear(self, hint: str | None = None):
        if hint is None:
            hint = tr('该日期范围无数据')
        self._kind = 'empty'
        self._data = {'hint': hint}
        self._lod_cache.clear()
        self.update()

    def set_title(self, title: str):
        self.title = title
        self.update()

    def set_series_color(self, label: str, color: str):
        """按系列标签固定颜色（用于原版配色场景，如蓝=原始/棕黄=修改后）。"""
        styles = self._props.setdefault('channel_styles', {})
        styles.setdefault(label, {})['color'] = color
        self.update()

    def set_segment_band(self, x0: float | None, x1: float | None):
        """选中数据段高亮带（数据坐标，随 x 轴类型）；None 清除。
        用于 Flag Manually 的选段高亮。"""
        if not self._data:
            return
        if x0 is None or x1 is None or x1 <= x0:
            self._data.pop('seg_band', None)
        else:
            self._data['seg_band'] = (float(x0), float(x1))
        self.update()

    def plot_line(self, x, y, label: str = '', xlabel: str = '', ylabel: str = '',
                  xtick_fmt: str | None = None, ymin: float | None = None,
                  smooth: bool = False, marker: str | None = None):
        """绘制单条折线。x 可 datetime/numeric；ymin 强制 y 轴下界。
        smooth=True 时使用样条曲线连接点（用于风切变廓线）。
        marker 支持 'o' 圆点 / 'd' 菱形 / 's' 方块，None 不画标记。"""
        x = np.atleast_1d(np.asarray(x))
        x, auto_fmt = _coerce_x_axis(x)
        if xtick_fmt is None:
            xtick_fmt = auto_fmt
        self._reset_view()
        self._lod_cache.clear()
        self._kind = 'line'
        self._data = {
            'x': x,
            'y': np.atleast_1d(np.asarray(y)),
            'label': label, 'xlabel': xlabel, 'ylabel': ylabel,
            'xtick_fmt': xtick_fmt, 'ymin': ymin, 'smooth': smooth,
            'marker': marker,
        }
        valid = pd.notna(x) & pd.notna(self._data['y'])
        if valid.any():
            x_lo, x_hi = self._tight_limits(float(x[valid].min()),
                                            float(x[valid].max()))
            y_lo, y_hi, _ = self._nice_limits(float(self._data['y'][valid].min()),
                                              float(self._data['y'][valid].max()),
                                              hard_min=ymin)
            self._set_data_bounds(x_lo, x_hi, y_lo, y_hi)
        self.update()

    def plot_lines(self, series: list[tuple], xlabel: str = '', ylabel: str = '',
                   xtick_fmt: str | None = None, ymin: float | None = None,
                   xtick_step: float | None = None, gap_detect: bool = True,
                   show_legend: bool = True):
        """绘制多条折线。series=[(label, x_arr, y_arr, marker?)， ...]；
        marker 可选 'o'/'d'/'s'，缺省 None。ymin 强制 y 轴下界。
        xtick_step 指定主刻度固定步长（用于平均风速等需要整间隔的场景）。
        gap_detect=False 禁用缺测缺口检测（如风切变廓线：x 非等距，起点处
        跳变会被误断）。show_legend=False 关闭内嵌图例（外部图例面板场景）。
        """
        coerced = []
        auto_fmt = None
        for item in series:
            label, sx, sy = item[0], item[1], item[2]
            marker = item[3] if len(item) >= 4 else None
            sx = np.atleast_1d(np.asarray(sx))
            sx, af = _coerce_x_axis(sx)
            if af:
                auto_fmt = 'date'
            coerced.append((label, sx, np.atleast_1d(np.asarray(sy)), marker))
        if xtick_fmt is None:
            xtick_fmt = auto_fmt
        self._reset_view()
        self._lod_cache.clear()
        self._kind = 'lines'
        self._data = {
            'series': coerced,
            'xlabel': xlabel, 'ylabel': ylabel,
            'xtick_fmt': xtick_fmt, 'ymin': ymin,
            'xtick_step': xtick_step,
            'gap_detect': gap_detect,
            'show_legend': show_legend,
        }
        if coerced:
            xs_all = np.concatenate([s[1] for s in coerced])
            ys_all = np.concatenate([s[2] for s in coerced])
            valid = pd.notna(xs_all) & pd.notna(ys_all)
            if valid.any():
                x_min = float(xs_all[valid].min())
                x_max = float(xs_all[valid].max())
                if xtick_step is not None and xtick_step > 0:
                    x_lo = math.floor(x_min / xtick_step) * xtick_step
                    x_hi = math.ceil(x_max / xtick_step) * xtick_step
                else:
                    x_lo, x_hi = self._tight_limits(x_min, x_max)
                y_lo, y_hi, _ = self._nice_limits(float(ys_all[valid].min()),
                                                  float(ys_all[valid].max()),
                                                  hard_min=ymin)
                self._set_data_bounds(x_lo, x_hi, y_lo, y_hi)
        self.update()

    def plot_bar(self, x, y, xlabel: str = '', ylabel: str = '',
                 xtick_fmt: str | None = None, ymin: float | None = None):
        x = np.atleast_1d(np.asarray(x))
        x, auto_fmt = _coerce_x_axis(x)
        if xtick_fmt is None:
            xtick_fmt = auto_fmt
        self._kind = 'bar'
        self._data = {
            'x': x, 'y': np.atleast_1d(np.asarray(y)),
            'xlabel': xlabel, 'ylabel': ylabel,
            'xtick_fmt': xtick_fmt, 'ymin': ymin,
        }
        self.update()

    def plot_histogram(self, edges, counts, xlabel: str = '',
                       ylabel: str = '', ymin: float | None = 0,
                       overlay: tuple | None = None,
                       legend: list | None = None,
                       thousands: bool = False,
                       color: str | None = None):
        """数值边界直方图（Histogram 标签页）。

        edges : (n+1,) 分箱边界；counts : (n,) 每箱高度（频次或频率%）
        overlay : (x, y, color, label) 叠加曲线（如 Best-fit Weibull）
        legend : [(color, label), ...] 绘于图下方居中；thousands：y 刻度千分位
        color : 柱体颜色（缺省深蓝；Fix Quantization 修改后直方图为棕黄）
        """
        self._reset_view()
        self._lod_cache.clear()
        self._kind = 'histogram'
        edges = np.atleast_1d(np.asarray(edges, dtype=float))
        counts = np.atleast_1d(np.asarray(counts, dtype=float))
        self._data = {
            'edges': edges, 'counts': counts,
            'xlabel': xlabel, 'ylabel': ylabel,
            'ymin': ymin, 'overlay': overlay, 'legend': legend or [],
            'thousands': thousands, 'bar_color': color,
        }
        if len(edges) >= 2:
            x_lo = float(edges[0])
            x_hi = float(edges[-1])
            if x_hi <= x_lo:
                x_hi = x_lo + 1.0
            valid = np.isfinite(counts)
            y_max = float(np.nanmax(counts[valid])) if valid.any() else 1.0
            y_lo, y_hi, _ = self._nice_limits(0.0, y_max, hard_min=ymin)
            self._set_data_bounds(x_lo, x_hi, y_lo, y_hi)
        self.update()

    def plot_scatter(self, x, y, xlabel: str = '', ylabel: str = '',
                     title: str = '', regression: bool = False,
                     ymin: float | None = None, xtick_fmt: str | None = None,
                     point_colors=None, colorbar=None):
        """绘制散点图。

        point_colors : 与 x/y 等长的颜色串列表（Color code by 功能）；
        colorbar : [(label, color), ...] 自上而下的色带图例（离散分档着色时
        画在绘图区右侧）。"""
        x = np.atleast_1d(np.asarray(x))
        x, auto_fmt = _coerce_x_axis(x)
        if xtick_fmt is None:
            xtick_fmt = auto_fmt
        self._reset_view()
        self._lod_cache.clear()
        self._kind = 'scatter'
        self._data = {
            'x': x, 'y': np.atleast_1d(np.asarray(y)),
            'xlabel': xlabel, 'ylabel': ylabel, 'regression': regression,
            'ymin': ymin, 'xtick_fmt': xtick_fmt,
            'point_colors': list(point_colors) if point_colors is not None
            else None,
            'colorbar': list(colorbar) if colorbar else None,
        }
        self.title = title or self.title
        valid = pd.notna(x) & pd.notna(y)
        if valid.any():
            x_lo, x_hi = self._tight_limits(float(x[valid].min()),
                                            float(x[valid].max()))
            y_lo, y_hi, _ = self._nice_limits(float(self._data['y'][valid].min()),
                                              float(self._data['y'][valid].max()),
                                              hard_min=ymin)
            self._set_data_bounds(x_lo, x_hi, y_lo, y_hi)
        self.update()

    def plot_polar(self, sectors: int, freq: np.ndarray, title: str = '',
                   energies: np.ndarray | None = None,
                   labels: list[str] | None = None,
                   calm: float = 0.0,
                   center_deg: np.ndarray | None = None,
                   display_type: str = 'frequency',
                   unit: str = '%',
                   styles: list[dict] | None = None,
                   radial_max: float | None = None,
                   radial_min: float = 0.0,
                   inner_circle_pct: float = 0.0,
                   fill_factor: float = 0.85,
                   show_legend: bool = True,
                   line_style: str = 'solid',
                   marker: str | None = None):
        """绘制风玫瑰。

        Parameters
        ----------
        sectors : 扇区数
        freq : 数值矩阵，形状 (sectors, n_series) 或 (sectors,)；
               display_type='scatter_plot' 时为 (N, 2) 的 [direction, value]
        title : 标题
        energies : 兼容旧接口，未使用
        labels : 系列标签
        calm : 静风比例 (%)
        center_deg : 扇区中心角度数组 (sectors,)，None 时自动生成
        display_type : frequency/occurrences/mean/max/std_dev/total_energy/scatter_plot
        unit : 径向轴单位
        styles : 每个系列的样式字典列表；键：color/line_width/line_style/marker/
                 marker_size/fill/visible/label/rose_style
        radial_max : 固定径向最大值；None 时自动 nice
        radial_min : 径向最小值（内圆百分比用）
        inner_circle_pct : 静风圆占径向轴的百分比（0=不画）
        fill_factor : 绘图区填充比例（0~1）
        show_legend : 是否显示图例
        line_style : 默认线型
        marker : 默认标记
        """
        self._kind = 'polar'
        self.title = title or self.title
        self._data = {
            'sectors': sectors,
            'freq': np.asarray(freq, dtype=float),
            'energies': energies,
            'labels': list(labels) if labels else None,
            'calm': float(calm),
            'center_deg': (np.asarray(center_deg, dtype=float)
                           if center_deg is not None else None),
            'display_type': display_type,
            'unit': unit or '%',
            'styles': styles or [],
            'radial_max': radial_max,
            'radial_min': radial_min,
            'inner_circle_pct': inner_circle_pct,
            'fill_factor': max(0.1, min(1.0, fill_factor)),
            'show_legend': show_legend,
            'line_style': line_style,
            'marker': marker,
        }
        self.update()

    def plot_table(self, rows: list[list], headers: list[str]):
        self._kind = 'table'
        self._data = {'rows': rows, 'headers': headers}
        self.update()

    def plot_heatmap(self, matrix, xlabels: list, ylabels: list,
                     xlabel: str = '', ylabel: str = '', unit: str = '',
                     vmin: float | None = None, vmax: float | None = None,
                     cmap: str = 'blue'):
        """绘制热力图（数据覆盖 / DMap）。

        matrix 形状 (n_rows, n_cols)，NaN 视为缺测（灰底）；
        xlabels/ylabels 为列/行标签；vmin/vmax 为色标上下限（None=自动）。"""
        self._kind = 'heatmap'
        self._data = {
            'matrix': np.asarray(matrix, dtype=float),
            'xlabels': list(xlabels), 'ylabels': list(ylabels),
            'xlabel': xlabel, 'ylabel': ylabel, 'unit': unit,
            'vmin': vmin, 'vmax': vmax, 'cmap': cmap,
        }
        self.update()

    def plot_box(self, groups: list[tuple], xlabel: str = '',
                 ylabel: str = '', show_mean: bool = True):
        """绘制箱线图。

        groups = [(标签, {'min','q1','med','q3','max','mean','n'}), ...]"""
        self._kind = 'box'
        self._data = {
            'groups': list(groups), 'xlabel': xlabel, 'ylabel': ylabel,
            'show_mean': show_mean,
        }
        self.update()

    # ---- 交互工具栏与右键菜单 ----
    def _build_toolbar(self):
        """在控件右下角叠加一个微型工具栏。"""
        self._toolbar = QWidget(self)
        self._toolbar.setStyleSheet(
            'QWidget { background-color: rgba(238,241,245,220); '
            'border: 1px solid #d5dbe2; border-radius: 3px; }'
            'QPushButton { border: none; padding: 2px 4px; font-size: 11px; '
            'color: #4a5460; }'
            'QPushButton:hover { background-color: #d5dbe2; }'
        )
        lay = QHBoxLayout(self._toolbar)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)

        def mk(text, tip, slot):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFlat(True)
            b.setMaximumWidth(26)
            b.clicked.connect(slot)
            return b

        lay.addWidget(mk('⛶', 'Fit', self._fit_view))
        lay.addWidget(mk('🔍+', 'Zoom in', self._zoom_in))
        lay.addWidget(mk('🔍-', 'Zoom out', self._zoom_out))
        lay.addWidget(mk('💾', 'Export', self._export_image))
        lay.addWidget(mk('📋', 'Copy bitmap', self._copy_bitmap))
        self._toolbar.adjustSize()
        self._toolbar.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_toolbar'):
            self._toolbar.move(self.width() - self._toolbar.width() - 6,
                               self.height() - self._toolbar.height() - 6)

    def enterEvent(self, event):
        self._toolbar.show()
        return super().enterEvent(event)

    def leaveEvent(self, event):
        self._toolbar.hide()
        return super().leaveEvent(event)

    # ---- 绘制 ----
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 先把绘制严格限制在控件范围内，防止任何情况下线条/文字溢出到相邻控件
        p.setClipRect(self.rect())
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor('#eef1f5'))

        kind = self._kind
        if kind == 'empty':
            self._draw_empty(p, w, h)
            return

        # 计算绘图区：留边
        left, right, top, bottom = self._plot_margins()
        rect = QRectF(left, top, w - left - right, h - top - bottom)

        # 标题
        if self.title and self._export_flags.get('show_title', True):
            p.setPen(QColor('#2a3542'))
            p.setFont(QFont('Microsoft YaHei', 11, QFont.Bold))
            p.drawText(QRectF(0, 6, w, 24), Qt.AlignCenter, self.title)

        if kind in ('line', 'lines'):
            self._draw_lines(p, rect)
        elif kind == 'bar':
            self._draw_bar(p, rect)
        elif kind == 'histogram':
            self._draw_histogram(p, rect)
        elif kind == 'scatter':
            self._draw_scatter(p, rect)
        elif kind == 'polar':
            self._draw_polar(p, rect)
        elif kind == 'table':
            self._draw_table(p, rect)
        elif kind == 'heatmap':
            self._draw_heatmap(p, rect)
        elif kind == 'box':
            self._draw_box(p, rect)

    # ---- 各图类型实现 ----
    def _draw_empty(self, p: QPainter, w, h):
        p.setPen(QPen(QColor('#d5dbe2'), 0.5))
        p.setBrush(QColor('#ffffff'))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)
        p.setPen(QColor('#9aa4ae'))
        p.setFont(QFont('Microsoft YaHei', 10))
        p.drawText(self.rect(), Qt.AlignCenter, self._data.get('hint', ''))

    def export_png(self, path: str):
        self.grab().save(path)
