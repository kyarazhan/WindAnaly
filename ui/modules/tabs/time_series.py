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

from ._common import (ts_ordinals, display_name, AnalysisTab)

class TimeSeriesTab(AnalysisTab):
    """时间序列：原版 Windographer 风格。

    布局：顶部 Display 单选按钮；左侧选项列（每个通道 / 全选行前面 3 列复选框，
    分别对应上 / 中 / 下三幅横图）；右侧 1~3 幅堆叠横图（按选中列数自动
    占满 / 均分）；底部时间轴滑块。同一幅图内同类型通道叠加绘制。
    """

    # kind -> (key, 全选标题, 颜色索引, 默认 y 轴单位)
    _GROUPS = [
        ('speed', 'All wind speed', 0, 'm/s'),
        ('dir', 'All wind direction', 1, 'deg'),
        ('temp', 'All temperature', 2, '°C'),
        ('pres', 'All pressure', 3, 'hPa'),
        ('rh', 'All humidity', 4, '%'),
        ('other', 'All other', 5, ''),
    ]
    _KEY_TO_IDX = {t[0]: i for i, t in enumerate(_GROUPS)}
    _NCOL = 3
    _HEIGHT_RE = __import__('re').compile(r'(\d+)m')
    ROLE_ORDER = {'Avg': 0, 'Max': 1, 'Min': 2, 'SD': 3, 'Gust': 4}
    # 复选框列宽（含指示器与点击区），三列间距≈1/2 checkbox 宽度
    _CB_W = 20
    _SPACING = 8
    _COL0_W = _CB_W * 3 + _SPACING * 2   # 三列复选框容器固定宽度

    def __init__(self):
        super().__init__()
        self._channel_boxes: dict[str, list] = {}      # name -> [cb0, cb1, cb2]
        self._all_checkboxes: dict[str, list] = {}     # kind -> [cb0, cb1, cb2]
        self._kind_counts: dict[str, int] = {}          # kind -> 该 kind 通道数
        self.canvases: list = []
        self._ignore_scroll = False
        self._syncing = False
        self._rebuilding = False
        self._shared_x = (None, None)   # 当前共享 X 视图（ordinal）
        self._x_full = (None, None)     # 数据全范围（ordinal）
        self._cur_ds = None
        self._last_built_ds = None      # 上次重建过通道列表的数据集
        self._scroll_units = 10000      # 滑块「文档长度」（虚拟单位）

        # 顶部 Display 工具行 + 筛选条件
        top = QWidget()
        top.setStyleSheet('background-color:#eef1f5;')
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(6, 4, 6, 4)
        top_lay.setSpacing(8)
        top_lay.addWidget(QLabel(tr('Display')))
        self.rb_measured = QRadioButton(tr('Measured Data'))
        self.rb_daily = QRadioButton(tr('Daily Means'))
        self.rb_monthly = QRadioButton(tr('Monthly Means'))
        self.rb_annual = QRadioButton(tr('Annual Means'))
        self.rb_measured.setChecked(True)
        for rb in (self.rb_measured, self.rb_daily, self.rb_monthly, self.rb_annual):
            # 用 clicked 而非 toggled：切换单选只触发 1 次（toggled 会触发 2 次）
            rb.clicked.connect(lambda _c=False: self.refresh())
            top_lay.addWidget(rb)

        sep = QLabel('|')
        sep.setStyleSheet('color:#9aa4ae; margin-left:4px; margin-right:4px;')
        top_lay.addWidget(sep)
        top_lay.addWidget(QLabel(tr('筛选条件')))
        self.cb_date = QCheckBox(tr('日期范围'))
        self.cb_date.setChecked(False)
        top_lay.addWidget(self.cb_date)
        h = QHBoxLayout()
        h.setSpacing(2)
        self.de_from = QLineEdit('2023/7/1')
        self.de_to = QLineEdit('2024/7/1')
        self.de_from.setFixedWidth(70)
        self.de_to.setFixedWidth(70)
        self.de_from.setStyleSheet('padding:0 2px;')
        self.de_to.setStyleSheet('padding:0 2px;')
        h.addWidget(QLabel(tr('从')))
        h.addWidget(self.de_from)
        h.addWidget(QLabel(tr('至')))
        h.addWidget(self.de_to)
        top_lay.addLayout(h)
        top_lay.addStretch(1)

        # 主区域：左侧选项列 + 右侧画布
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setStyleSheet('background-color:#eef1f5;')
        main_splitter.setChildrenCollapsible(True)

        # 左侧：选项列
        self.left_panel = QScrollArea()
        self.left_panel.setWidgetResizable(True)
        self.left_panel.setMinimumWidth(220)
        self.left_panel.setMaximumWidth(360)
        self.left_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_panel.setStyleSheet('background-color:#eef1f5; border:none;')
        lw = QWidget()
        lw.setStyleSheet('background-color:#eef1f5;')
        self.left_inner_layout = lv = QVBoxLayout(lw)
        lv.setContentsMargins(2, 2, 2, 2)
        lv.setSpacing(4)

        # 全选行：每个 kind 一行，checkbox 容器 + 占位 + 标签
        self._all_layout = QVBoxLayout()
        self._all_layout.setContentsMargins(0, 0, 0, 0)
        self._all_layout.setSpacing(2)
        lv.addLayout(self._all_layout)

        # 通道列表：checkbox 容器 + 颜色 + 标签
        self._grid = QVBoxLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(2)
        self._channel_list_widget = QWidget()
        self._channel_list_widget.setLayout(self._grid)
        lv.addWidget(self._channel_list_widget, 1)

        self.left_panel.setWidget(lw)
        main_splitter.addWidget(self.left_panel)

        # 右侧：1~3 幅画布 + 底部滑块
        right_pane = QWidget()
        right_pane.setStyleSheet('background-color:#eef1f5;')
        right_lay = QVBoxLayout(right_pane)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)
        for c in range(self._NCOL):
            cv = PlotCanvas('')
            cv.setMinimumHeight(160)
            cv.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            cv.viewChanged.connect(
                lambda x0, x1, y0, y1, idx=c: self._on_canvas_view(idx, x0, x1, y0, y1))
            self.canvases.append(cv)
            right_lay.addWidget(cv, 1)

        self.scrollbar = QScrollBar(Qt.Horizontal)
        self.scrollbar.setRange(0, 0)
        self.scrollbar.setPageStep(self._scroll_units)
        self.scrollbar.valueChanged.connect(self._on_scrollbar)
        right_lay.addWidget(self.scrollbar)

        main_splitter.addWidget(right_pane)
        main_splitter.setSizes([230, 950])
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)

        # Display 工具行置顶，主 splitter 在下
        outer = QWidget()
        outer.setStyleSheet('background-color:#eef1f5;')
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(4)
        outer_lay.addWidget(top)
        outer_lay.addWidget(main_splitter, 1)
        self._layout.addWidget(outer, 1)

    # ---- 全选 / 通道 辅助 ----
    def _make_all_handler(self, key: str, col: int):
        def handler(state: int):
            checked = state == Qt.Checked.value
            for n, cbs in self._channel_boxes.items():
                if self._channel_kind(n) == key:
                    cb = cbs[col]
                    cb.blockSignals(True)
                    # 勾选 All 时只选中平均值通道；取消时全部不选
                    cb.setChecked(checked and self._channel_role(n) == 'Avg')
                    cb.blockSignals(False)
            self.refresh()
        return handler

    def _channel_role(self, name: str) -> str:
        ds = self.active_dataset()
        if ds is None:
            return ''
        ch = ds.channels.get(name)
        if ch is None:
            return ''
        return getattr(ch, 'role', '') or ''

    def _channel_kind(self, name: str) -> str:
        ds = self.active_dataset()
        if ds is None:
            return 'other'
        ch = ds.channels.get(name)
        if ch is None:
            return 'other'
        kind = getattr(ch, 'kind', '') or ''
        if kind in (KIND_SPEED, KIND_SPEED_SD):
            return 'speed'
        if kind == KIND_DIR:
            return 'dir'
        if kind == KIND_TEMP:
            return 'temp'
        if kind == KIND_PRES:
            return 'pres'
        if kind == KIND_RH:
            return 'rh'
        return 'other'

    def _color_for_channel(self, name: str, kind_idx: int = -1) -> str:
        key = self._channel_kind(name)
        idx = self._KEY_TO_IDX.get(key, 5)
        from ui.modules.plot import PALETTE
        c = QColor(PALETTE[idx % len(PALETTE)])
        if kind_idx >= 0:
            n = self._kind_counts.get(key, 1)
            # 同一 kind 内按索引做明暗渐变：索引 0 最浅，最大最深
            if n > 1:
                L = int(80 - 45 * kind_idx / (n - 1))
                c.setHsl(c.hue(), c.saturation(), L)
        return c.name()

    def _make_checkbox_container(self) -> tuple[QWidget, list]:
        """生成一个固定宽度的三列复选框容器，返回 (widget, [cb0, cb1, cb2])。"""
        w = QWidget()
        w.setFixedWidth(self._COL0_W)
        w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self._SPACING)
        lay.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cbs = []
        for _ in range(self._NCOL):
            cb = QCheckBox()
            cb.setFixedSize(self._CB_W, self._CB_W)
            cb.setStyleSheet('QCheckBox::indicator { width: 14px; height: 14px; }')
            lay.addWidget(cb)
            cbs.append(cb)
        return w, cbs

    def _make_row_widget(self, label: str, key: str | None = None,
                         name: str | None = None, color: str = '',
                         prev: list | None = None) -> QWidget:
        """创建一行：checkbox 容器 + 标签（无颜色方块）。

        All 行：name=None，复选框连接 _make_all_handler。
        通道行：name=通道名，复选框连接 refresh。
        """
        row = QWidget()
        hlay = QHBoxLayout(row)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(10)    # ≈ 1/2 checkbox 宽度
        container, cbs = self._make_checkbox_container()
        if name is not None:
            for c, cb in enumerate(cbs):
                cb.setChecked(prev[c] if prev else False)
                cb.stateChanged.connect(self.refresh)
        else:
            for c, cb in enumerate(cbs):
                cb.setEnabled(False)
                cb.stateChanged.connect(self._make_all_handler(key, c))
        lbl = QLabel(label)
        if color:
            lbl.setStyleSheet(f'color:{color};')
            lbl.setToolTip(label)
        hlay.addWidget(container, 0, Qt.AlignLeft | Qt.AlignVCenter)
        hlay.addWidget(lbl, 1, Qt.AlignLeft | Qt.AlignVCenter)
        if key is not None:
            self._all_checkboxes[key] = cbs
        return row

    def _height_for_channel(self, name: str) -> int:
        m = self._HEIGHT_RE.search(name)
        return int(m.group(1)) if m else 0

    def _role_order(self, name: str) -> int:
        return self.ROLE_ORDER.get(self._channel_role(name), 99)

    def _rebuild_channel_list(self):
        """根据当前数据集重建通道列表，保留勾选状态。"""
        ds = self.active_dataset()
        old = {n: [cb.isChecked() for cb in cbs]
               for n, cbs in self._channel_boxes.items()}

        # 清空 All 行和通道行
        for lay in (self._all_layout, self._grid):
            while lay.count():
                item = lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
                del item
        self._channel_boxes.clear()
        self._all_checkboxes.clear()

        if ds is None:
            return

        names = [n for n in ds.df.columns if n in ds.channels]
        order = {t[0]: i for i, t in enumerate(self._GROUPS)}

        # 按 kind 分组，组内按高度低到高，再按角色排序
        kind_names = {}
        for n in names:
            k = self._channel_kind(n)
            kind_names.setdefault(k, []).append(n)
        self._kind_counts = {k: len(v) for k, v in kind_names.items()}
        sorted_names = []
        self._kind_index = {}   # name -> 该 kind 内的排序索引
        for key, _, _, _ in self._GROUPS:
            if key in kind_names:
                group = kind_names[key]
                group.sort(key=lambda n: (
                    order.get(self._channel_kind(n), 99),
                    self._height_for_channel(n),
                    self._role_order(n),
                    n.lower(),
                ))
                for i, n in enumerate(group):
                    self._kind_index[n] = i
                sorted_names.extend(group)
        names = sorted_names

        # 首次根据最长通道名精确固定左侧宽度（All 标题允许截断，通道名必须完整）
        if names and not getattr(self, '_left_width_fixed', False):
            fm = QFontMetrics(self.font())
            max_text = max(fm.horizontalAdvance(display_name(n)) for n in names)
            # 容器 + 与复选框 1/2 宽度的间距 + 文字 + 边距
            desired = self._COL0_W + 10 + max_text + 4
            self.left_panel.setFixedWidth(max(220, min(320, desired)))
            self._left_width_fixed = True

        # 重建 All 行
        for key, title, _, _ in self._GROUPS:
            row = self._make_row_widget(title, key=key)
            self._all_layout.addWidget(row)

        # 重建通道行
        for n in names:
            default_speed_avg = (self._channel_kind(n) == 'speed'
                                 and self._channel_role(n) == 'Avg')
            prev = old.get(n, [default_speed_avg, False, False])
            color = self._color_for_channel(n, self._kind_index.get(n, 0))
            row = self._make_row_widget(display_name(n), name=n,
                                        color=color, prev=prev)
            self._grid.addWidget(row)
            # 取出该行容器中的 3 个 checkbox
            container = row.layout().itemAt(0).widget()
            cbs = [container.layout().itemAt(i).widget()
                   for i in range(container.layout().count())
                   if isinstance(container.layout().itemAt(i).widget(), QCheckBox)]
            self._channel_boxes[n] = cbs

        # 同步全选框：该 kind 下 Avg 通道在列 c 是否全选
        for key, _, _, _ in self._GROUPS:
            avg_names = [n for n in names
                         if self._channel_kind(n) == key
                         and self._channel_role(n) == 'Avg']
            for c in range(self._NCOL):
                all_cb = self._all_checkboxes[key][c]
                all_cb.blockSignals(True)
                if avg_names:
                    all_cb.setChecked(
                        all(self._channel_boxes[n][c].isChecked() for n in avg_names))
                    all_cb.setEnabled(True)
                else:
                    all_cb.setChecked(False)
                    all_cb.setEnabled(False)
                all_cb.blockSignals(False)

    # ---- 绘制 ----
    def refresh(self):
        ds = self.active_dataset()
        if ds is not self._cur_ds:
            self._cur_ds = ds
            self._shared_x = (None, None)
            self._x_full = (None, None)
        # 仅在数据集变化（或列表尚未建立）时重建通道行。
        # 勾选状态本来就存在复选框里，反复重建 58 行控件是卡顿来源之一。
        if ds is not self._last_built_ds or not self._channel_boxes:
            self._rebuild_channel_list()
            self._last_built_ds = ds

        if ds is None or ds.df.empty:
            for c in range(self._NCOL):
                self.canvases[c].clear(tr('未载入数据集') if ds is None
                                        else tr('该日期范围无数据'))
                self.canvases[c].setVisible(c == 0)
            self.scrollbar.setEnabled(False)
            return

        # 按列收集通道
        col_channels = {c: [] for c in range(self._NCOL)}
        for n, cbs in self._channel_boxes.items():
            for c in range(self._NCOL):
                if cbs[c].isChecked():
                    col_channels[c].append(n)

        keep = self._keep_mask(ds)
        agg = self._agg()
        non_neg = {'speed', 'dir', 'pres', 'rh'}
        x_full_lo, x_full_hi = None, None
        active = []

        self._rebuilding = True
        try:
            for c in range(self._NCOL):
                chs = col_channels[c]
                if not chs:
                    self.canvases[c].setVisible(False)
                    continue
                active.append(c)
                self.canvases[c].setVisible(True)
                series_data = []
                channel_styles = {}
                for n in chs:
                    s = self.series(n)
                    if keep is not None:
                        s = s[keep]
                    if agg == 'D':
                        s = s.resample('D').mean()
                    elif agg == 'MS':
                        s = s.resample('MS').mean()
                    elif agg == 'YS':
                        s = s.resample('YS').mean()
                    if len(s.index):
                        x = ts_ordinals(s.index)
                        y = np.asarray(s.values, dtype=float)
                    else:
                        x = np.array([], dtype=float)
                        y = np.array([], dtype=float)
                    label = display_name(n)
                    color = self._color_for_channel(n, self._kind_index.get(n, 0))
                    channel_styles[label] = {'color': color}
                    series_data.append((label, x, y))
                    if len(x):
                        lo = float(x[0]); hi = float(x[-1])
                        x_full_lo = lo if x_full_lo is None else min(x_full_lo, lo)
                        x_full_hi = hi if x_full_hi is None else max(x_full_hi, hi)
                kinds = {self._channel_kind(n) for n in chs}
                ymin = 0.0 if kinds.issubset(non_neg) else None
                ylabel = '数值'
                if len(kinds) == 1:
                    key = next(iter(kinds))
                    for t in self._GROUPS:
                        if t[0] == key:
                            ylabel = t[3] if t[3] else '数值'
                            break
                self.canvases[c]._props['channel_styles'] = channel_styles
                self.canvases[c].plot_lines(series_data, xlabel='',
                                            ylabel=ylabel, xtick_fmt='date',
                                            ymin=ymin)

            if not active:
                self.canvases[0].clear(tr('请选择数据列'))
                self.canvases[0].setVisible(True)
                for c in (1, 2):
                    self.canvases[c].setVisible(False)
                self.scrollbar.setEnabled(False)
                return

            # 数据全范围（真实起止）
            if x_full_lo is not None and x_full_hi is not None:
                self._x_full = (x_full_lo, x_full_hi)
            # 视图越界（切换聚合方式 / 通道变化导致全范围变化）时回到全范围
            if self._x_full[0] is None:
                self._shared_x = (None, None)
            elif (self._shared_x[0] is None
                  or self._shared_x[0] < self._x_full[0] - 1e-9
                  or self._shared_x[1] > self._x_full[1] + 1e-9):
                self._shared_x = self._x_full

            self._apply_shared_x()
            self.scrollbar.setEnabled(True)
        finally:
            self._rebuilding = False

    def _apply_shared_x(self):
        if self._shared_x[0] is None:
            return
        x0, x1 = self._shared_x
        self._syncing = True
        for cv in self.canvases:
            if cv.isVisible():
                cv.set_x_range(x0, x1)
        self._syncing = False
        self._configure_scrollbar()

    def _on_canvas_view(self, idx, x0, x1, y0, y1):
        if self._syncing or self._rebuilding:
            return
        # 仅 X 变化时才同步（Y 缩放各幅图独立）
        if self._shared_x[0] is not None and \
           abs(x0 - self._shared_x[0]) < 1e-9 and \
           abs(x1 - self._shared_x[1]) < 1e-9:
            return
        self._shared_x = (x0, x1)
        self._apply_shared_x()

    def _configure_scrollbar(self):
        """按「文档长度恒定」映射滑块。

        Qt 滑块长度 = pageStep / (max - min + pageStep)。令文档长度恒为 D：
        page = V/S*D、max = D - page，则滑块占比恰好 = 可见跨度 V / 总跨度 S；
        V == S 时 max == min，滑块铺满滑轨（旧实现固定 max=10000，导致
        满量程时滑块只占一半轨道）。
        """
        xlo, xhi = self._x_full
        if xhi is None or xhi <= xlo:
            return
        span = xhi - xlo
        d = self._scroll_units
        cur_lo, cur_hi = self._shared_x
        if cur_lo is None:
            cur_lo, cur_hi = xlo, xhi
        view = max(0.0, min(span, cur_hi - cur_lo))
        page = max(1, min(d, int(round(view / span * d))))
        self.scrollbar.setPageStep(page)
        self.scrollbar.setSingleStep(max(1, page // 10))
        self.scrollbar.setRange(0, d - page)
        val = int(round((cur_lo - xlo) / span * d))
        self._ignore_scroll = True
        self.scrollbar.setValue(max(0, min(d - page, val)))
        self._ignore_scroll = False

    def _on_scrollbar(self, value: int):
        if self._ignore_scroll:
            return
        xlo, xhi = self._x_full
        if xhi is None or xhi <= xlo:
            return
        span = xhi - xlo
        d = self._scroll_units
        page = self.scrollbar.pageStep()
        view_span = page / d * span
        new_lo = xlo + value / d * span
        new_hi = new_lo + view_span
        if new_hi > xhi:
            new_hi = xhi
            new_lo = xhi - view_span
        self._shared_x = (new_lo, new_hi)
        self._apply_shared_x()

    def _agg(self) -> str:
        if self.rb_daily.isChecked():
            return 'D'
        if self.rb_monthly.isChecked():
            return 'MS'
        if self.rb_annual.isChecked():
            return 'YS'
        return 'raw'
