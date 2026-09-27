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



from ._common import (PALETTE, CMAPS, _coerce_x_axis, _decimate_xy, _root_base)


class CartesianPlotMixin:

    # ---- 图例：位于绘图区右侧外部，纵向单列 ----
    _LEGEND_FONT_PT = 7
    _LEGEND_LINE_W = 10
    _LEGEND_GAP = 5
    _LEGEND_PAD_L = 8     # 绘图区右边框 → 示例线起点
    _LEGEND_PAD_R = 6     # 文字右侧留白
    _LEGEND_ROW_H = 12
    _LEGEND_MAX_TEXT_W = 180

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
