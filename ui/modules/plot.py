"""PlotCanvas：QPainter 自绘图表控件（零新增依赖）。

支持：plot_line / plot_bar / plot_scatter / plot_polar(风玫瑰) / plot_table
      / plot_heatmap(数据覆盖·DMap) / plot_box(箱线图)。
布局采用 "10% padding" 原则：
  - X 轴标签在下 8%，Y 轴在左 8%，标题在上 5%。
  - 实际绘图区 = rect 剩余内部。
颜色遵循中文工程报告习惯：风速蓝、风向绿、温度橙、气压紫、湿度青。
"""

from __future__ import annotations

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


# 默认调色板
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


class PlotCanvas(QWidget):
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

    # ---- 图例：位于绘图区右侧外部，纵向单列 ----
    _LEGEND_FONT_PT = 7
    _LEGEND_LINE_W = 10
    _LEGEND_GAP = 5
    _LEGEND_PAD_L = 8     # 绘图区右边框 → 示例线起点
    _LEGEND_PAD_R = 6     # 文字右侧留白
    _LEGEND_ROW_H = 12
    _LEGEND_MAX_TEXT_W = 180

    def _legend_labels(self) -> list[str]:
        """当前图形要显示的图例条目；无条目时绘图区不预留右侧空间。"""
        kind = self._kind
        data = self._data or {}
        if kind == 'lines':
            out = [str(s[0]) for s in (data.get('series') or []) if s and s[0]]
        elif kind == 'line':
            lab = data.get('label', '')
            out = [str(lab)] if lab else []
        elif kind == 'polar':
            out = [str(x) for x in (data.get('labels') or [])]
        else:
            out = []
        return [t for t in out if t]

    def _legend_text_width(self, labels) -> int:
        fm = QFontMetrics(QFont('Microsoft YaHei', self._LEGEND_FONT_PT))
        return int(min(max((fm.horizontalAdvance(t) for t in labels), default=0),
                       self._LEGEND_MAX_TEXT_W))

    def _legend_width(self, labels=None) -> int:
        if not self._export_flags.get('show_legend', True):
            return 0
        if labels is None:
            labels = self._legend_labels()
        if not labels:
            return 0
        return int(self._LEGEND_PAD_L + self._LEGEND_LINE_W + self._LEGEND_GAP
                   + self._legend_text_width(labels) + self._LEGEND_PAD_R)

    def _plot_margins(self):
        """返回当前绘图区边距 (left, right, top, bottom)。"""
        kind = self._kind
        left = 58
        right = 24
        show_title = self._export_flags.get('show_title', True)
        show_xlabel = self._export_flags.get('show_xlabel', True)
        show_ylabel = self._export_flags.get('show_ylabel', True)
        show_legend = self._export_flags.get('show_legend', True)
        top = 36 if (self.title and show_title) else 24
        bottom = 48
        if (show_ylabel and 'ylabel' in self._data and self._data['ylabel']):
            left = max(left, 64)
        if (show_xlabel and 'xlabel' in self._data and self._data['xlabel']):
            bottom = max(bottom, 56)
        if kind == 'heatmap':
            fm = QFontMetrics(QFont('Microsoft YaHei', 8))
            widest = max((fm.horizontalAdvance(str(t))
                          for t in self._data.get('ylabels') or ['']), default=0)
            left = max(left, min(240, widest + 14))
            right = max(right, 96)
            bottom = max(bottom, 52)
        elif kind == 'box':
            bottom = max(bottom, 52)
        elif kind == 'histogram':
            if self._data.get('legend'):
                bottom = max(bottom, 78)
        elif kind == 'scatter' and self._data.get('colorbar'):
            right = max(right, 110)     # 右侧色带图例（色块 + 标签）
        # 图例在绘图区之外，故从右边距里扣出它的宽度；
        # show_legend=False（外部图例面板接管）时不预留，避免右侧大片空白
        if show_legend and self._data.get('show_legend', True):
            lw = self._legend_width()
            if lw:
                lw = int(min(lw, max(0, self.width()) * 0.35))
                right += lw
        return left, right, top, bottom

    def _set_data_bounds(self, xmin: float, xmax: float, ymin: float, ymax: float):
        """记录数据全范围，用于限制缩放/平移不越界。"""
        self._data_bounds = {'xmin': float(xmin), 'xmax': float(xmax),
                             'ymin': float(ymin), 'ymax': float(ymax)}

    @staticmethod
    def _tight_limits(vmin: float, vmax: float) -> tuple[float, float]:
        """X 轴边界用数据真实起止（不再外扩 5%），
        保证「复位 / 缩到最小」时两端不出现空白。"""
        if not (math.isfinite(vmin) and math.isfinite(vmax)):
            return 0.0, 1.0
        if vmax - vmin < 1e-9:
            vmin, vmax = vmin - 0.5, vmax + 0.5
        return float(vmin), float(vmax)

    def _lod(self, key: int, x: np.ndarray, y: np.ndarray,
             nbins: int, x_lo: float, x_hi: float):
        """按当前视图裁剪 + 像素列抽稀，带缓存。返回 (x, y)。"""
        n = x.size
        i0, i1 = 0, n
        if n > 4 and x[0] <= x[-1] and bool(np.all(np.diff(x) >= 0)):
            # 升序序列：二分裁到可见区间，减少后续抽稀量
            i0 = max(0, int(np.searchsorted(x, x_lo, 'left')) - 1)
            i1 = min(n, int(np.searchsorted(x, x_hi, 'right')) + 1)
            xs, ys = x[i0:i1], y[i0:i1]
        else:
            xs, ys = x, y
        ck = (key, nbins, id(_root_base(x)), n, i0, i1)
        hit = self._lod_cache.get(ck)
        if hit is not None:
            return hit
        dx, dy = _decimate_xy(xs, ys, nbins)
        if len(self._lod_cache) > 64:
            self._lod_cache.clear()
        self._lod_cache[ck] = (dx, dy)
        return dx, dy

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

    def _copy_bitmap(self):
        """将当前图表渲染为位图并复制到剪贴板。"""
        from PySide6.QtCore import QPoint
        pix = QPixmap(self.size())
        pix.fill(QColor('#eef1f5'))
        p = QPainter(pix)
        self.render(p, QPoint(0, 0))
        p.end()
        QApplication.clipboard().setPixmap(pix)

    def _export_image(self):
        """导出图片对话框。"""
        dlg = ExportImageDialog(self)
        dlg.exec()

    def _export_data(self):
        """导出图表底层数据，默认 .txt，文件头为英文规范名（对齐原版）。"""
        default_name = f"{self.export_header.replace(' ', '_')}.txt" if self.export_header else 'plot_data.txt'
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Data', default_name,
            'Text (*.txt);;CSV (*.csv);;All files (*.*)')
        if not path:
            return
        df = self._to_dataframe()
        if df is None or df.empty:
            QMessageBox.warning(self, tr('无数据'), tr('当前图表没有可导出的数据。'))
            return
        try:
            header = f'{self.export_header}\n' if self.export_header else ''
            if path.lower().endswith('.csv'):
                with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                    f.write(header)
                    df.to_csv(f, index=False)
            else:
                with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                    f.write(header)
                    df.to_csv(f, sep='\t', index=False)
        except Exception as e:
            QMessageBox.warning(self, tr('导出失败'), f'{e}')

    def _show_properties(self):
        """打开图表属性对话框。

        若外部（如 WindRoseWidget）设置了 properties_handler，优先调用，
        否则打开通用 PlotPropertiesDialog。
        """
        if self.properties_handler is not None:
            self.properties_handler()
            return
        dlg = PlotPropertiesDialog(self)
        dlg.exec()

    def _to_dataframe(self) -> pd.DataFrame | None:
        """把当前图表数据转换为 DataFrame，供导出。"""
        kind = self._kind
        data = self._data
        if kind == 'empty':
            return None
        if kind in ('line', 'bar', 'scatter'):
            return pd.DataFrame({
                'x': data.get('x', []),
                'y': data.get('y', []),
            })
        if kind == 'lines':
            rows = []
            for s in data.get('series', []):
                label, x, y = s[0], s[1], s[2]
                n = min(len(x), len(y))
                for i in range(n):
                    rows.append({'series': label, 'x': x[i], 'y': y[i]})
            return pd.DataFrame(rows) if rows else None
        if kind == 'polar':
            freq = np.asarray(data.get('freq', []))
            sector = np.arange(freq.shape[0] if freq.ndim else 0)
            if freq.ndim == 1:
                return pd.DataFrame({'sector': sector, 'frequency': freq})
            # 多通道玫瑰：逐通道输出列
            cols = {'sector': sector}
            for ci in range(freq.shape[1]):
                cols[f'frequency_ch{ci}'] = freq[:, ci]
            return pd.DataFrame(cols)
        if kind == 'box':
            rows = []
            for label, st in data.get('groups', []):
                st = st or {}
                rows.append({
                    'label': label, 'min': st.get('min'), 'q1': st.get('q1'),
                    'median': st.get('med'), 'q3': st.get('q3'),
                    'max': st.get('max'), 'mean': st.get('mean'), 'n': st.get('n'),
                })
            return pd.DataFrame(rows) if rows else None
        if kind == 'heatmap':
            return pd.DataFrame(data.get('matrix', []))
        if kind == 'table':
            return pd.DataFrame(data.get('rows', []),
                                columns=data.get('headers', []))
        return None

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

    def _nice_limits(self, vmin: float, vmax: float, pad: float = 0.05,
                     hard_min: float | None = None,
                     hard_max: float | None = None):
        """生成 nice 的坐标范围与 tick 间隔；hard_min 强制下界不低于该值。"""
        if not math.isfinite(vmin) or not math.isfinite(vmax):
            return 0.0, 1.0, 0.5
        if abs(vmax - vmin) < 1e-12:
            vmin, vmax = vmin - 0.5, vmax + 0.5
        span = vmax - vmin
        lo = vmin - span * pad
        hi = vmax + span * pad
        if hard_min is not None:
            lo = max(lo, hard_min)
            if hi < lo + 1e-12:
                hi = lo + span * (1 + pad)
        if hard_max is not None:
            hi = min(hi, hard_max)
            if lo > hi - 1e-12:
                lo = hi - span * (1 + pad)
        span = hi - lo
        # 找 nice step: 1,2,5 * 10^k
        rough = span / 5
        if rough <= 0:
            rough = 1.0
        exp10 = 10 ** math.floor(math.log10(rough))
        frac = rough / exp10
        if frac <= 1:
            step = exp10
        elif frac <= 2:
            step = 2 * exp10
        elif frac <= 5:
            step = 5 * exp10
        else:
            step = 10 * exp10
        nice_lo = math.floor(lo / step) * step
        nice_hi = math.ceil(hi / step) * step
        # hard_min/hard_max 为强制边界：轴端精确落在该值（如 ymin=0 → y 轴从 0 起）
        if hard_min is not None:
            nice_lo = hard_min
        if hard_max is not None:
            nice_hi = hard_max
        if (hard_min is not None or hard_max is not None):
            # 强制边界后把跨度向上取整到 5 的倍数：绘图区把量程五等分作刻度，
            # 否则会出现 2.8 这类难看的刻度步长
            forced_span = nice_hi - nice_lo
            if forced_span > 0:
                nice_span = math.ceil(forced_span / 5.0) * 5.0
                if hard_max is None:
                    nice_hi = nice_lo + nice_span
                else:
                    nice_lo = nice_hi - nice_span
        return nice_lo, nice_hi, step

    def _draw_grid(self, p: QPainter, rect: QRectF, lo, hi, step, xaxis: bool = True):
        pen = QPen(QColor('#e0e4ea'), 0.5)
        p.setPen(pen)
        ticks = np.arange(lo, hi + step / 2, step)
        for t in ticks:
            if xaxis:
                x = rect.left() + rect.width() * (t - lo) / (hi - lo)
                p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            else:
                y = rect.bottom() - rect.height() * (t - lo) / (hi - lo)
                p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
        return ticks

    def _draw_axes(self, p: QPainter, rect: QRectF, x_lo, x_hi, y_lo, y_hi,
                   xlabel: str, ylabel: str, xtick_fmt=None,
                   show_grid: bool = True, xtick_step: float | None = None,
                   thousands_y: bool = False):
        if not self._export_flags.get('show_xlabel', True):
            xlabel = ''
        if not self._export_flags.get('show_ylabel', True):
            ylabel = ''
        from datetime import datetime

        p.setPen(QPen(QColor('#8c96a5'), 0.8))
        # 外框
        p.drawRect(rect)

        # ---- 物理/语义坐标范围修正 ----
        if xtick_fmt == 'month':
            x_lo, x_hi = 1.0, 12.0
        elif xtick_fmt == 'hour':
            x_lo, x_hi = 0.0, 24.0

        # ---- Y 轴 ticks ----
        y_step = (y_hi - y_lo) / 5 if y_hi != y_lo else 1
        y_ticks = np.linspace(y_lo, y_hi, 6)
        p.setFont(QFont('Microsoft YaHei', 8))
        p.setPen(QColor('#4a5460'))
        for t in y_ticks:
            y = rect.bottom() - rect.height() * (t - y_lo) / (y_hi - y_lo)
            txt = f'{t:,.0f}' if thousands_y else self._fmt_tick(t)
            p.drawText(QRectF(rect.left() - 54, y - 8, 50, 16),
                       Qt.AlignRight | Qt.AlignVCenter, txt)
            if show_grid:
                p.setPen(QPen(QColor('#d5dbe2'), 0.5))
                p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
                p.setPen(QColor('#4a5460'))

        # ---- X 轴 ticks ----
        if xtick_step is not None and xtick_step > 0:
            x_ticks = np.arange(math.floor(x_lo / xtick_step) * xtick_step,
                                x_hi + xtick_step * 0.5,
                                xtick_step)
        elif xtick_fmt == 'month':
            x_ticks = np.arange(1, 13)
        elif xtick_fmt == 'hour':
            x_ticks = np.arange(0, 25, 4)
        else:
            x_step = (x_hi - x_lo) / 5 if x_hi != x_lo else 1
            x_ticks = np.linspace(x_lo, x_hi, 6)
        for t in x_ticks:
            x = rect.left() + rect.width() * (t - x_lo) / (x_hi - x_lo)
            # 裁剪超出绘图区右侧的刻度标签（避免画到图例区）
            if x > rect.right() + 40:
                continue
            if xtick_fmt == 'date':
                try:
                    # x 为 Python ordinal（from toordinal）
                    txt = datetime.fromordinal(int(t)).strftime('%Y-%m-%d')
                except Exception:
                    txt = str(t)
            elif xtick_fmt == 'month':
                txt = f'{int(t):d}月'
            elif xtick_fmt == 'hour':
                txt = f'{int(t):d}'
            else:
                txt = self._fmt_tick(t)
            p.drawText(QRectF(x - 40, rect.bottom() + 4, 80, 16),
                       Qt.AlignCenter, txt)
            if show_grid:
                p.setPen(QPen(QColor('#d5dbe2'), 0.5))
                p.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
                p.setPen(QColor('#4a5460'))

        # ---- 轴标题 ----
        if ylabel:
            p.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
            p.save()
            cx = rect.left() - 42
            cy = rect.top() + rect.height() / 2
            p.translate(cx, cy)
            p.rotate(-90)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(ylabel)
            p.drawText(QRectF(-tw / 2, -8, tw, 16), Qt.AlignCenter, ylabel)
            p.restore()
        if xlabel:
            p.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
            p.drawText(QRectF(rect.left(), rect.bottom() + 22, rect.width(), 18),
                       Qt.AlignCenter, xlabel)

    @staticmethod
    def _fmt_tick(t: float) -> str:
        """按数量级选择简洁刻度格式，避免小数值的科学计数法。"""
        if not math.isfinite(t):
            return ''
        if abs(t) >= 10000 or (abs(t) < 1e-3 and t != 0):
            return f'{t:.2e}'
        if abs(t - round(t)) < 1e-9 and abs(t) < 10000:
            return f'{int(round(t))}'
        if abs(t) >= 100:
            return f'{t:.1f}'
        if abs(t) >= 1:
            return f'{t:.2f}'
        return f'{t:.3f}'

    def _draw_lines(self, p: QPainter, rect: QRectF):
        data = self._data
        ymin = data.get('ymin')
        if data.get('series'):
            raw = data['series']
        elif 'x' in data and 'y' in data:
            raw = [(data.get('label', ''), data['x'], data['y'], data.get('marker'))]
        else:
            self._draw_empty(p, self.width(), self.height())
            return
        # 归一化：每个 series 的 x/y 强制 1-d，并按最小长度对齐，避免
        # 标量(0-d) 或 x/y 长度不一致导致 concatenate / 布尔索引崩溃。
        series = []
        for item in raw:
            label, x, y = item[0], item[1], item[2]
            marker = item[3] if len(item) >= 4 else None
            x = np.atleast_1d(np.asarray(x))
            if x.dtype.kind == 'M':
                x, _ = _coerce_x_axis(x)
            else:
                x = x.astype(float, copy=False)
            y = np.atleast_1d(np.asarray(y)).astype(float, copy=False)
            n = min(len(x), len(y))
            if n == 0:
                continue
            series.append((label, x[:n], y[:n], marker))
        if not series:
            self._draw_empty(p, self.width(), self.height())
            return
        xs_all = np.concatenate([s[1] for s in series])
        ys_all = np.concatenate([s[2] for s in series])
        valid = np.isfinite(xs_all) & np.isfinite(ys_all)
        if not valid.any():
            self._draw_empty(p, self.width(), self.height())
            return
        ymax = data.get('ymax')
        xtick_fmt = data.get('xtick_fmt')
        xtick_step = data.get('xtick_step')
        # 数据全范围：X 按 xtick_step 对齐到刻度（保证轴上含全部数据且末点不贴右缘）；
        # 无 xtick_step 时沿用真实起止（缩到最小/复位时两端无空白）。Y 用 nice 范围保留上下余量。
        xv_min = float(xs_all[valid].min())
        xv_max = float(xs_all[valid].max())
        if xtick_step is not None and xtick_step > 0:
            x_lo_full = math.floor(xv_min / xtick_step) * xtick_step
            x_hi_full = math.ceil(xv_max / xtick_step) * xtick_step
            # 数据最大值恰好落在刻度边界时再外扩一个刻度（如均值最大 4.0 m/s → 横轴到 5.0 m/s）
            if x_hi_full - xv_max < 1e-9:
                x_hi_full += xtick_step
        else:
            x_lo_full, x_hi_full = self._tight_limits(xv_min, xv_max)
        if xtick_fmt == 'hour':
            x_lo_full, x_hi_full = 0.0, 24.0
        elif xtick_fmt == 'month':
            x_lo_full, x_hi_full = 1.0, 12.0
        y_lo_full, y_hi_full, _ = self._nice_limits(float(ys_all[valid].min()), float(ys_all[valid].max()),
                                                    hard_min=ymin, hard_max=ymax)
        self._set_data_bounds(x_lo_full, x_hi_full, y_lo_full, y_hi_full)

        # 当前视图范围（未缩放=全范围）
        x_lo, x_hi = self._effective_range(x=True)
        y_lo, y_hi = self._effective_range(x=False)
        self._draw_axes(p, rect, x_lo, x_hi, y_lo, y_hi,
                        data.get('xlabel', ''), data.get('ylabel', ''),
                        xtick_fmt, show_grid=self._show_grid,
                        xtick_step=xtick_step)
        smooth = self._data.get('smooth', False)
        styles = self._props.get('channel_styles', {})
        denom_x = (x_hi - x_lo) or 1.0
        denom_y = (y_hi - y_lo) or 1.0
        # 抽稀粒度：每像素 1 列（LOD 后 ≤ 2 点/像素，峰值不丢）
        nbins = max(2, int(rect.width()))
        # 密集曲线关闭抗锯齿：Qt 光栅引擎对带 join 的描边开销呈病态放大
        # （同几何 drawPolyline 1350 ms vs drawLines 36 ms，关 AA 再降到 14 ms）。
        # 网格/文字/坐标仍保留 AA，视觉无明显差异。
        # 稀疏曲线（日变化廓线等 ≤4000 点）保持 AA，否则 1.5px 线呈点状。
        # 同时把曲线裁剪到绘图区，防止多图堆叠时线条越界。
        total_pts = sum(len(s[1]) for s in series)
        dense = total_pts > 4000
        p.setRenderHint(QPainter.Antialiasing, not dense)
        p.setClipRect(rect)
        # 选中数据段高亮带（画在曲线之下）
        band = self._data.get('seg_band')
        if band:
            bx0 = max(x_lo, min(float(band[0]), x_hi))
            bx1 = max(x_lo, min(float(band[1]), x_hi))
            if bx1 > bx0:
                rx0 = rect.left() + rect.width() * (bx0 - x_lo) / denom_x
                rx1 = rect.left() + rect.width() * (bx1 - x_lo) / denom_x
                p.fillRect(QRectF(rx0, rect.top(), rx1 - rx0, rect.height()),
                           QColor(255, 235, 59, 110))
        for i, (label, x, y, marker) in enumerate(series):
            st = styles.get(label, {})
            color = QColor(st['color']) if st.get('color') else PALETTE[i % len(PALETTE)]
            pen = QPen(color, float(st.get('line_width', 1.5)))
            p.setPen(pen)
            m = np.isfinite(x) & np.isfinite(y)
            xm, ym = x[m], y[m]
            if xm.size < 2:
                continue
            xd, yd = self._lod(i, xm, ym, nbins, x_lo, x_hi)
            # 向量化映射到像素（替代逐点 Python 循环，5 万点亦为毫秒级）
            px = rect.left() + rect.width() * (xd - x_lo) / denom_x
            py = rect.bottom() - rect.height() * (yd - y_lo) / denom_y
            if px.size < 2:
                continue
            # 避免跨缺测缺口连出长斜线：抽稀后相邻点 x 跳变超过中位跳变 10 倍时断开。
            # 对 x 非等距的曲线（如风切变廓线）可传 gap_detect=False 禁用，
            # 否则起点处跳变会被误当成缺口。
            if data.get('gap_detect', True):
                dxd = np.diff(xd)
                med = np.median(dxd) if dxd.size else 1.0
                gap = dxd > max(med * 10, 1e-9)
            else:
                gap = np.zeros(px.size - 1, dtype=bool)
            if smooth and px.size >= 3:
                p.setRenderHint(QPainter.Antialiasing, True)
                p.drawPath(self._smooth_path(
                    [QPointF(float(a), float(b)) for a, b in zip(px, py)]))
                p.setRenderHint(QPainter.Antialiasing, not dense)
            else:
                # 用独立线段绘制：避免 drawPolyline 的连接点(join)计算爆炸
                p.drawLines([QLineF(float(px[k]), float(py[k]),
                                    float(px[k + 1]), float(py[k + 1]))
                             for k in range(px.size - 1) if not gap[k]])
            # 数据标记（点少时才画，避免拖慢重绘）
            if marker and px.size <= 3000:
                p.setBrush(color)
                p.setPen(QPen(color, 1.2))
                for a, b in zip(px, py):
                    self._draw_marker(p, QPointF(float(a), float(b)), marker, 4.0)
                p.setPen(pen)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setClipping(False)
        # ---- 图例（右上角，半透明背景，自动列数）----
        labels = [s[0] for s in series if s[0]]
        if labels and data.get('show_legend', True):
            self._draw_legend(p, rect, labels)

    @staticmethod
    def _smooth_path(points: list[QPointF]) -> QPainterPath:
        """用三次贝塞尔构造平滑曲线，控制点沿相邻点切线方向。"""
        path = QPainterPath()
        path.moveTo(points[0])
        n = len(points)
        for i in range(n - 1):
            p0 = points[max(0, i - 1)]
            p1 = points[i]
            p2 = points[i + 1]
            p3 = points[min(n - 1, i + 2)]
            # 切线方向
            t1 = QPointF((p2.x() - p0.x()) * 0.15, (p2.y() - p0.y()) * 0.15)
            t2 = QPointF((p3.x() - p1.x()) * 0.15, (p3.y() - p1.y()) * 0.15)
            c1 = QPointF(p1.x() + t1.x(), p1.y() + t1.y())
            c2 = QPointF(p2.x() - t2.x(), p2.y() - t2.y())
            path.cubicTo(c1, c2, p2)
        return path

    @staticmethod
    def _draw_marker(p: QPainter, pt: QPointF, kind: str, size: float):
        """在 pt 处绘制数据标记：'o' 圆 / 'd' 菱形 / 's' 方块。"""
        r = size
        if kind == 'o':
            p.drawEllipse(pt, r, r)
        elif kind == 's':
            p.drawRect(QRectF(pt.x() - r, pt.y() - r, 2 * r, 2 * r))
        else:  # 'd' 菱形
            poly = [
                QPointF(pt.x(), pt.y() - r),
                QPointF(pt.x() + r, pt.y()),
                QPointF(pt.x(), pt.y() + r),
                QPointF(pt.x() - r, pt.y()),
            ]
            p.drawPolygon(poly)

    def _draw_legend(self, p: QPainter, rect: QRectF, labels: list[str]):
        """在绘图区右侧外部纵向绘制图例（无背景框），对齐原版样式。

        - 位置：绘图区右边框之外，顶端与绘图区顶端齐平，纵向单列；
        - 字号 7pt，示例横线长 10px；
        - 条目超过可用高度时截断，末行给出「… +N」提示；
        - 文字过长按可用宽度省略，保证不越出控件右边界。
        """
        if not labels or not self._export_flags.get('show_legend', True):
            return
        row_h = self._LEGEND_ROW_H
        line_w = self._LEGEND_LINE_W
        gap = self._LEGEND_GAP
        p.setFont(QFont('Microsoft YaHei', self._LEGEND_FONT_PT))
        fm = p.fontMetrics()
        x0 = rect.right() + self._LEGEND_PAD_L
        y0 = rect.top()
        avail_w = max(24, self.width() - x0 - 2)
        text_w = max(12, min(self._legend_text_width(labels),
                             avail_w - line_w - gap))
        max_rows = max(1, int(rect.height() // row_h))
        if len(labels) > max_rows:
            keep = max(1, max_rows - 1)
            shown, rest = labels[:keep], len(labels) - keep
        else:
            shown, rest = labels, 0

        styles = self._props.get('channel_styles', {})
        for i, lbl in enumerate(shown):
            cy = y0 + i * row_h
            st = styles.get(lbl, {})
            color = QColor(st['color']) if st.get('color') else PALETTE[i % len(PALETTE)]
            p.setPen(QPen(color, 1.5))
            p.drawLine(int(x0), int(cy + row_h / 2),
                       int(x0 + line_w), int(cy + row_h / 2))
            p.setPen(QColor('#2a3542'))
            p.drawText(QRectF(x0 + line_w + gap, cy - 1, text_w + 4, row_h + 1),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(lbl, Qt.ElideRight, text_w))
        if rest:
            cy = y0 + len(shown) * row_h
            p.setPen(QColor('#8c96a5'))
            p.drawText(QRectF(x0, cy - 1, text_w + line_w + gap + 4, row_h + 1),
                       Qt.AlignLeft | Qt.AlignVCenter, f'… +{rest}')

    def _draw_bar(self, p: QPainter, rect: QRectF):
        data = self._data
        x, y = data['x'], data['y']
        ymin = data.get('ymin', 0.0)
        valid = pd.notna(x) & pd.notna(y)
        x, y = x[valid], y[valid]
        if len(x) == 0:
            self._draw_empty(p, self.width(), self.height())
            return
        ymax = data.get('ymax')
        y_lo, y_hi, _ = self._nice_limits(float(y.min()), float(y.max()),
                                          hard_min=ymin, hard_max=ymax)
        n = len(x)
        bar_w = rect.width() / max(n, 1) * 0.7
        pen = QPen(QColor('#2c7be5'), 0.5)
        brush = QColor('#2c7be5')
        p.setPen(pen)
        p.setBrush(brush)
        for i, (xi, yi) in enumerate(zip(x, y)):
            cx = rect.left() + rect.width() * (i + 0.5) / n
            y0 = rect.bottom() - rect.height() * (y_lo - y_lo) / (y_hi - y_lo)
            y1 = rect.bottom() - rect.height() * (float(yi) - y_lo) / (y_hi - y_lo)
            p.drawRect(QRectF(cx - bar_w / 2, y1, bar_w, y0 - y1))
        # 简单轴
        self._draw_axes(p, rect, 0, n, y_lo, y_hi,
                        data.get('xlabel', ''), data.get('ylabel', ''),
                        data.get('xtick_fmt'), show_grid=self._show_grid)

    def _draw_histogram(self, p: QPainter, rect: QRectF):
        """数值边界直方图 + 可选叠加曲线 + 图下方图例。"""
        data = self._data
        edges = np.asarray(data.get('edges'), dtype=float) \
            if data.get('edges') is not None else np.array([])
        counts = np.asarray(data.get('counts'), dtype=float) \
            if data.get('counts') is not None else np.array([])
        if len(edges) < 2 or len(counts) == 0 or not np.isfinite(counts).any():
            self._draw_empty(p, self.width(), self.height())
            return
        x_lo_full = float(edges[0])
        x_hi_full = float(edges[-1])
        if x_hi_full <= x_lo_full:
            x_hi_full = x_lo_full + 1.0
        y_lo_full, y_hi_full, _ = self._nice_limits(
            0.0, float(np.nanmax(counts)), hard_min=data.get('ymin', 0))
        self._set_data_bounds(x_lo_full, x_hi_full, y_lo_full, y_hi_full)
        x_lo, x_hi = self._effective_range(x=True)
        y_lo, y_hi = self._effective_range(x=False)
        self._draw_axes(p, rect, x_lo, x_hi, y_lo, y_hi,
                        data.get('xlabel', ''), data.get('ylabel', ''),
                        data.get('xtick_fmt'), show_grid=self._show_grid,
                        thousands_y=data.get('thousands', False))

        denom_x = (x_hi - x_lo) or 1.0
        denom_y = (y_hi - y_lo) or 1.0

        def px(xv):
            return rect.left() + rect.width() * (float(xv) - x_lo) / denom_x

        def py(yv):
            return rect.bottom() - rect.height() * (float(yv) - y_lo) / denom_y

        p.setRenderHint(QPainter.Antialiasing, False)
        p.setClipRect(rect)
        bar_color = data.get('bar_color')
        if bar_color:
            bc = QColor(bar_color)
            bar_pen = QPen(bc.darker(125), 0.8)
            bar_brush = bc
        else:
            bar_pen = QPen(QColor('#123c6b'), 0.8)
            bar_brush = QColor('#1a4e8a')
        p.setPen(bar_pen)
        p.setBrush(bar_brush)
        for i in range(len(counts)):
            if not np.isfinite(counts[i]) or counts[i] <= 0:
                continue
            x0 = max(px(edges[i]), rect.left())
            x1 = min(px(edges[i + 1]), rect.right())
            if x1 <= x0:
                continue
            y1 = max(py(counts[i]), rect.top())
            p.drawRect(QRectF(x0, y1, x1 - x0, rect.bottom() - y1))

        overlay = data.get('overlay')
        if overlay is not None:
            ox, oy, ocolor, _olabel = overlay
            ox = np.asarray(ox, dtype=float)
            oy = np.asarray(oy, dtype=float)
            m = np.isfinite(ox) & np.isfinite(oy)
            if m.any():
                p.setRenderHint(QPainter.Antialiasing, True)
                p.setPen(QPen(QColor(ocolor), 1.4))
                p.setBrush(Qt.NoBrush)
                pts = [QPointF(float(px(a)), float(py(b)))
                       for a, b in zip(ox[m], oy[m])]
                p.drawPolyline(pts)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setClipping(False)

        # 图例：x 轴标题下方一行，居中
        legend = data.get('legend') or []
        if not legend:
            return
        p.setFont(QFont('Microsoft YaHei', 8))
        fm = p.fontMetrics()
        items = []
        for color, label in legend:
            items.append((color, str(label),
                          18 + 5 + fm.horizontalAdvance(str(label))))
        gap = 18
        total = sum(w for _, _, w in items) + gap * (len(items) - 1)
        cx = rect.left() + (rect.width() - total) / 2
        ly = rect.bottom() + 38
        p.setPen(QColor('#4a5460'))
        for color, label, w in items:
            p.setPen(QPen(QColor(color), 1.6))
            p.drawLine(int(cx), int(ly + 7), int(cx + 18), int(ly + 7))
            p.setPen(QColor('#4a5460'))
            p.drawText(QRectF(cx + 23, ly, w - 23, 16),
                       Qt.AlignLeft | Qt.AlignVCenter, label)
            cx += w + gap

    def _draw_scatter(self, p: QPainter, rect: QRectF):
        data = self._data
        x, y = data['x'], data['y']
        ymin = data.get('ymin')
        valid = pd.notna(x) & pd.notna(y)
        x, y = x[valid], y[valid]
        if len(x) == 0:
            self._draw_empty(p, self.width(), self.height())
            return
        ymax = data.get('ymax')
        xtick_fmt = data.get('xtick_fmt')
        x_lo_full, x_hi_full = self._tight_limits(float(x.min()), float(x.max()))
        if xtick_fmt == 'hour':
            x_lo_full, x_hi_full = 0.0, 24.0
        elif xtick_fmt == 'month':
            x_lo_full, x_hi_full = 1.0, 12.0
        else:
            # 散点 x 轴取整刻度：范围上下取整到 1/2/5 步长，避免 1.67 这类刻度
            raw = (x_hi_full - x_lo_full) / 5 or 1.0
            exp10 = 10 ** math.floor(math.log10(raw))
            frac = raw / exp10
            x_step = exp10 * (1 if frac <= 1 else 2 if frac <= 2 else 5)
            x_lo_full = math.floor(x_lo_full / x_step) * x_step
            x_hi_full = math.ceil(x_hi_full / x_step) * x_step
        y_lo_full, y_hi_full, _ = self._nice_limits(float(y.min()), float(y.max()),
                                                    hard_min=ymin, hard_max=ymax)
        self._set_data_bounds(x_lo_full, x_hi_full, y_lo_full, y_hi_full)

        x_lo, x_hi = self._effective_range(x=True)
        y_lo, y_hi = self._effective_range(x=False)
        self._draw_axes(p, rect, x_lo, x_hi, y_lo, y_hi,
                        data.get('xlabel', ''), data.get('ylabel', ''),
                        xtick_fmt, show_grid=self._show_grid,
                        xtick_step=data.get('xtick_step'))
        r = 2.5
        # 点数过多时等间隔抽样后逐点绘制，避免上万次 Python 级调用卡界面
        xs, ys = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        colors = data.get('point_colors')
        if colors is not None:
            colors = np.asarray(colors, dtype=object)
            if len(colors) == len(x):
                colors = colors[valid]
            else:
                colors = None
        if xs.size > 10000:
            step = int(np.ceil(xs.size / 10000))
            xs, ys = xs[::step], ys[::step]
            if colors is not None:
                colors = colors[::step]
        px_arr = rect.left() + rect.width() * (xs - x_lo) / ((x_hi - x_lo) or 1.0)
        py_arr = rect.bottom() - rect.height() * (ys - y_lo) / ((y_hi - y_lo) or 1.0)
        p.setRenderHint(QPainter.Antialiasing, False)
        if colors is None:
            color = PALETTE[0]
            p.setPen(QPen(color, 1.2))
            p.setBrush(color)
            for pxi, pyi in zip(px_arr, py_arr):
                p.drawEllipse(QPointF(float(pxi), float(pyi)), r, r)
        else:
            # 按颜色分组绘制（Color code by flag / data column）
            for c in np.unique(colors):
                m = colors == c
                col = QColor(str(c))
                p.setPen(QPen(col, 1.2))
                p.setBrush(col)
                for pxi, pyi in zip(px_arr[m], py_arr[m]):
                    p.drawEllipse(QPointF(float(pxi), float(pyi)), r, r)
        p.setRenderHint(QPainter.Antialiasing, True)
        if data.get('regression'):
            a, b = np.polyfit(x.astype(float), y.astype(float), 1)
            p.setPen(QPen(QColor('#e74c3c'), 1.5))
            px1, py1 = self._data_to_pixel(x_lo, a * x_lo + b, rect)
            px2, py2 = self._data_to_pixel(x_hi, a * x_hi + b, rect)
            p.drawLine(QPointF(px1, py1), QPointF(px2, py2))

        # 色带图例：绘图区右侧竖排色块 + 边界标签（Color code by data column）
        cbar = data.get('colorbar')
        if cbar:
            bw_ = 16
            x0 = rect.right() + 10
            top = rect.top() + 2
            bh = (rect.height() - 4) / len(cbar)
            p.setFont(QFont('Microsoft YaHei', 7))
            for i, (label, color) in enumerate(cbar):
                p.setPen(QPen(QColor('#8c96a5'), 0.6))
                p.setBrush(QColor(color))
                p.drawRect(QRectF(x0, top + i * bh, bw_, bh))
                p.setPen(QColor('#4a5460'))
                p.drawText(QRectF(x0 + bw_ + 3, top + i * bh, 48, bh),
                           Qt.AlignLeft | Qt.AlignVCenter, str(label))

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

    @staticmethod
    def _parse_color(c, default):
        # None 或 ''（默认"自动取调色板"）按 default 处理，避免空串被当成黑色
        if not c:
            return default
        if isinstance(c, QColor):
            return c
        try:
            return QColor(str(c))
        except Exception:
            return default

    @staticmethod
    def _qt_pen_style(style: str):
        mapping = {
            'solid': Qt.SolidLine,
            'dash': Qt.DashLine,
            'dot': Qt.DotLine,
            'dash_dot': Qt.DashDotLine,
            'dash_dot_dot': Qt.DashDotDotLine,
        }
        return mapping.get(style, Qt.SolidLine)

    def _draw_markers(self, p: QPainter, cx: float, cy: float,
                      pts: list[tuple], marker: str, size: float, color: QColor):
        px = np.array([cx + r * math.cos(ang) for ang, r, _ in pts])
        py = np.array([cy - r * math.sin(ang) for ang, r, _ in pts])
        self._draw_marker_points(p, px, py, marker, size, color)

    def _draw_marker_points(self, p: QPainter, px: np.ndarray, py: np.ndarray,
                            marker: str, size: float, color: QColor):
        p.setPen(QPen(color, 1))
        p.setBrush(color)
        s2 = size / 2.0
        for x, y in zip(px, py):
            x, y = float(x), float(y)
            if marker == 'circle':
                p.drawEllipse(QPointF(x, y), s2, s2)
            elif marker == 'square':
                p.drawRect(QRectF(x - s2, y - s2, size, size))
            elif marker == 'diamond':
                poly = QPolygonF([
                    QPointF(x, y - s2), QPointF(x + s2, y),
                    QPointF(x, y + s2), QPointF(x - s2, y),
                ])
                p.drawPolygon(poly)
            elif marker == 'triangle':
                h = size * 0.866
                poly = QPolygonF([
                    QPointF(x, y - h * 2 / 3),
                    QPointF(x + s2, y + h / 3),
                    QPointF(x - s2, y + h / 3),
                ])
                p.drawPolygon(poly)
            elif marker == 'cross':
                p.drawLine(QPointF(x - s2, y), QPointF(x + s2, y))
                p.drawLine(QPointF(x, y - s2), QPointF(x, y + s2))
            elif marker == 'x':
                p.drawLine(QPointF(x - s2, y - s2), QPointF(x + s2, y + s2))
                p.drawLine(QPointF(x + s2, y - s2), QPointF(x - s2, y + s2))
            else:
                p.drawEllipse(QPointF(x, y), s2, s2)

    def _draw_table(self, p: QPainter, rect: QRectF):
        data = self._data
        rows = data['rows']
        headers = data['headers']
        n_rows = len(rows)
        n_cols = len(headers)
        if n_cols == 0:
            return
        col_w = rect.width() / n_cols
        row_h = min(22, rect.height() / max(n_rows + 1, 2))
        p.setFont(QFont('Microsoft YaHei', 9))
        # 表头
        p.setPen(QPen(QColor('#8c96a5'), 0.5))
        p.setBrush(QColor('#e4e8ee'))
        for c, h in enumerate(headers):
            x = rect.left() + c * col_w
            p.drawRect(QRectF(x, rect.top(), col_w, row_h))
            p.setPen(QColor('#2a3542'))
            p.drawText(QRectF(x + 4, rect.top(), col_w - 8, row_h),
                       Qt.AlignLeft | Qt.AlignVCenter, h)
            p.setPen(QPen(QColor('#8c96a5'), 0.5))
        # 行
        for r, row in enumerate(rows):
            y = rect.top() + (r + 1) * row_h
            for c, v in enumerate(row):
                x = rect.left() + c * col_w
                p.drawRect(QRectF(x, y, col_w, row_h))
                p.setPen(QColor('#4a5460'))
                txt = str(v) if v is not None else ''
                p.drawText(QRectF(x + 4, y, col_w - 8, row_h),
                           Qt.AlignLeft | Qt.AlignVCenter, txt)
                p.setPen(QPen(QColor('#8c96a5'), 0.5))

    # ---- 热力图 / 箱线图 ----
    @staticmethod
    def cmap_color(frac: float, name: str = 'blue') -> QColor:
        """按色带名在 [0,1] 上取色（线性插值）。"""
        stops = CMAPS.get(name, CMAPS['blue'])
        if not math.isfinite(frac):
            return QColor('#e3e7ec')
        frac = min(max(frac, 0.0), 1.0)
        if len(stops) == 1:
            return QColor(stops[0])
        pos = frac * (len(stops) - 1)
        i = int(math.floor(pos))
        if i >= len(stops) - 1:
            return QColor(stops[-1])
        t = pos - i
        c0, c1 = QColor(stops[i]), QColor(stops[i + 1])
        return QColor(int(c0.red() + (c1.red() - c0.red()) * t),
                      int(c0.green() + (c1.green() - c0.green()) * t),
                      int(c0.blue() + (c1.blue() - c0.blue()) * t))

    def _draw_frame_y(self, p: QPainter, rect: QRectF, y_lo: float,
                      y_hi: float, ylabel: str = ''):
        """只画 Y 轴刻度/网格/外框（X 轴为类别轴，由调用方自绘标签）。"""
        p.setPen(QPen(QColor('#8c96a5'), 0.8))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)
        p.setFont(QFont('Microsoft YaHei', 8))
        span = (y_hi - y_lo) or 1.0
        for t in np.linspace(y_lo, y_hi, 6):
            y = rect.bottom() - rect.height() * (t - y_lo) / span
            p.setPen(QPen(QColor('#d5dbe2'), 0.5))
            p.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            p.setPen(QColor('#4a5460'))
            p.drawText(QRectF(rect.left() - 54, y - 8, 50, 16),
                       Qt.AlignRight | Qt.AlignVCenter, self._fmt_tick(t))
        if ylabel:
            p.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
            p.save()
            p.translate(rect.left() - 42, rect.top() + rect.height() / 2)
            p.rotate(-90)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(ylabel)
            p.drawText(QRectF(-tw / 2, -8, tw, 16), Qt.AlignCenter, ylabel)
            p.restore()

    def _draw_colorbar(self, p: QPainter, rect: QRectF, vmin: float,
                       vmax: float, cmap: str, unit: str = ''):
        """在绘图区右侧绘制竖向色标。"""
        bx = rect.right() + 18
        bw = 13.0
        bh = min(rect.height() * 0.78, 240.0)
        by = rect.top() + (rect.height() - bh) / 2
        steps = max(int(bh), 24)
        p.setPen(Qt.NoPen)
        for i in range(steps):
            frac = 1.0 - i / (steps - 1)
            p.setBrush(self.cmap_color(frac, cmap))
            p.drawRect(QRectF(bx, by + bh * i / steps, bw, bh / steps + 0.8))
        p.setPen(QPen(QColor('#8c96a5'), 0.7))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(bx, by, bw, bh))
        p.setFont(QFont('Microsoft YaHei', 8))
        p.setPen(QColor('#4a5460'))
        for i in range(5):
            frac = i / 4
            v = vmin + (vmax - vmin) * frac
            y = by + bh * (1 - frac)
            p.drawLine(int(bx + bw), int(y), int(bx + bw + 3), int(y))
            p.drawText(QRectF(bx + bw + 5, y - 7, 52, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, self._fmt_tick(v))
        if unit:
            p.setFont(QFont('Microsoft YaHei', 8, QFont.Bold))
            p.drawText(QRectF(bx - 6, by - 18, 70, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, unit)

    def _draw_heatmap(self, p: QPainter, rect: QRectF):
        data = self._data
        m = data['matrix']
        if m.ndim != 2 or m.size == 0:
            self._draw_empty(p, self.width(), self.height())
            return
        finite = m[np.isfinite(m)]
        if finite.size == 0:
            self._draw_empty(p, self.width(), self.height())
            return
        n_rows, n_cols = m.shape
        vmin = data.get('vmin')
        vmax = data.get('vmax')
        vmin = float(finite.min()) if vmin is None else float(vmin)
        vmax = float(finite.max()) if vmax is None else float(vmax)
        if vmax - vmin < 1e-12:
            vmax = vmin + 1.0
        cmap = data.get('cmap', 'blue')
        cw = rect.width() / n_cols
        chh = rect.height() / n_rows

        # 色块
        p.setPen(Qt.NoPen)
        for r in range(n_rows):
            y = rect.top() + r * chh
            for c in range(n_cols):
                v = m[r, c]
                if np.isfinite(v):
                    frac = (float(v) - vmin) / (vmax - vmin)
                    p.setBrush(self.cmap_color(frac, cmap))
                else:
                    p.setBrush(QColor('#e3e7ec'))     # 缺测
                p.drawRect(QRectF(rect.left() + c * cw, y,
                                  cw + 0.7, chh + 0.7))
        p.setPen(QPen(QColor('#8c96a5'), 0.8))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)

        # 行标签（空间不足时抽样）
        p.setFont(QFont('Microsoft YaHei', 8))
        p.setPen(QColor('#4a5460'))
        ylabels = data.get('ylabels') or []
        row_step = max(1, int(math.ceil(n_rows / max(1, rect.height() // 13))))
        for r in range(0, n_rows, row_step):
            if r >= len(ylabels):
                break
            y = rect.top() + (r + 0.5) * chh
            p.drawText(QRectF(rect.left() - 250, y - 8, 246, 16),
                       Qt.AlignRight | Qt.AlignVCenter, str(ylabels[r]))

        # 列标签（按可用宽度抽样）
        xlabels = data.get('xlabels') or []
        if xlabels:
            max_lbl = max(1, int(rect.width() // 72))
            col_step = max(1, int(math.ceil(n_cols / max_lbl)))
            for c in range(0, n_cols, col_step):
                if c >= len(xlabels):
                    break
                x = rect.left() + (c + 0.5) * cw
                p.setPen(QPen(QColor('#8c96a5'), 0.6))
                p.drawLine(int(x), int(rect.bottom()),
                           int(x), int(rect.bottom() + 3))
                p.setPen(QColor('#4a5460'))
                p.drawText(QRectF(x - 44, rect.bottom() + 4, 88, 15),
                           Qt.AlignCenter, str(xlabels[c]))

        # 轴标题
        if data.get('xlabel'):
            p.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
            p.drawText(QRectF(rect.left(), rect.bottom() + 22,
                              rect.width(), 18),
                       Qt.AlignCenter, data['xlabel'])
        if data.get('ylabel'):
            p.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
            p.save()
            p.translate(14, rect.top() + rect.height() / 2)
            p.rotate(-90)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(data['ylabel'])
            p.drawText(QRectF(-tw / 2, -8, tw, 16), Qt.AlignCenter,
                       data['ylabel'])
            p.restore()

        self._draw_colorbar(p, rect, vmin, vmax, cmap, data.get('unit', ''))

    def _draw_box(self, p: QPainter, rect: QRectF):
        data = self._data
        groups = [(lbl, st) for lbl, st in data.get('groups', [])
                  if st and math.isfinite(st.get('med', float('nan')))]
        if not groups:
            self._draw_empty(p, self.width(), self.height())
            return
        lo = min(float(st['min']) for _, st in groups)
        hi = max(float(st['max']) for _, st in groups)
        y_lo, y_hi, _ = self._nice_limits(lo, hi)
        self._draw_frame_y(p, rect, y_lo, y_hi, data.get('ylabel', ''))

        n = len(groups)
        slot = rect.width() / n
        bw = min(slot * 0.55, 36.0)
        span = (y_hi - y_lo) or 1.0

        def ypix(v: float) -> float:
            return rect.bottom() - rect.height() * (float(v) - y_lo) / span

        lbl_step = max(1, int(math.ceil(n / max(1, rect.width() // 56))))
        for i, (label, st) in enumerate(groups):
            cx = rect.left() + slot * (i + 0.5)
            # 须线（上下缘）
            p.setPen(QPen(QColor('#4a5460'), 1.0))
            p.drawLine(QPointF(cx, ypix(st['max'])), QPointF(cx, ypix(st['q3'])))
            p.drawLine(QPointF(cx, ypix(st['q1'])), QPointF(cx, ypix(st['min'])))
            cap = bw * 0.3
            p.drawLine(QPointF(cx - cap, ypix(st['max'])),
                       QPointF(cx + cap, ypix(st['max'])))
            p.drawLine(QPointF(cx - cap, ypix(st['min'])),
                       QPointF(cx + cap, ypix(st['min'])))
            # 箱体（Q1~Q3）
            top, bot = ypix(st['q3']), ypix(st['q1'])
            p.setPen(QPen(QColor('#1f5fae'), 1.0))
            p.setBrush(QColor(44, 123, 229, 110))
            p.drawRect(QRectF(cx - bw / 2, top, bw, max(bot - top, 1.0)))
            # 中位线
            p.setPen(QPen(QColor('#12457f'), 1.6))
            ym = ypix(st['med'])
            p.drawLine(QPointF(cx - bw / 2, ym), QPointF(cx + bw / 2, ym))
            # 均值点
            mean = st.get('mean', float('nan'))
            if data.get('show_mean', True) and math.isfinite(mean):
                p.setPen(QPen(QColor('#e74c3c'), 1.0))
                p.setBrush(QColor('#e74c3c'))
                p.drawEllipse(QPointF(cx, ypix(mean)), 2.6, 2.6)
            # 类别标签
            if i % lbl_step == 0:
                p.setPen(QColor('#4a5460'))
                p.setFont(QFont('Microsoft YaHei', 8))
                p.setBrush(Qt.NoBrush)
                p.drawText(QRectF(cx - slot / 2, rect.bottom() + 4,
                                  max(slot, 40), 16),
                           Qt.AlignCenter, str(label))
        if data.get('xlabel'):
            p.setPen(QColor('#4a5460'))
            p.setFont(QFont('Microsoft YaHei', 9, QFont.Bold))
            p.drawText(QRectF(rect.left(), rect.bottom() + 22,
                              rect.width(), 18),
                       Qt.AlignCenter, data['xlabel'])

    def export_png(self, path: str):
        self.grab().save(path)


# ---------------------------------------------------------------------------
# 图表属性对话框
# ---------------------------------------------------------------------------
class PlotPropertiesDialog(QDialog):
    """图表属性：Axes / Channels / Fonts 三页。"""

    def __init__(self, canvas: PlotCanvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self.setWindowTitle(tr('Properties'))
        self.resize(520, 420)

        data = canvas._data
        props = canvas._props
        self._orig = {
            'title': canvas.title,
            'xlabel': data.get('xlabel', props.get('xlabel', '')),
            'ylabel': data.get('ylabel', props.get('ylabel', '')),
            'y2label': props.get('y2label', ''),
            'xunit': props.get('xunit', ''),
            'yunit': props.get('yunit', ''),
            'y2unit': props.get('y2unit', ''),
            'xaxis_log': props.get('xaxis_log', False),
            'yaxis_log': props.get('yaxis_log', False),
            'y2axis_log': props.get('y2axis_log', False),
            'xaxis_min': props.get('xaxis_min'),
            'xaxis_max': props.get('xaxis_max'),
            'yaxis_min': data.get('ymin', props.get('yaxis_min')),
            'yaxis_max': data.get('ymax', props.get('yaxis_max')),
            'y2axis_min': props.get('y2axis_min'),
            'y2axis_max': props.get('y2axis_max'),
            'grid_major': props.get('grid_major', True),
            'grid_minor': props.get('grid_minor', True),
            'font_size': props.get('font_size', 10),
            'show_grid': getattr(canvas, '_show_grid', True),
        }

        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        self.tabs.addTab(self._build_axes_tab(), tr('Axes'))
        self.tabs.addTab(self._build_channels_tab(), tr('Channels'))
        self.tabs.addTab(self._build_fonts_tab(), tr('Fonts'))

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _build_axes_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        # Labels
        g = QGridLayout()
        g.addWidget(QLabel(tr('Title')), 0, 0)
        self.e_title = QLineEdit(self._orig['title'])
        g.addWidget(self.e_title, 0, 1, 1, 2)

        g.addWidget(QLabel(tr('X axis label')), 1, 0)
        self.e_xlabel = QLineEdit(self._orig['xlabel'])
        g.addWidget(self.e_xlabel, 1, 1)
        g.addWidget(QLabel(tr('Units')), 1, 2)
        self.e_xunit = QLineEdit(self._orig['xunit'])
        g.addWidget(self.e_xunit, 1, 3)

        g.addWidget(QLabel(tr('Y axis label')), 2, 0)
        self.e_ylabel = QLineEdit(self._orig['ylabel'])
        g.addWidget(self.e_ylabel, 2, 1)
        g.addWidget(QLabel(tr('Units')), 2, 2)
        self.e_yunit = QLineEdit(self._orig['yunit'])
        g.addWidget(self.e_yunit, 2, 3)

        g.addWidget(QLabel(tr('Y2 axis label')), 3, 0)
        self.e_y2label = QLineEdit(self._orig['y2label'])
        g.addWidget(self.e_y2label, 3, 1)
        g.addWidget(QLabel(tr('Units')), 3, 2)
        self.e_y2unit = QLineEdit(self._orig['y2unit'])
        g.addWidget(self.e_y2unit, 3, 3)
        v.addLayout(g)

        # 三列轴设置
        h = QHBoxLayout()
        h.addLayout(self._axis_group('X axis', 'x'))
        h.addLayout(self._axis_group('Y axis', 'y'))
        h.addLayout(self._axis_group('Y2 axis', 'y2'))
        v.addLayout(h)
        v.addStretch(1)
        return w

    def _axis_group(self, title: str, prefix: str):
        g = QGridLayout()
        g.addWidget(QLabel(title), 0, 0, 1, 2)
        log = QCheckBox(tr('Logarithmic'))
        log.setChecked(self._orig[f'{prefix}axis_log'])
        g.addWidget(log, 1, 0, 1, 2)
        setattr(self, f'cb_{prefix}_log', log)

        g.addWidget(QLabel(tr('Fix minimum')), 2, 0)
        emin = QLineEdit('' if self._orig[f'{prefix}axis_min'] is None else str(self._orig[f'{prefix}axis_min']))
        emin.setMaximumWidth(60)
        g.addWidget(emin, 2, 1)
        setattr(self, f'e_{prefix}_min', emin)

        g.addWidget(QLabel(tr('Fix maximum')), 3, 0)
        emax = QLineEdit('' if self._orig[f'{prefix}axis_max'] is None else str(self._orig[f'{prefix}axis_max']))
        emax.setMaximumWidth(60)
        g.addWidget(emax, 3, 1)
        setattr(self, f'e_{prefix}_max', emax)

        # 对 Y/Y2 显示 grid 选项
        if prefix != 'x':
            cb_major = QCheckBox(tr('Gridlines at major division'))
            cb_major.setChecked(self._orig['grid_major'])
            g.addWidget(cb_major, 4, 0, 1, 2)
            setattr(self, f'cb_{prefix}_major', cb_major)
            cb_minor = QCheckBox(tr('Gridlines at minor division'))
            cb_minor.setChecked(self._orig['grid_minor'])
            g.addWidget(cb_minor, 5, 0, 1, 2)
            setattr(self, f'cb_{prefix}_minor', cb_minor)
        return g

    def _build_channels_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        # 通道列表
        self.lw_channels = QTableWidget()
        self.lw_channels.setColumnCount(3)
        self.lw_channels.setHorizontalHeaderLabels(['Channel', 'Label', 'Color'])
        self.lw_channels.setSelectionBehavior(QTableWidget.SelectRows)
        self.lw_channels.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        h.addWidget(self.lw_channels, 1)

        # 右侧属性
        form = QGridLayout()
        form.addWidget(QLabel(tr('Label')), 0, 0)
        self.e_ch_label = QLineEdit()
        form.addWidget(self.e_ch_label, 0, 1)
        form.addWidget(QLabel(tr('Color')), 1, 0)
        self.e_ch_color = QLineEdit()
        form.addWidget(self.e_ch_color, 1, 1)
        h.addLayout(form)
        v.addLayout(h)

        # 填充通道
        series = []
        if self._canvas._kind == 'lines':
            series = [s[0] for s in self._canvas._data.get('series', [])]
        elif self._canvas._kind == 'line':
            lbl = self._canvas._data.get('label', '')
            if lbl:
                series = [lbl]
        elif self._canvas._kind == 'polar':
            series = list(self._canvas._data.get('labels') or [])
        self.lw_channels.setRowCount(len(series))
        styles = self._canvas._props.get('channel_styles', {})
        for r, lbl in enumerate(series):
            item = QTableWidgetItem(lbl)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.lw_channels.setItem(r, 0, item)
            self.lw_channels.setItem(r, 1, QTableWidgetItem(styles.get(lbl, {}).get('label', lbl)))
            self.lw_channels.setItem(r, 2, QTableWidgetItem(styles.get(lbl, {}).get('color', '')))
        self.lw_channels.resizeColumnsToContents()
        self.lw_channels.itemSelectionChanged.connect(self._on_channel_select)
        self.e_ch_label.textChanged.connect(self._on_channel_label_changed)
        self.e_ch_color.textChanged.connect(self._on_channel_color_changed)
        return w

    def _on_channel_select(self):
        rows = self.lw_channels.selectedIndexes()
        if not rows:
            return
        r = rows[0].row()
        self.e_ch_label.setText(self.lw_channels.item(r, 1).text())
        self.e_ch_color.setText(self.lw_channels.item(r, 2).text())

    def _on_channel_label_changed(self, text: str):
        rows = self.lw_channels.selectedIndexes()
        if not rows:
            return
        self.lw_channels.item(rows[0].row(), 1).setText(text)

    def _on_channel_color_changed(self, text: str):
        rows = self.lw_channels.selectedIndexes()
        if not rows:
            return
        self.lw_channels.item(rows[0].row(), 2).setText(text)

    def _build_fonts_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(tr('Specify font sizes by entering sizes directly:')))
        g = QGridLayout()
        labels = ['Graph title', 'Axis titles', 'Axis numbers', 'Legend title', 'Legend text']
        self.font_edits = {}
        for r, lbl in enumerate(labels):
            g.addWidget(QLabel(lbl), r, 0)
            e = QSpinBox()
            e.setRange(6, 24)
            e.setValue(self._orig['font_size'])
            g.addWidget(e, r, 1)
            self.font_edits[lbl] = e
        v.addLayout(g)
        v.addStretch(1)
        return w

    def _accept(self):
        self._canvas.title = self.e_title.text()
        data = self._canvas._data
        data['xlabel'] = self.e_xlabel.text()
        data['ylabel'] = self.e_ylabel.text()
        props = self._canvas._props
        props['xlabel'] = self.e_xlabel.text()
        props['ylabel'] = self.e_ylabel.text()
        props['y2label'] = self.e_y2label.text()
        props['xunit'] = self.e_xunit.text()
        props['yunit'] = self.e_yunit.text()
        props['y2unit'] = self.e_y2unit.text()

        def f(edit):
            v = edit.text().strip()
            return float(v) if v else None

        for prefix in ('x', 'y', 'y2'):
            props[f'{prefix}axis_log'] = getattr(self, f'cb_{prefix}_log').isChecked()
            props[f'{prefix}axis_min'] = f(getattr(self, f'e_{prefix}_min'))
            props[f'{prefix}axis_max'] = f(getattr(self, f'e_{prefix}_max'))
        data['ymin'] = props['yaxis_min']
        data['ymax'] = props['yaxis_max']

        # 网格：三页共用一个开关，取 Y axis 的
        props['grid_major'] = getattr(self, 'cb_y_major', QCheckBox()).isChecked()
        props['grid_minor'] = getattr(self, 'cb_y_minor', QCheckBox()).isChecked()
        self._canvas._show_grid = props['grid_major']

        # 字号
        props['font_size'] = self.font_edits['Axis numbers'].value()

        # 通道样式
        styles = props.get('channel_styles', {})
        for r in range(self.lw_channels.rowCount()):
            orig = self.lw_channels.item(r, 0).text()
            label = self.lw_channels.item(r, 1).text()
            color = self.lw_channels.item(r, 2).text().strip()
            styles[orig] = styles.get(orig, {})
            styles[orig]['label'] = label
            if color:
                styles[orig]['color'] = color
        props['channel_styles'] = styles

        self._canvas.update()
        self.accept()


# ---------------------------------------------------------------------------
# 导出图片对话框
# ---------------------------------------------------------------------------
class ExportImageDialog(QDialog):
    """导出图片：对齐原版布局，支持 PNG / 剪贴板，含尺寸、字体、线宽、预览。"""

    def __init__(self, canvas: PlotCanvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self.setWindowTitle(tr('Export Image'))
        self.resize(640, 520)

        lay = QVBoxLayout(self)
        settings = QGridLayout()
        settings.setHorizontalSpacing(12)
        settings.setVerticalSpacing(8)

        # Image dimensions
        settings.addWidget(QLabel(tr('Image dimensions')), 0, 0)
        self.sp_w = QSpinBox()
        self.sp_w.setRange(100, 4000)
        self.sp_w.setValue(800)
        self.sp_h = QSpinBox()
        self.sp_h.setRange(100, 4000)
        self.sp_h.setValue(500)
        h_dim = QHBoxLayout()
        h_dim.addWidget(self.sp_w)
        h_dim.addWidget(QLabel('px by'))
        h_dim.addWidget(self.sp_h)
        h_dim.addWidget(QLabel('px'))
        h_dim.addStretch(1)
        settings.addLayout(h_dim, 0, 1, 1, 3)

        self.cb_actual_dim = QCheckBox(tr('Use actual plot dimensions'))
        settings.addWidget(self.cb_actual_dim, 1, 0, 1, 2)

        # Font size / Line width
        settings.addWidget(QLabel(tr('Font size')), 2, 0)
        self.cb_font = QComboBox()
        self.cb_font.addItems(['Small', 'Normal', 'Large'])
        self.cb_font.setCurrentIndex(1)
        settings.addWidget(self.cb_font, 2, 1)
        settings.addWidget(QLabel(tr('Line width')), 2, 2)
        self.cb_lw = QComboBox()
        self.cb_lw.addItems(['Thin', 'Normal', 'Thick'])
        self.cb_lw.setCurrentIndex(1)
        settings.addWidget(self.cb_lw, 2, 3)

        # Include axis labels
        h_labels = QHBoxLayout()
        self.cb_xlabel = QCheckBox(tr('x-axis'))
        self.cb_xlabel.setChecked(True)
        self.cb_ylabel = QCheckBox(tr('y-axis'))
        self.cb_ylabel.setChecked(True)
        h_labels.addWidget(QLabel(tr('Include axis labels')))
        h_labels.addWidget(self.cb_xlabel)
        h_labels.addWidget(self.cb_ylabel)
        h_labels.addStretch(1)
        settings.addLayout(h_labels, 3, 0, 1, 2)

        # Display
        h_disp = QHBoxLayout()
        self.cb_title = QCheckBox(tr('plot title'))
        self.cb_title.setChecked(True)
        self.cb_legend = QCheckBox(tr('legend'))
        self.cb_legend.setChecked(True)
        h_disp.addWidget(QLabel(tr('Display')))
        h_disp.addWidget(self.cb_title)
        h_disp.addWidget(self.cb_legend)
        h_disp.addStretch(1)
        settings.addLayout(h_disp, 3, 2, 1, 2)

        self.cb_transparent = QCheckBox(tr('Transparent background (for metafiles only)'))
        settings.addWidget(self.cb_transparent, 4, 0, 1, 4)

        lay.addLayout(settings)

        # Preview
        lay.addWidget(QLabel(tr('Image preview')))
        self.preview = QLabel()
        self.preview.setMinimumHeight(260)
        self.preview.setStyleSheet('background-color:#eef1f5; border:1px solid #d5dbe2;')
        self.preview.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.preview, 1)
        self.lbl_scale = QLabel()
        self.lbl_scale.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl_scale)

        for w in (self.cb_actual_dim, self.cb_xlabel, self.cb_ylabel,
                  self.cb_title, self.cb_legend, self.cb_transparent):
            w.stateChanged.connect(self._update_preview)

        # Bottom buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        help_btn = QPushButton(tr('Help'))
        cancel = QPushButton(tr('Cancel'))
        self.cb_export_type = QComboBox()
        self.cb_export_type.addItems(['Copy bitmap to clipboard', 'Save PNG'])
        self.btn_action = QPushButton(tr('Copy'))
        self.btn_action.setObjectName('primaryBtn')
        help_btn.clicked.connect(self._help)
        cancel.clicked.connect(self.reject)
        self.cb_export_type.currentIndexChanged.connect(self._on_type_changed)
        self.btn_action.clicked.connect(self._export)
        btns.addWidget(help_btn)
        btns.addWidget(QLabel(tr('Export type')))
        btns.addWidget(self.cb_export_type)
        btns.addWidget(self.btn_action)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        for w in (self.sp_w, self.sp_h):
            w.valueChanged.connect(self._update_preview)
        for w in (self.cb_font, self.cb_lw, self.cb_export_type):
            w.currentIndexChanged.connect(self._update_preview)

        self._update_preview()

    def _on_type_changed(self, idx: int):
        self.btn_action.setText('Copy' if idx == 0 else 'Save')

    def _update_preview(self):
        if self.cb_actual_dim.isChecked():
            self.sp_w.setValue(self._canvas.width())
            self.sp_h.setValue(self._canvas.height())
        self._canvas.set_export_flags(
            show_title=self.cb_title.isChecked(),
            show_xlabel=self.cb_xlabel.isChecked(),
            show_ylabel=self.cb_ylabel.isChecked(),
            show_legend=self.cb_legend.isChecked(),
        )
        pix = self._canvas.grab()
        self._canvas.reset_export_flags()
        if pix.isNull():
            return
        scaled = pix.scaled(self.preview.width(), self.preview.height(),
                            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(scaled)
        scale = scaled.width() / pix.width() * 100 if pix.width() else 100
        self.lbl_scale.setText(f'Image shown at {scale:.0f}% scale')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()

    def _export(self):
        w, h = self.sp_w.value(), self.sp_h.value()
        bg = QColor('#eef1f5')
        if self.cb_transparent.isChecked():
            bg = Qt.transparent
        self._canvas.set_export_flags(
            show_title=self.cb_title.isChecked(),
            show_xlabel=self.cb_xlabel.isChecked(),
            show_ylabel=self.cb_ylabel.isChecked(),
            show_legend=self.cb_legend.isChecked(),
        )
        from PySide6.QtCore import QPoint
        pix = QPixmap(w, h)
        pix.fill(bg)
        p = QPainter(pix)
        self._canvas.render(p, QPoint(0, 0))
        p.end()
        self._canvas.reset_export_flags()
        typ = self.cb_export_type.currentIndex()
        if typ == 0:
            QApplication.clipboard().setPixmap(pix)
            self.accept()
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, 'Save Image', 'plot.png', 'PNG (*.png);;All files (*.*)')
            if path:
                pix.save(path)
                self.accept()

    def _help(self):
        QMessageBox.information(self, 'Export Image',
                                'Set image dimensions and options, then copy to clipboard or save as PNG.')
