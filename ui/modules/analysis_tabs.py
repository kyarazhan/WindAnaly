"""WindAnaly 的 8 个分析 Tab（Windographer 风格）。

每个 Tab 都是「左侧控制面板 + 右侧绘图/表格区」。
所有 Tab 共享同一个 Project；通过 set_project()/refresh() 更新。
"""

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


# ---------------------------------------------------------------------------
# 1) Summary
# ---------------------------------------------------------------------------
class SummaryTab(AnalysisTab):
    def __init__(self):
        super().__init__()
        # 左侧信息面板：扁平化，与系统背景一致，紧贴右侧不留大缝
        # 宽度按内容自适应（见 _fit_left_panel），中间基本不留额外间隙
        # （左边最长行是日期，右边 y 轴标签“离地高度”与之垂直错位，不会重叠）
        # 用户要求：完全不要滚动条，左侧内容宽度最大值固定
        left = QWidget()
        left.setStyleSheet('background-color: #eef1f5;')
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(6, 6, 6, 6)
        left_lay.setSpacing(12)

        self.info_grid = self._make_section(left_lay, tr('数据集属性'))
        self.env_grid = self._make_section(left_lay, tr('环境条件'))
        self.power_grid = self._make_section(left_lay, tr('风速与功率'))
        self.shear_grid = self._make_section(left_lay, tr('风切变系数'))
        left_lay.addStretch(1)

        # 右侧图表：四个图各占 1/4（每个含自身右侧图例）
        # 使用固定等分的嵌套 QSplitter，不再可拖动
        self.c_shear = PlotCanvas(tr('垂直风切变廓线'))
        self.c_rose = WindRoseWidget(show_toolbar=False)
        self.c_monthly = PlotCanvas(tr('月平均风速'))
        self.c_diurnal = PlotCanvas(tr('日变化风速廓线'))
        # 导出数据文件头（对齐原版英文规范名，独立于屏幕中文标题）
        self.c_shear.export_header = 'Vertical Wind Shear Profile'
        self.c_monthly.export_header = 'Monthly Mean Wind Speeds'
        self.c_diurnal.export_header = 'Diurnal Wind Speed Profile'

        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.addWidget(self.c_shear)
        top_splitter.addWidget(self.c_rose)
        top_splitter.setSizes([500, 500])
        top_splitter.setChildrenCollapsible(False)

        bottom_splitter = QSplitter(Qt.Horizontal)
        bottom_splitter.addWidget(self.c_monthly)
        bottom_splitter.addWidget(self.c_diurnal)
        bottom_splitter.setSizes([500, 500])
        bottom_splitter.setChildrenCollapsible(False)

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(top_splitter)
        right_splitter.addWidget(bottom_splitter)
        right_splitter.setSizes([500, 500])
        right_splitter.setChildrenCollapsible(False)
        right_splitter.setStyleSheet('background-color: #eef1f5;')

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(left)
        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([300, 1000])
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setChildrenCollapsible(True)
        self._layout.addWidget(main_splitter, 1)

        self._left_widget = left
        self._main_splitter = main_splitter

    @staticmethod
    def _panel_gap() -> int:
        """左侧面板与右侧图表之间的额外间隙。

        用户反馈：左边最长行（起始/结束日期）与右边 y 轴标签“离地高度”
        在垂直方向上完全错位，不需要再留两个汉字的宽度。这里只给 0，
        实际可见间隔由 QSplitter 的 handle（约 3~4px）自然提供。
        """
        return 0

    def _fit_left_panel(self):
        """安排一次左面板自适应。

        网格刚填完时 sizeHint 还没反映最终内容，必须等布局稳定后再量测，
        否则会把宽度算小、右侧仍然留大片空白。故延迟到事件循环空闲时执行。
        """
        from PySide6.QtCore import QTimer
        if getattr(self, '_fit_pending', False):
            return
        self._fit_pending = True
        QTimer.singleShot(0, self._do_fit_left_panel)

    def showEvent(self, event):
        # 首帧 QTimer 里 splitter 宽度可能还是 0，显示后再校正一次
        super().showEvent(event)
        self._fit_left_panel()

    def _content_right_edge(self) -> int:
        """左栏最长一行的文字右边缘（相对左栏左边界），作为间隙的度量基准。

        不能拿 widget.sizeHint().width() 当基准：它含左右边距与列间距，
        比真实最长行右边缘宽出十余像素，叠加上预留间隙后会明显偏大。
        """
        widget = getattr(self, '_left_widget', None)
        if widget is None:
            return 0
        lay = widget.layout()
        if lay is not None:
            lay.activate()
        edge = 0
        for lab in widget.findChildren(QLabel):
            if lab.isHidden():
                continue
            edge = max(edge, lab.geometry().x() + lab.sizeHint().width())
        return int(edge) or int(widget.sizeHint().width())

    def _do_fit_left_panel(self):
        """左侧面板按内容自适应：最长行右边缘到右侧图表只留 splitter handle。

        用户反馈：左边最长行（日期）与右边 y 轴标签“离地高度”垂直错位，
        不需要再留两个汉字的宽度。因此额外间隙设为 0，右面板从 handle 之后
        开始，仍可手动拖动分隔条加宽。
        """
        self._fit_pending = False
        widget = getattr(self, '_left_widget', None)
        splitter = getattr(self, '_main_splitter', None)
        if widget is None or splitter is None:
            return
        gap = self._panel_gap()
        total = splitter.width() or self.width()
        # 迭代两轮：首轮按当前布局量测；滚动条出现/消失会改变可用宽度，
        # setSizes 已同步更新子控件 geometry，故第二轮量测即可收敛。
        for _ in range(2):
            content = self._content_right_edge()
            if not content:
                break
            need = int(min(max(content + gap, 200), 600))
            if total - need < 240:
                need = max(200, total - 240)
            splitter.setSizes([need, max(240, total - need)])
        # 固定左栏最大宽度，不再需要 min/max
        widget.setMinimumWidth(200)
        widget.setMaximumWidth(620)

    def refresh(self):
        # 语言切换实时生效：信息区块标题按当前语言重译
        for lbl, title in getattr(self, '_section_labels', []):
            lbl.setText(tr(title))
        self.c_shear.set_title(tr('垂直风切变廓线'))
        self.c_monthly.set_title(tr('月平均风速'))
        self.c_diurnal.set_title(tr('日变化风速廓线'))
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            self._fill_info(None)
            self._fill_env(None, None)
            self._fill_power(None, None, None)
            self._fill_shear(None)
            self.c_shear.clear(tr('未载入数据集'))
            self.c_rose.set_project(None)
            self.c_monthly.clear(tr('未载入数据集'))
            self.c_diurnal.clear(tr('未载入数据集'))
            self._fit_left_panel()
            return

        self._fill_info(ds)
        temp = self.project.selection.get('temp')
        pres = self.project.selection.get('pres')
        t = ds.df[temp].astype(float).mean() if temp and temp in ds.df.columns else None
        p = ds.df[pres].astype(float).mean() if pres and pres in ds.df.columns else None
        rho = self._air_density(t, p) if t is not None and p is not None else None
        self._fill_env(ds, rho)

        # 1. 风切变廓线 + 切变指数
        shear = self._compute_shear(ds)
        self._fill_power(ds, shear, rho)
        if shear is not None:
            profile = shear['profile']
            heights = np.asarray([h for h, _ in profile])
            means = np.asarray([v for _, v in profile])
            pw = np.asarray(shear['power'], dtype=float)
            lg = np.asarray(shear['log'], dtype=float)
            series = [
                ('Measured data', means, heights, 'd'),
                ('Power law fit', pw[:, 1], pw[:, 0]),
                ('Log law fit', lg[:, 1], lg[:, 0]),
            ]
            x_max = float(np.nanmax(np.concatenate([means, pw[:, 1], lg[:, 1]])))
            if x_max <= 5.0:
                x_step = 1.0
            elif x_max <= 10.0:
                x_step = 2.0
            else:
                x_step = float(math.ceil(x_max / 5.0))
            # xtick_step 驱动横轴上限：plot.py 内按刻度对齐，数据恰落边界时再外扩一刻度
            # （如均值最大 4.0 m/s → 横轴到 5.0 m/s）。
            # gap_detect=False：x 轴为风速（非等距），起点处跳变不应被当缺口
            self.c_shear.plot_lines(series, xlabel=tr('平均风速 (m/s)'),
                                    ylabel=tr('离地高度 (m)'), ymin=0,
                                    xtick_step=x_step, gap_detect=False)
            self._fill_shear(shear)
        else:
            self.c_shear.clear(tr('风速层数不足'))
            self._fill_shear(None)

        # 2. wind rose：交给 WindRoseWidget（含控制栏与属性对话框）
        try:
            self.c_rose.set_project(self.project)
        except Exception:
            import traceback
            traceback.print_exc()
            self.c_rose.canvas.clear(tr('风玫瑰计算异常'))

        # 3. monthly mean：绘制所有 Avg 风速层，带图例
        self._plot_multi_speed(ds, self.c_monthly, 'month',
                               xlabel=tr('月份'), ylabel=tr('平均风速 (m/s)'))

        # 4. diurnal：绘制所有 Avg 风速层，带图例
        self._plot_multi_speed(ds, self.c_diurnal, 'hour',
                               xlabel=tr('小时'), ylabel=tr('平均风速 (m/s)'))

        # 左侧面板按内容自适应，中间只留两个汉字间隙
        self._fit_left_panel()

    def _plot_multi_speed(self, ds: Dataset, canvas: PlotCanvas, mode: str,
                          xlabel: str, ylabel: str):
        """绘制所有 Avg 风速通道的月/日变化曲线，用于汇总页图例展示。"""
        cols = []
        for n, ch in ds.channels.items():
            if ch.kind == KIND_SPEED and getattr(ch, 'role', 'Avg') == 'Avg' and n in ds.df.columns:
                cols.append(n)
        if not cols:
            canvas.clear(tr('无风速通道'))
            return
        series = []
        for col in cols:
            s = self.series(col)
            if len(s) == 0:
                continue
            if mode == 'month':
                grouped = s.groupby(s.index.month).mean().reindex(range(1, 13))
                xfmt = 'month'
            else:
                grouped = s.groupby(s.index.hour).mean().reindex(range(24))
                xfmt = 'hour'
            series.append((col, grouped.index.values, grouped.values))
        if not series:
            canvas.clear()
            return
        canvas.plot_lines(series, xlabel=xlabel, ylabel=ylabel,
                          xtick_fmt=xfmt, ymin=0)

    def _make_section(self, parent_layout, title: str) -> QGridLayout:
        """创建扁平化信息区块：无背景/无边框，标题加粗。

        标题 QLabel 存入 self._section_labels，refresh 时按当前语言
        重新 tr()，实现语言切换实时生效。"""
        w = QWidget()
        w.setStyleSheet('background-color: #eef1f5;')
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        lbl = QLabel(tr(title))
        lbl.setStyleSheet('font-weight: bold; color: #2a3542; font-size: 13px;')
        v.addWidget(lbl)
        if not hasattr(self, '_section_labels'):
            self._section_labels = []
        self._section_labels.append((lbl, title))
        grid = QGridLayout()
        grid.setContentsMargins(2, 0, 2, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        # 键列固定宽度，值列自适应剩余宽度并自动换行
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        parent_layout.addWidget(w)
        return grid

    def _fill_grid(self, grid: QGridLayout, rows: list[tuple[str, str]],
                   nowrap_keys: set[str] | None = None):
        """清空并填充键值网格；键 90px，值自动换行且不溢出。

        nowrap_keys 中的键对应的值不自动换行（用于日期时间等需要保持一行的值）。
        """
        self._clear_grid(grid)
        nowrap_keys = nowrap_keys or set()
        if not rows:
            lbl = QLabel(tr('无数据'))
            lbl.setStyleSheet('color: #9aa4ae;')
            grid.addWidget(lbl, 0, 0, 1, 2)
            return
        for r, (k, v) in enumerate(rows):
            kl = QLabel(tr(k))
            kl.setStyleSheet('color: #5a6573;')
            kl.setFixedWidth(90)
            vl = QLabel(v)
            vl.setStyleSheet('color: #2a3542;')
            # 指定键不换行，使日期时间能完整显示在一行
            vl.setWordWrap(k not in nowrap_keys)
            vl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            grid.addWidget(kl, r, 0, alignment=Qt.AlignLeft | Qt.AlignTop)
            grid.addWidget(vl, r, 1, alignment=Qt.AlignLeft | Qt.AlignTop)

    def _clear_grid(self, grid: QGridLayout):
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    _INFO_FIELDS = [
        ('纬度', ''),
        ('经度', ''),
        ('海拔', ''),
        ('起始日期', ''),
        ('结束日期', ''),
        ('持续时长', ''),
        ('时间步长', ''),
        ('数据点数', ''),
        ('静风阈值', '0 m/s'),
    ]
    _ENV_FIELDS = [
        ('平均气温', ''),
        ('平均气压', ''),
        ('平均空气密度', ''),
        ('空气密度比', ''),
    ]
    _POWER_FIELDS = [
        ('平均风速', ''),
        ('功率密度', ''),
        ('风功率等级', ''),
    ]
    _SHEAR_FIELDS = [
        ('参考高度范围', ''),
        ('风切变指数 α', ''),
        ('拟合优度 R²', ''),
        ('地表粗糙度', ''),
        ('粗糙度等级', ''),
        ('有效高度层数', ''),
    ]

    # QDoubleSpinBox 默认范围边界： lat=90, lon=180, elevation=9000。
    # 当导入流程未正确回填经纬度/海拔时，这些值会作为 NaN 的 clamp 结果出现，
    #  SummaryTab 里应识别为非法占位值并显示为空，避免展示假数据。
    _BOGUS_COORDS = {
        'lat': {90.0, -90.0},
        'lon': {180.0, -180.0},
        'elevation': {9000.0, -500.0},
    }

    def _fill_info(self, ds: Dataset | None):
        if ds is None:
            self._fill_grid(self.info_grid, [(k, 'n/a') for k, _ in self._INFO_FIELDS])
            return
        a = getattr(ds, 'attrs', {})

        def _geo(key):
            v = a.get(key)
            if v is None:
                return None
            try:
                fv = float(v)
            except Exception:
                return None
            if fv in self._BOGUS_COORDS.get(key, set()):
                return None
            return fv

        lat = _geo('lat')
        lon = _geo('lon')
        elev = _geo('elevation')

        # 日期时间统一格式化，避免 str(Timestamp) 在不同 pandas 版本下换行
        def _fmt_ts(v):
            if v is None:
                return ''
            try:
                ts = pd.to_datetime(v)
                return ts.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                return str(v)

        t_start = _fmt_ts(a.get('t_start')) if a.get('t_start') else \
            (_fmt_ts(ds.df.index[0]) if len(ds.df) else '')
        t_end = _fmt_ts(a.get('t_end')) if a.get('t_end') else \
            (_fmt_ts(ds.df.index[-1]) if len(ds.df) else '')
        n = len(ds.df)
        dt = self._guess_dt(ds)
        self._fill_grid(self.info_grid, [
            ('纬度', self._fmt_coord_lat(lat) if lat is not None else '—'),
            ('经度', self._fmt_coord_lon(lon) if lon is not None else '—'),
            ('海拔', f"{elev:.1f} m" if elev is not None else '—'),
            ('起始日期', t_start),
            ('结束日期', t_end),
            ('持续时长', self._fmt_duration(n, dt)),
            ('时间步长', f'{dt:g} {tr("分钟")}' if dt else ''),
            ('数据点数', f'{n:,}'),
            ('静风阈值', '0 m/s'),
        ], nowrap_keys={'起始日期', '结束日期'})
        # 数据集属性键列单独左移 3 汉字（51px）
        for r in range(self.info_grid.rowCount()):
            item = self.info_grid.itemAtPosition(r, 0)
            if item and item.widget():
                item.widget().setFixedWidth(51)

    def _fill_env(self, ds: Dataset | None, rho: float | None):
        if ds is None:
            self._fill_grid(self.env_grid, [(k, 'n/a') for k, _ in self._ENV_FIELDS])
            return
        temp = self.project.selection.get('temp')
        pres = self.project.selection.get('pres')
        t = ds.df[temp].astype(float).mean() if temp and temp in ds.df.columns else None
        p = ds.df[pres].astype(float).mean() if pres and pres in ds.df.columns else None
        self._fill_grid(self.env_grid, [
            ('平均气温', f'{t:.1f} °C' if t is not None else tr('无数据')),
            ('平均气压', f'{p:.1f} hPa' if p is not None else tr('无数据')),
            ('平均空气密度',
             f'{rho:.3f} kg/m³' if rho is not None else tr('无数据')),
            ('空气密度比',
             f'{rho / 1.225:.3f}' if rho is not None else tr('无数据')),
        ])

    def _fill_power(self, ds: Dataset | None, shear: dict | None, rho: float | None):
        if ds is None:
            self._fill_grid(self.power_grid, [(k, 'n/a') for k, _ in self._POWER_FIELDS])
            return
        alpha = shear['alpha'] if shear else None
        z_ref = shear['z_ref'] if shear else None
        # 寻找默认风速列（优先 selection 中的 speed，否则第一个 speed 通道）
        speed_col = self.project.selection.get('speed')
        if not speed_col or speed_col not in ds.df.columns:
            for n, ch in ds.channels.items():
                if ch.kind == KIND_SPEED and n in ds.df.columns:
                    speed_col = n
                    break
        if speed_col and speed_col in ds.df.columns:
            ch = ds.channels.get(speed_col)
            z_meas = ch.height if ch and ch.height else z_ref
            v_meas = float(pd.to_numeric(ds.df[speed_col], errors='coerce').mean())
        else:
            z_meas = v_meas = None

        def extrap(z):
            if z_meas is None or v_meas is None or z_meas == z:
                return v_meas
            if alpha is None or z_ref is None:
                # 无切变信息时直接用测量值
                return v_meas
            return self._extrapolate_speed(v_meas, z_meas, z, alpha)

        # 无可用风速数据时，统一用通用字段名（不显示假高度）
        if v_meas is None:
            self._fill_grid(self.power_grid, [
                ('平均风速', tr('无数据')),
                ('功率密度', tr('无数据')),
                ('风功率等级', tr('无数据')),
            ])
            return

        # 计算目标高度：首选通道高度，否则用 160m 作为默认展示高度
        z_target = z_meas if z_meas is not None else 160.0
        v_tgt = extrap(z_target)
        pd_tgt = (0.5 * rho * v_tgt ** 3) if rho and v_tgt else None
        rows = []
        if v_tgt is not None:
            rows.append((f'{tr("平均风速 @ ")}{z_target:g} m', f'{v_tgt:.2f} m/s'))
        if pd_tgt is not None:
            rows.append((f'功率密度 @ {z_target:g} m', f'{pd_tgt:.0f} W/m²'))
            rows.append(('风功率等级', self._wind_power_class(pd_tgt)))
        self._fill_grid(self.power_grid, rows)

    @staticmethod
    def _extrapolate_speed(v_ref: float, z_ref: float, z_tgt: float,
                           alpha: float) -> float:
        return v_ref * (z_tgt / z_ref) ** alpha

    @staticmethod
    def _wind_power_class(pdensity: float) -> str:
        if pdensity < 200:
            return '1 (Poor)'
        if pdensity < 300:
            return '2 (Marginal)'
        if pdensity < 400:
            return '3 (Fair)'
        if pdensity < 500:
            return '4 (Good)'
        if pdensity < 600:
            return '5 (Very good)'
        return '6 (Excellent)'

    @staticmethod
    def _roughness_class(z0: float) -> str:
        if z0 < 0.005:
            return '0'
        if z0 < 0.03:
            return '1'
        if z0 < 0.1:
            return '2'
        if z0 < 0.3:
            return '3'
        if z0 < 1.0:
            return '4'
        return '5'

    @staticmethod
    def _compute_shear(ds: Dataset | None):
        """按唯一高度聚合风速均值，再对 ln(V)-ln(z) 线性拟合得到风切变指数 α。

        同一高度常有多套方位/boom 传感器，先取该高度均值再拟合，
        否则不同方位混入会使 α 失真（R² 极低）。"""
        if ds is None:
            return None
        from collections import defaultdict
        agg = defaultdict(list)
        for n, ch in ds.channels.items():
            if ch.kind == KIND_SPEED and ch.height and ch.height > 0 and n in ds.df.columns:
                try:
                    v = float(pd.to_numeric(ds.df[n], errors='coerce').mean())
                except Exception:
                    continue
                if math.isfinite(v) and v > 0:
                    agg[ch.height].append(v)
        if len(agg) < 2:
            return None
        heights = np.array(sorted(agg.keys()), dtype=float)
        vals = np.array([float(np.mean(agg[h])) for h in heights], dtype=float)
        slope, intercept = np.polyfit(np.log(heights), np.log(vals), 1)
        pred = slope * np.log(heights) + intercept
        ss_res = np.sum((np.log(vals) - pred) ** 2)
        ss_tot = np.sum((np.log(vals) - np.log(vals).mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 1.0
        z_ref, z_tgt = heights[0], heights[-1]
        v_ref = vals[0]
        v_tgt = v_ref * (z_tgt / z_ref) ** slope
        alpha = float(slope)
        # 拟合曲线（对齐 Windographer 导出行为，500 点）：
        # Power law 从 z = z_max*0.002 起（贴近横轴但不取 0，避免过原点），
        # Log law 从 z = z0 起，z≤z0 段风速为 0（贴纵轴）。
        z_max = float(heights.max())
        z_fit_power = np.linspace(z_max * 0.002, z_max, 500)
        v_power = v_ref * (z_fit_power / z_ref) ** alpha
        # 对数风廓线：按 v = a + b·ln(z) 直接对测量高度做线性回归，
        # 粗糙长度 z0 = exp(-a/b)，摩擦速度 u* = b·κ。z≤z0 处 v=0。
        log_b, log_a = np.polyfit(np.log(heights), vals, 1)
        z0 = None
        if abs(log_b) > 1e-9:
            z0 = math.exp(-log_a / log_b)
            if z0 > 0 and z0 < z_max:
                z_fit_log = np.linspace(z0, z_max, 500)
                v_log = log_b * np.log(z_fit_log / z0)
                v_log = np.clip(np.nan_to_num(v_log, nan=0.0), 0.0, None)
            else:
                z0 = None
                z_fit_log = z_fit_power.copy()
                v_log = v_power.copy()
        else:
            z_fit_log = z_fit_power.copy()
            v_log = v_power.copy()
        return {
            'profile': list(zip(heights.tolist(), vals.tolist())),
            'alpha': alpha, 'r2': float(r2),
            'z_ref': float(z_ref), 'z_tgt': float(z_tgt),
            'v_ref': float(v_ref), 'v_tgt': float(v_tgt),
            'n_heights': int(len(heights)),
            'z0': float(z0) if z0 is not None else None,
            'power': list(zip(z_fit_power.tolist(), v_power.tolist())),
            'log': list(zip(z_fit_log.tolist(), v_log.tolist())),
        }

    def _fill_shear(self, shear: dict | None):
        if shear is None:
            self._fill_grid(self.shear_grid, [(k, 'n/a') for k, _ in self._SHEAR_FIELDS])
            return
        alpha = shear['alpha']
        z0 = shear.get('z0')
        rows = [
            ('参考高度范围', f"{shear['z_ref']:.0f}-{shear['z_tgt']:.0f} m"),
            ('风切变指数 α', f"{alpha:.4f}"),
            ('拟合优度 R²', f"{shear['r2']:.3f}"),
            ('地表粗糙度', f"{z0:.2f} m" if z0 is not None else '—'),
            ('粗糙度等级', self._roughness_class(z0) if z0 is not None else '—'),
            ('有效高度层数', f"{shear['n_heights']}"),
        ]
        self._fill_grid(self.shear_grid, rows)

    @staticmethod
    def _fmt_coord_lat(v):
        """纬度：返回原样格式 'N 27.371021' 或 'S -27.371021'。"""
        if v is None:
            return ''
        av = float(v)
        # 负坐标保留符号，正坐标用 N
        h = 'N' if av >= 0 else 'S'
        return f'{h} {av}'

    @staticmethod
    def _fmt_coord_lon(v):
        """经度：返回原样格式 'E 106.087546' 或 'W -106.087546'。"""
        if v is None:
            return ''
        av = float(v)
        # 负坐标保留符号，正坐标用 E
        h = 'E' if av >= 0 else 'W'
        return f'{h} {av}'

    @staticmethod
    def _fmt_duration(n: int, dt_min: float) -> str:
        if dt_min == 10 and n:
            days = n * 10 / 1440
            return f'{days:.1f} {tr("天")}'
        return ''

    @staticmethod
    def _guess_dt(ds: Dataset) -> float:
        """时间步长（分钟，数值）；供显示与持续时长换算共用。"""
        if len(ds.df) < 2:
            return 0
        try:
            idx = pd.to_datetime(ds.df.index)
            d = (idx[1] - idx[0]).total_seconds() / 60
            return float(int(d))
        except Exception:
            return 0

    @staticmethod
    def _air_density(t_c, p_hpa):
        return p_hpa * 100 / (287.05 * (273.15 + t_c))


# ---------------------------------------------------------------------------
# 2) Time Series
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 2) Time Series
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 3) Wind Rose
# ---------------------------------------------------------------------------
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


# 8) Reports
# ---------------------------------------------------------------------------
class ReportsTab(AnalysisTab):
    """Reports：风资源分析报告（对齐原版：Report combo + Create Report + Sections + Filter by）。"""

    SECTIONS = [
        ('summary', 'Data Set Summary'),
        ('env', 'Environmental Summary'),
        ('weibull', 'Wind Speed Distribution'),
        ('monthly', 'Monthly Statistics'),
        ('annual', 'Annual Statistics'),
        ('directional', 'Directional Statistics'),
        ('recovery', 'Data Recovery'),
    ]

    def __init__(self):
        super().__init__()
        self._layout.setContentsMargins(10, 10, 10, 10)

        from PySide6.QtWidgets import (QGroupBox, QTextBrowser, QDateTimeEdit,
                                       QDoubleSpinBox)
        from PySide6.QtCore import QDateTime

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)

        # ---- Report ----
        h_rpt = QHBoxLayout()
        h_rpt.setSpacing(6)
        h_rpt.addWidget(QLabel(tr('Report')))
        self.cmb_report = QComboBox()
        self.cmb_report.addItems(['Standard Report'])
        h_rpt.addWidget(self.cmb_report, 1)
        lv.addLayout(h_rpt)

        self.btn_create = QPushButton(tr('Create Report'))
        lv.addWidget(self.btn_create)

        # ---- Sections ----
        lv.addWidget(QLabel(tr('Sections')))
        self._section_boxes = []
        for key, label in self.SECTIONS:
            cb = QCheckBox(label)
            cb.setChecked(key in ('summary', 'weibull', 'monthly', 'annual'))
            cb.setProperty('key', key)
            cb.stateChanged.connect(self._on_changed)
            self._section_boxes.append(cb)
            lv.addWidget(cb)

        # ---- Filter by ----
        from core.dataset import KIND_DIR, KIND_SPEED
        flt = QGroupBox(tr('Filter by'))
        flt_lay = QVBoxLayout(flt)
        flt_lay.setSpacing(4)
        flt_lay.setContentsMargins(6, 6, 6, 6)

        h_flag = QHBoxLayout()
        self.chk_flag = QCheckBox(tr('Flag'))
        self.chk_include = QLabel(tr('Include'))
        self.chk_unflagged = QCheckBox(tr('<Unflagged data>'))
        self.chk_unflagged.setChecked(True)
        h_flag.addWidget(self.chk_flag)
        h_flag.addWidget(self.chk_include)
        h_flag.addWidget(self.chk_unflagged, 1)
        flt_lay.addLayout(h_flag)

        h_date = QHBoxLayout()
        self.chk_date = QCheckBox(tr('Date'))
        self.cmb_year = QComboBox(); self.cmb_year.addItem('<All>')
        self.cmb_month = QComboBox(); self.cmb_month.addItem('<All>')
        h_date.addWidget(self.chk_date)
        h_date.addWidget(QLabel(tr('Year')))
        h_date.addWidget(self.cmb_year)
        h_date.addWidget(QLabel(tr('Month')))
        h_date.addWidget(self.cmb_month, 1)
        flt_lay.addLayout(h_date)

        h_range = QHBoxLayout()
        self.chk_range = QCheckBox(tr('Date range'))
        self.dt_from = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat('yyyy/M/d')
        self.dt_to = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat('yyyy/M/d')
        self.dt_from.setEnabled(False)
        self.dt_to.setEnabled(False)
        h_range.addWidget(self.chk_range)
        h_range.addWidget(self.dt_from)
        h_range.addWidget(QLabel('to'))
        h_range.addWidget(self.dt_to, 1)
        flt_lay.addLayout(h_range)

        h_sec = QHBoxLayout()
        self.chk_sector = QCheckBox(tr('Direction sector'))
        self.cmb_sector = QComboBox(); self.cmb_sector.addItem(tr('All'))
        self.lbl_fsectors = QLabel(tr('Sectors'))
        self.sp_fsectors = QSpinBox(); self.sp_fsectors.setRange(4, 36)
        self.sp_fsectors.setValue(16)
        h_sec.addWidget(self.chk_sector)
        h_sec.addWidget(self.cmb_sector)
        h_sec.addWidget(self.lbl_fsectors)
        h_sec.addWidget(self.sp_fsectors)
        h_sec.addStretch(1)
        flt_lay.addLayout(h_sec)

        self.lbl_fsensor = QLabel(tr('Direction sensor'))
        self.cmb_fsensor = QComboBox()
        self.lbl_fsensor.setEnabled(False)
        self.cmb_fsensor.setEnabled(False)
        flt_lay.addWidget(self.lbl_fsensor)
        flt_lay.addWidget(self.cmb_fsensor)

        h_dcol = QHBoxLayout()
        self.chk_dcol = QCheckBox(tr('Data column'))
        self.cmb_fdata = QComboBox()
        h_dcol.addWidget(self.chk_dcol)
        h_dcol.addWidget(self.cmb_fdata, 1)
        flt_lay.addLayout(h_dcol)

        h_lim = QHBoxLayout()
        h_lim.setContentsMargins(8, 0, 0, 0)
        self.chk_min = QCheckBox(tr('Min'))
        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(-1e6, 1e6); self.spin_min.setValue(0.0)
        self.spin_min.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.chk_max = QCheckBox(tr('Max'))
        self.spin_max = QDoubleSpinBox()
        self.spin_max.setRange(-1e6, 1e6); self.spin_max.setValue(50.0)
        self.spin_max.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        h_lim.addWidget(self.chk_min)
        h_lim.addWidget(self.spin_min)
        h_lim.addWidget(self.chk_max)
        h_lim.addWidget(self.spin_max, 1)
        flt_lay.addLayout(h_lim)
        lv.addWidget(flt)

        # ---- Export ----
        h_exp = QHBoxLayout()
        btn_pdf = QPushButton(tr('Export PDF...'))
        btn_docx = QPushButton(tr('Export DOCX...'))
        h_exp.addWidget(btn_pdf)
        h_exp.addWidget(btn_docx)
        h_exp.addStretch(1)
        lv.addLayout(h_exp)
        self._layout.addWidget(left, 0)

        # ---- 右侧预览 ----
        self.preview = QTextBrowser()
        self._layout.addWidget(self.preview, 1)

        # ---- 信号 ----
        for cb in self._section_boxes:
            cb.stateChanged.connect(self._on_changed)
        self.btn_create.clicked.connect(self.refresh)
        btn_pdf.clicked.connect(self._export_pdf)
        btn_docx.clicked.connect(self._export_docx)

        self._populate_filters()
        self._sync_filter_enabled()

    def _populate_filters(self):
        """填充筛选下拉框（年份/月份/传感器/数据列）。"""
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            return
        try:
            years = sorted(ds.df.index.year.unique())
        except (AttributeError, TypeError):
            return
        for y in years:
            self.cmb_year.addItem(str(y), str(y))
        for m in range(1, 13):
            self.cmb_month.addItem(str(m), str(m))
        for n, ch in ds.channels.items():
            if ch.kind == 'dir' and getattr(ch, 'role', 'Avg') == 'Avg' \
                    and n in ds.df.columns:
                self.cmb_fsensor.addItem(n, n)
        for n in ds.channels:
            if n in ds.df.columns:
                self.cmb_fdata.addItem(n, n)
        idx0 = pd.Timestamp(ds.df.index[0])
        idx1 = pd.Timestamp(ds.df.index[-1])
        self.dt_from.setDateTime(idx0)
        self.dt_to.setDateTime(idx1)

    def _sync_filter_enabled(self):
        for w in (self.chk_include, self.chk_unflagged):
            w.setEnabled(self.chk_flag.isChecked())
        for w in (self.cmb_year, self.cmb_month):
            w.setEnabled(self.chk_date.isChecked())
        for w in (self.dt_from, self.dt_to):
            w.setEnabled(self.chk_range.isChecked())
        for w in (self.cmb_sector, self.lbl_fsectors, self.sp_fsectors,
                  self.cmb_fsensor):
            w.setEnabled(self.chk_sector.isChecked())
        for w in (self.chk_min, self.spin_min, self.chk_max, self.spin_max):
            w.setEnabled(self.chk_dcol.isChecked())

    def _filter_mask(self):
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            return None
        mask = pd.Series(True, index=ds.df.index)
        if self.chk_flag.isChecked():
            flags = getattr(ds, 'flags', None)
            if flags is not None and len(flags) == len(ds.df):
                if self.chk_unflagged.isChecked():
                    mask &= ~flags.astype(bool)
                else:
                    mask &= flags.astype(bool)
        if self.chk_date.isChecked():
            year = self.cmb_year.currentData()
            month = self.cmb_month.currentData()
            if year:
                mask &= ds.df.index.year == int(year)
            if month:
                mask &= ds.df.index.month == int(month)
        if self.chk_range.isChecked():
            mask &= ds.df.index >= pd.Timestamp(self.dt_from.dateTime().toPyDateTime())
            mask &= ds.df.index <= pd.Timestamp(self.dt_to.dateTime().toPyDateTime())
        if self.chk_dcol.isChecked():
            dcol = self.cmb_fdata.currentData()
            if dcol and dcol in ds.df.columns:
                v = pd.to_numeric(ds.df[dcol], errors='coerce')
                if self.chk_min.isChecked():
                    mask &= v >= self.spin_min.value()
                if self.chk_max.isChecked():
                    mask &= v <= self.spin_max.value()
        return mask if not mask.all() else None

    def _on_changed(self):
        self.refresh()

    def _model(self):
        from ui.modules.report_builder import ReportModel
        sections = [cb.property('key') for cb in self._section_boxes
                    if cb.isChecked()]
        return ReportModel(self.active_dataset(),
                           sections=sections,
                           title='Wind Resource Analysis Report')

    def _rose_png(self) -> bytes | None:
        from PySide6.QtCore import QBuffer, QIODevice
        from core.wind_rose import compute_rose
        ds = self.active_dataset()
        dir_col = None
        for n, ch in ds.channels.items():
            if ch.kind == 'dir' and getattr(ch, 'role', 'Avg') == 'Avg':
                dir_col = n
                break
        if not dir_col:
            return None
        r = compute_rose(ds.df, dir_col, sectors=16, display='frequency',
                         versus='direction')
        if r is None:
            return None
        canvas = PlotCanvas('Wind Rose')
        canvas.plot_polar(sectors=r.sectors, freq=r.values,
                          title='Wind Rose', labels=r.labels,
                          calm=r.calm, display_type='frequency',
                          unit=r.unit)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        canvas.grab().save(buf, 'PNG')
        return bytes(buf.data())

    def _monthly_png(self) -> bytes | None:
        from PySide6.QtCore import QBuffer, QIODevice
        ds = self.active_dataset()
        speeds = [(n, ch.height) for n, ch in ds.channels.items()
                  if ch.kind == 'speed' and getattr(ch, 'role', 'Avg') == 'Avg'
                  and n in ds.df.columns]
        if not speeds:
            return None
        name = speeds[-1][0]
        s = pd.to_numeric(ds.df[name], errors='coerce').dropna()
        if s.empty:
            return None
        monthly = s.groupby(s.index.month).mean()
        canvas = PlotCanvas('Monthly Mean Wind Speed')
        canvas.plot_bar(monthly.index.to_numpy(), monthly.to_numpy(),
                        xlabel='Month', ylabel='Mean wind speed (m/s)',
                        ymin=0)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        canvas.grab().save(buf, 'PNG')
        return bytes(buf.data())

    def refresh(self):
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            self.preview.setHtml('<p style="color:#999">No data loaded</p>')
            return
        model = self._model()
        blocks = model.blocks()
        rose = self._rose_png()
        if rose:
            blocks.append(('h2', 'Wind Rose'))
            blocks.append(('image', rose, 560, 400))
        monthly = self._monthly_png()
        if monthly:
            blocks.append(('h2', 'Monthly Mean Wind Speed'))
            blocks.append(('image', monthly, 560, 320))
        from ui.modules.report_builder import blocks_to_html
        self.preview.setHtml(blocks_to_html(blocks))

    def _export_pdf(self):
        from PySide6.QtCore import QMarginsF, QSizeF
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
        from ui.modules.report_builder import blocks_to_html
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            QMessageBox.information(self, 'Reports', 'No data loaded')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export PDF',
                                              'report.pdf', 'PDF (*.pdf)')
        if not path:
            return
        model = self._model()
        blocks = model.blocks()
        for png, h in ((self._rose_png(), 400), (self._monthly_png(), 320)):
            if png:
                blocks.append(('image', png, 560, h))
        with tempfile.TemporaryDirectory() as tmp:
            html = blocks_to_html(blocks, image_dir=tmp)
            writer = QPdfWriter(path)
            writer.setPageLayout(QPageLayout(
                QPageSize(QPageSize.A4), QPageLayout.Portrait,
                QMarginsF(15, 15, 15, 15)))
            writer.setResolution(96)
            doc = QTextDocument()
            doc.setHtml(html)
            doc.setPageSize(QSizeF(writer.width(), writer.height()))
            doc.print_(writer)
        QMessageBox.information(self, 'Reports', f'PDF exported: {path}')

    def _export_docx(self):
        from ui.modules.docx_writer import DocxBuilder
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            QMessageBox.information(self, 'Reports', 'No data loaded')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export DOCX',
                                              'report.docx', 'Word (*.docx)')
        if not path:
            return
        model = self._model()
        docx = DocxBuilder()
        rose = self._rose_png()
        monthly = self._monthly_png()
        for kind, payload in model.blocks():
            if kind == 'h1':
                docx.heading(payload, 1)
            elif kind == 'h2':
                docx.heading(payload, 2)
            elif kind == 'p':
                docx.paragraph(payload)
            elif kind == 'table':
                docx.table(payload)
        if rose:
            docx.image_png(rose, 560, 400)
            docx.paragraph('Wind Rose')
        if monthly:
            docx.image_png(monthly, 560, 320)
            docx.paragraph('Monthly Mean Wind Speed')
        docx.save(path)
        QMessageBox.information(self, 'Reports', f'DOCX exported: {path}')
