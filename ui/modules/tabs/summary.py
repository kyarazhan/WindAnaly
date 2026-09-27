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
