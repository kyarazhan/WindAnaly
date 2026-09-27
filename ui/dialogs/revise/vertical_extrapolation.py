"""vertical_extrapolation.py：见 _common 与 shim。"""
from __future__ import annotations

import copy
import math

import numpy as np
import pandas as pd
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateTimeEdit,
    QDialog, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QRadioButton, QSpinBox, QSplitter, QStackedWidget,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.dataset import Channel, Dataset
from core.i18n import language, tr
from core.io_import import build_canon_name
from ui.modules.analysis_tabs import actual_name, display_name
from ui.modules.plot import PlotCanvas

from ._common import (_to_num)

class VerticalExtrapolationDialog(QDialog):
    """Vertical Extrapolation：原版布局。

    左（共享）：Synthesize 复选 + 目标高度表（20 行）+ Flag new columns；
    右：Speed | Direction | Temperature 三个 Tab；
    Speed 幂律指数 8 种模式（每时间步计算 / 常数 / 月 / 小时 / 方向扇区 /
    月×小时 / 扇区×月 / 扇区×小时），指数表按数据预填中位数并可编辑。
    """

    ALPHA_MODES = [
        'Calculate in each time step',
        'Specify as a constant',
        'Specify by month',
        'Specify by hour of day',
        'Specify by direction sector',
        'Specify by month and hour of day',
        'Specify by direction sector and month',
        'Specify by direction sector and hour of day',
    ]
    MONTH_LB = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    def __init__(self, ds: Dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Vertical Extrapolation'))
        self.resize(1000, 640)
        self._ds = ds
        self._info = ''
        # 原版行为：外推源列表只列平均值（Avg）通道；SD 列由外推自动生成
        self._speed_src = [c.name for c in ds.channels.values()
                           if c.kind == 'speed'
                           and (c.role or 'Avg') == 'Avg']
        self._dir_src = [c.name for c in ds.channels.values()
                         if c.kind == 'dir'
                         and (c.role or 'Avg') == 'Avg']
        self._temp_src = [c.name for c in ds.channels.values()
                          if c.kind == 'temp'
                          and (c.role or 'Avg') == 'Avg']
        self._alpha_cache = None      # 每时间步 alpha（惰性）
        self._sector_prefilled_n = 0

        root = QVBoxLayout(self)
        body = QHBoxLayout()

        # ---- 左（共享）：Synthesize + 高度表 + Flag ----
        left = QWidget()
        left.setFixedWidth(230)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)
        lv.addWidget(QLabel(tr('Synthesize:')))
        self.chk_speed = QCheckBox(tr('Wind speed'))
        self.chk_speed.setChecked(True)
        self.chk_dir = QCheckBox(tr('Wind direction'))
        self.chk_dir.setChecked(True)
        self.chk_temp = QCheckBox(tr('Temperature'))
        self.chk_temp.setChecked(True)
        lv.addWidget(self.chk_speed)
        lv.addWidget(self.chk_dir)
        lv.addWidget(self.chk_temp)
        lv.addSpacing(10)
        lv.addWidget(QLabel(tr('for these heights:')))
        self.heights = QTableWidget(20, 2)
        self.heights.setHorizontalHeaderLabels(['#', tr('Height (m)')])
        self.heights.verticalHeader().setVisible(False)
        self.heights.setColumnWidth(0, 34)
        self.heights.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        default_h = self._default_target_height()
        for r in range(20):
            self.heights.setItem(r, 0, QTableWidgetItem(str(r + 1)))
            if r == 0 and default_h:
                self.heights.setItem(r, 1, QTableWidgetItem(f'{default_h:.1f}'))
        lv.addWidget(self.heights, 1)
        lv.addSpacing(8)
        self.chk_flag_new = QCheckBox(tr('Flag new columns with'))
        self.chk_flag_new.setChecked(True)
        lv.addWidget(self.chk_flag_new)
        self.flag_new = QComboBox()
        self.flag_new.addItems(['Synthesized', 'Icing', 'Invalid',
                                'Low quality', 'Tower shading'])
        lv.addWidget(self.flag_new)
        lv.addStretch(1)
        body.addWidget(left)

        # ---- 右：三个 Tab ----
        tabs = QTabWidget()
        tabs.addTab(self._build_speed_tab(), tr('Speed'))
        tabs.addTab(self._build_dir_tab(), tr('Direction'))
        tabs.addTab(self._build_temp_tab(), tr('Temperature'))
        body.addWidget(tabs, 1)
        root.addLayout(body, 1)

        btns = QHBoxLayout()
        help_btn = QPushButton(tr('Help'))
        help_btn.clicked.connect(lambda: QMessageBox.information(
            self, tr('Help'), tr(self.HELP)))
        btns.addWidget(help_btn)
        btns.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton(tr('Synthesize Data & Append To Data Set...'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

        self._prefill_tables()
        self._prefill_veer_tables()
        self._prefill_grad_tables()

    # ---------- 构建 Speed Tab ----------
    def _build_speed_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        top = QGridLayout()
        top.addWidget(QLabel(tr('Power law exponent')), 0, 0)
        self.alpha_method = QComboBox()
        for m in self.ALPHA_MODES:
            self.alpha_method.addItem(tr(m))
        top.addWidget(self.alpha_method, 0, 1)
        top.setColumnStretch(1, 1)
        v.addLayout(top)

        # Extrapolate from（模式 2-8 共享行）
        self.ex_row_w = QWidget()
        exh = QHBoxLayout(self.ex_row_w)
        exh.setContentsMargins(0, 0, 0, 0)
        exh.addWidget(QLabel(tr('Extrapolate from')))
        self.ref_combo = self._src_combo(self._speed_src)
        exh.addWidget(self.ref_combo)
        exh.addStretch(1)

        # Direction sensor + sectors（扇区模式共享行）
        self.sector_row_w = QWidget()
        seh = QHBoxLayout(self.sector_row_w)
        seh.setContentsMargins(0, 0, 0, 0)
        seh.addWidget(QLabel(tr('Direction sensor')))
        self.dir_combo = self._src_combo(self._dir_src)
        seh.addWidget(self.dir_combo)
        seh.addWidget(QLabel(tr('Direction sectors')))
        self.sector_spin = QSpinBox()
        self.sector_spin.setRange(1, 36)
        self.sector_spin.setValue(16)
        seh.addWidget(self.sector_spin)
        seh.addStretch(1)
        self.sector_spin.valueChanged.connect(
            lambda _v: self._on_sectors_changed())

        # 模式 1：Calculate in each time step
        p1 = QWidget()
        p1h = QHBoxLayout(p1)
        p1l = QVBoxLayout()
        p1l.addWidget(QLabel(tr('Calculate from')))
        self.src_speed = self._src_check_list(self._speed_src)
        p1l.addWidget(self.src_speed, 1)
        p1h.addLayout(p1l, 1)
        p1r = QVBoxLayout()
        self.chk_restrict = QCheckBox(
            tr('Restrict power law exponent to a range'))
        self.chk_restrict.setChecked(True)
        p1r.addWidget(self.chk_restrict)
        form = QFormLayout()
        self.alpha_min = QDoubleSpinBox()
        self.alpha_min.setRange(-1, 2)
        self.alpha_min.setDecimals(3)
        self.alpha_min.setValue(-0.05)
        self.alpha_max = QDoubleSpinBox()
        self.alpha_max.setRange(-1, 2)
        self.alpha_max.setDecimals(3)
        self.alpha_max.setValue(1.0)
        form.addRow(tr('Min. value'), self.alpha_min)
        form.addRow(tr('Max. value'), self.alpha_max)
        p1r.addLayout(form)
        p1r.addStretch(1)
        p1h.addLayout(p1r)

        # 模式 2：constant
        p2 = QWidget()
        p2v = QVBoxLayout(p2)
        p2v.addWidget(QLabel(tr('Enter constant power law exponent')))
        f2 = QFormLayout()
        self.alpha_const = QDoubleSpinBox()
        self.alpha_const.setRange(-1, 2)
        self.alpha_const.setDecimals(6)
        self.alpha_const.setValue(self._default_alpha())
        f2.addRow(tr('Constant power law exponent'), self.alpha_const)
        p2v.addLayout(f2)
        p2v.addStretch(1)

        # 模式 3-8 的指数表
        self.tbl_month = self._make_table(12, 2, 'Month', self.MONTH_LB)
        cap_month = self._wrap(self.tbl_month,
                               tr('Enter power law exponent by month'))
        hour_lb = [f'{h:02d}:00- {h + 1:02d}:00' for h in range(24)]
        self.tbl_hour = self._make_table(24, 2, 'Hour', hour_lb)
        cap_hour = self._wrap(self.tbl_hour,
                              tr('Enter power law exponent by hour of day'))
        self.tbl_sector = self._make_table(16, 2, 'Direction Sector', None)
        cap_sector = self._wrap(
            self.tbl_sector,
            tr('Enter power law exponent by direction sector'))
        self.tbl_month_hour = self._make_table(
            24, 13, 'Hour', self.MONTH_LB)
        cap_mh = self._wrap(
            self.tbl_month_hour,
            tr('Enter power law exponent by month and hour of day'))
        self.tbl_sector_month = self._make_table(
            16, 13, 'Direction Sector', self.MONTH_LB)
        cap_sm = self._wrap(
            self.tbl_sector_month,
            tr('Enter power law exponent by direction sector and month'))
        self.tbl_sector_hour = self._make_table(
            16, 25, 'Direction Sector', hour_lb)
        cap_sh = self._wrap(
            self.tbl_sector_hour,
            tr('Enter power law exponent by hour of day and direction sector'))

        self.mode_stack = QStackedWidget()
        for pg in (p1, p2, cap_month, cap_hour, cap_sector,
                   cap_mh, cap_sm, cap_sh):
            self.mode_stack.addWidget(pg)
        v.addWidget(self.ex_row_w)
        v.addWidget(self.sector_row_w)
        v.addWidget(self.mode_stack, 1)

        def _on_mode(i):
            self.ex_row_w.setVisible(i != 0)
            self.sector_row_w.setVisible(i in (4, 6, 7))
            self.mode_stack.setCurrentIndex(i)
            if i in (4, 6, 7):
                self._on_sectors_changed()

        self.alpha_method.currentIndexChanged.connect(_on_mode)
        _on_mode(0)
        return w

    def _make_table(self, rows: int, cols: int, first_header: str,
                    col_headers) -> QTableWidget:
        """cols=2 → 标签列+单指数列；cols>2 → 标签列+多列。"""
        tbl = QTableWidget(rows, cols)
        if cols == 2:
            tbl.setHorizontalHeaderLabels(
                [first_header, f'Power Law\nExponent'])
        else:
            tbl.setHorizontalHeaderLabels([first_header] + list(col_headers))
        tbl.verticalHeader().setVisible(False)
        # 标签列
        for r in range(rows):
            if cols == 2:
                lb = col_headers[r] if col_headers else ''
            else:
                lb = ''
            if lb:
                it = QTableWidgetItem(lb)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                tbl.setItem(r, 0, it)
        if cols > 2:
            tbl.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeToContents)
        return tbl

    def _wrap(self, table: QTableWidget, caption: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel(caption))
        v.addWidget(table)
        return w

    # ---------- 构建 Direction / Temperature Tab ----------
    def _build_dir_tab(self) -> QWidget:
        """Direction Tab：风向切变率（Wind veer rate，°/100m），6 种模式。"""
        w = QWidget()
        v = QVBoxLayout(w)
        top = QGridLayout()
        top.addWidget(QLabel(tr('Wind veer rate')), 0, 0)
        self.veer_method = QComboBox()
        for m in ('Calculate in each time step', 'Specify as a constant',
                  'Specify by month', 'Specify by hour of day',
                  'Specify by direction sector',
                  'Specify by month and hour of day',
                  'Specify by direction sector and month',
                  'Specify by direction sector and hour of day'):
            self.veer_method.addItem(tr(m))
        top.addWidget(self.veer_method, 0, 1)
        top.setColumnStretch(1, 1)
        v.addLayout(top)

        # Extrapolate from（模式 2-6 共享行）
        self.ex_dir_row_w = QWidget()
        exh = QHBoxLayout(self.ex_dir_row_w)
        exh.setContentsMargins(0, 0, 0, 0)
        exh.addWidget(QLabel(tr('Extrapolate from')))
        self.veer_ref = self._src_combo(self._dir_src)
        exh.addWidget(self.veer_ref)
        exh.addStretch(1)

        # Direction sensor + sectors（扇区模式共享行）
        self.sector_row_dir_w = QWidget()
        seh = QHBoxLayout(self.sector_row_dir_w)
        seh.setContentsMargins(0, 0, 0, 0)
        seh.addWidget(QLabel(tr('Direction sensor')))
        self.dir_sensor_combo = self._src_combo(self._dir_src)
        seh.addWidget(self.dir_sensor_combo)
        seh.addWidget(QLabel(tr('Direction sectors')))
        self.veer_sector_spin = QSpinBox()
        self.veer_sector_spin.setRange(1, 36)
        self.veer_sector_spin.setValue(16)
        seh.addWidget(self.veer_sector_spin)
        seh.addStretch(1)
        self.veer_sector_spin.valueChanged.connect(
            lambda _v: self._on_veer_sectors_changed())

        # 模式 1：Calculate in each time step
        p1 = QWidget()
        p1h = QHBoxLayout(p1)
        p1l = QVBoxLayout()
        p1l.addWidget(QLabel(tr('Calculate from')))
        self.src_dir = self._src_check_list(self._dir_src)
        p1l.addWidget(self.src_dir, 1)
        p1h.addLayout(p1l, 1)
        p1r = QVBoxLayout()
        self.chk_veer_restrict = QCheckBox(
            tr('Restrict wind veer rate to a range'))
        self.chk_veer_restrict.setChecked(True)
        p1r.addWidget(self.chk_veer_restrict)
        vf = QFormLayout()
        self.veer_min = QDoubleSpinBox()
        self.veer_min.setRange(-1000, 1000)
        self.veer_min.setValue(-200)
        self.veer_max = QDoubleSpinBox()
        self.veer_max.setRange(-1000, 1000)
        self.veer_max.setValue(200)
        vf.addRow(tr('Min. value (\u2191100m)'), self.veer_min)
        vf.addRow(tr('Max. value (\u2191100m)'), self.veer_max)
        p1r.addLayout(vf)
        p1r.addStretch(1)
        p1h.addLayout(p1r)

        # 模式 2：constant
        p2 = QWidget()
        p2v = QVBoxLayout(p2)
        p2v.addWidget(QLabel(tr('Enter constant wind veer rate')))
        f2 = QFormLayout()
        self.veer_const = QDoubleSpinBox()
        self.veer_const.setRange(-1000, 1000)
        self.veer_const.setDecimals(4)
        self.veer_const.setValue(self._default_veer())
        f2.addRow(tr('Constant wind veer rate (\u2191100m)'), self.veer_const)
        p2v.addLayout(f2)
        p2v.addStretch(1)

        hour_lb = [f'{h:02d}:00- {h + 1:02d}:00' for h in range(24)]
        self.tbl_veer_month = self._make_table(12, 2, 'Month', self.MONTH_LB)
        cap_m = self._wrap(self.tbl_veer_month,
                           tr('Enter wind veer rate by month'))
        self.tbl_veer_hour = self._make_table(24, 2, 'Hour', hour_lb)
        cap_h = self._wrap(self.tbl_veer_hour,
                           tr('Enter wind veer rate by hour of day'))
        self.tbl_veer_sector = self._make_table(16, 2, 'Direction Sector', None)
        cap_s = self._wrap(self.tbl_veer_sector,
                           tr('Enter wind veer rate by direction sector'))
        self.tbl_veer_mh = self._make_table(24, 13, 'Hour', self.MONTH_LB)
        cap_mh = self._wrap(self.tbl_veer_mh,
                            tr('Enter wind veer rate by month and hour of day'))
        self.tbl_veer_sm = self._make_table(16, 13, 'Direction Sector',
                                            self.MONTH_LB)
        cap_sm = self._wrap(
            self.tbl_veer_sm,
            tr('Enter wind veer rate by direction sector and month'))
        self.tbl_veer_sh = self._make_table(16, 25, 'Direction Sector', hour_lb)
        cap_sh = self._wrap(
            self.tbl_veer_sh,
            tr('Enter wind veer rate by direction sector and hour of day'))

        self.veer_stack = QStackedWidget()
        for pg in (p1, p2, cap_m, cap_h, cap_s, cap_mh, cap_sm, cap_sh):
            self.veer_stack.addWidget(pg)
        v.addWidget(self.ex_dir_row_w)
        v.addWidget(self.sector_row_dir_w)
        v.addWidget(self.veer_stack, 1)

        def _on_veer_mode(i):
            self.ex_dir_row_w.setVisible(i != 0)
            self.sector_row_dir_w.setVisible(i in (4, 6, 7))
            self.veer_stack.setCurrentIndex(i)
            if i == 4:
                self._on_veer_sectors_changed()

        self.veer_method.currentIndexChanged.connect(_on_veer_mode)
        _on_veer_mode(0)
        return w

    def _checked_dir_src(self) -> list[tuple[str, float]]:
        out = []
        for i in range(self.src_dir.count()):
            it = self.src_dir.item(i)
            if it.checkState() == Qt.Checked:
                col = it.data(Qt.UserRole)
                ch = self._ds.channels.get(col)
                if ch is not None and ch.height and col in self._ds.df.columns:
                    out.append((col, float(ch.height)))
        return out

    def _veer_step_rates(self) -> np.ndarray:
        """每个时间步的风向切变率（°/100m）。

        以最低层方向为基准，把各层方向按圆周差展开后对高度做线性拟合，
        斜率 ×100。"""
        srcs = sorted(self._checked_dir_src(), key=lambda x: x[1])
        idx = self._ds.df.index
        if len(srcs) < 2:
            return np.full(len(idx), np.nan)
        base_col, base_z = srcs[0]
        d_base = _to_num(self._ds.df[base_col]).to_numpy()
        z_rel = np.array([z for _, z in srcs]) - base_z
        D = np.column_stack([_to_num(self._ds.df[c]).to_numpy()
                             for c, _ in srcs])
        deltas = (D - d_base[:, None] + 180) % 360 - 180
        valid = np.isfinite(deltas).all(axis=1)
        m = np.where(valid, np.nanmean(deltas, axis=1), 0)
        mz = z_rel.mean()
        num = np.nansum((deltas - m[:, None]) * (z_rel - mz), axis=1)
        den = float(((z_rel - mz) ** 2).sum())
        slope = num / den if den else np.full(len(idx), np.nan)
        slope = np.asarray(slope, dtype=float)
        slope[~np.isfinite(slope)] = np.nan
        return slope * 100.0

    def _default_veer(self) -> float:
        v = self._veer_step_rates()
        v = v[np.isfinite(v)]
        return float(np.clip(np.median(v), -200, 200)) if len(v) else 3.16

    def _on_veer_sectors_changed(self):
        n = self.veer_sector_spin.value()
        for r in range(min(n, self.tbl_veer_sector.rowCount())):
            it = QTableWidgetItem(self._sector_label(r, n))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.tbl_veer_sector.setItem(r, 0, it)
        for r in range(min(n, self.tbl_veer_sm.rowCount())):
            it = QTableWidgetItem(self._sector_label(r, n))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.tbl_veer_sm.setItem(r, 0, it)
        for r in range(min(n, self.tbl_veer_sh.rowCount())):
            it = QTableWidgetItem(self._sector_label(r, n))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.tbl_veer_sh.setItem(r, 0, it)
        self._prefill_veer_tables()

    def _prefill_veer_tables(self):
        """按数据预填切变率表（每桶中位数）；只填空白格。"""
        rates = self._veer_step_rates()
        if not np.isfinite(rates).any():
            return
        idx = self._ds.df.index
        fill_1d(self.tbl_veer_month,
                [float(np.nanmedian(rates[idx.month == m]))
                 for m in range(1, 13)])
        fill_1d(self.tbl_veer_hour,
                [float(np.nanmedian(rates[idx.hour == h]))
                 for h in range(24)])
        n = self.veer_sector_spin.value()
        dcol = self.dir_sensor_combo.currentData()
        if not dcol or dcol not in self._ds.df.columns:
            return
        sec = self._sector_index(
            _to_num(self._ds.df[dcol]).to_numpy(), n)
        fill_1d(self.tbl_veer_sector,
                [float(np.nanmedian(rates[sec == i])) for i in range(n)])
        months = idx.month.values - 1
        hours = idx.hour.values
        fill_2d(self.tbl_veer_mh,
                [[float(np.nanmedian(rates[(hours == h) & (months == m)]))
                  for m in range(12)] for h in range(24)])
        fill_2d(self.tbl_veer_sm,
                [[float(np.nanmedian(rates[(sec == i) & (months == m)]))
                  for m in range(12)] for i in range(n)])
        fill_2d(self.tbl_veer_sh,
                [[float(np.nanmedian(rates[(sec == i) & (hours == h)]))
                  for h in range(24)] for i in range(n)])

    def _find_dir_sd(self, ref_col: str) -> str | None:
        """找参考风向通道的同高度 SD 列（关联优先，同高度匹配兜底）。"""
        ch = self._ds.channels.get(ref_col)
        if ch is not None and ch.sd_col and ch.sd_col in self._ds.df.columns:
            return ch.sd_col
        if ch is None:
            return None
        for c2, c in self._ds.channels.items():
            if c.kind == 'dir' and c.role == 'SD' \
                    and (c.height or -1) == (ch.height or -1) \
                    and c2 in self._ds.df.columns:
                return c2
        return None

    def _veer_lookup(self) -> np.ndarray:
        """按当前切变率模式为每个时间步生成 veer（°/100m）。"""
        idx = self._ds.df.index
        mode = self.veer_method.currentIndex()
        n = len(idx)
        if mode == 1:
            return np.full(n, self.veer_const.value())
        months = idx.month.values - 1
        hours = idx.hour.values
        if mode == 2:
            col = read_col(self.tbl_veer_month)
            return np.array([col[m] for m in months])
        if mode == 3:
            col = read_col(self.tbl_veer_hour)
            return np.array([col[h] for h in hours])
        n_sec = self.veer_sector_spin.value()
        dcol = self.dir_sensor_combo.currentData()
        dirs = _to_num(self._ds.df[dcol]).to_numpy() if dcol else None
        if dirs is None:
            return np.full(n, np.nan)
        sec = self._sector_index(dirs, n_sec)
        if mode == 4:
            col = read_col(self.tbl_veer_sector)
            return np.array([col[s] for s in sec])
        if mode == 5:
            mat = read_mat(self.tbl_veer_mh)
            return np.array([mat[hours[i], months[i]] for i in range(n)])
        if mode == 6:
            mat = read_mat(self.tbl_veer_sm)
            return np.array([mat[sec[i], months[i]] for i in range(n)])
        if mode == 7:
            mat = read_mat(self.tbl_veer_sh)
            return np.array([mat[sec[i], hours[i]] for i in range(n)])
        return np.full(n, np.nan)

    def _build_temp_tab(self) -> QWidget:
        """Temperature Tab：温度梯度（Temperature gradient，°C/100m），8 模式。"""
        w = QWidget()
        v = QVBoxLayout(w)
        top = QGridLayout()
        top.addWidget(QLabel(tr('Temperature gradient')), 0, 0)
        self.grad_method = QComboBox()
        for m in self.ALPHA_MODES:
            self.grad_method.addItem(tr(m))
        top.addWidget(self.grad_method, 0, 1)
        top.setColumnStretch(1, 1)
        v.addLayout(top)

        self.ex_temp_row_w = QWidget()
        exh = QHBoxLayout(self.ex_temp_row_w)
        exh.setContentsMargins(0, 0, 0, 0)
        exh.addWidget(QLabel(tr('Extrapolate from')))
        self.temp_ref = self._src_combo(self._temp_src)
        exh.addWidget(self.temp_ref)
        exh.addStretch(1)

        self.sector_row_temp_w = QWidget()
        seh = QHBoxLayout(self.sector_row_temp_w)
        seh.setContentsMargins(0, 0, 0, 0)
        seh.addWidget(QLabel(tr('Direction sensor')))
        self.grad_dir_combo = self._src_combo(self._dir_src)
        seh.addWidget(self.grad_dir_combo)
        seh.addWidget(QLabel(tr('Direction sectors')))
        self.grad_sector_spin = QSpinBox()
        self.grad_sector_spin.setRange(1, 36)
        self.grad_sector_spin.setValue(16)
        seh.addWidget(self.grad_sector_spin)
        seh.addStretch(1)
        self.grad_sector_spin.valueChanged.connect(
            lambda _v: self._on_grad_sectors_changed())

        # 模式 1：Calculate in each time step
        p0 = QWidget()
        p0h = QHBoxLayout(p0)
        p0l = QVBoxLayout()
        p0l.addWidget(QLabel(tr('Calculate from')))
        self.src_temp = self._src_check_list(self._temp_src)
        p0l.addWidget(self.src_temp, 1)
        p0h.addLayout(p0l, 1)
        p0r = QVBoxLayout()
        self.chk_grad_restrict = QCheckBox(
            tr('Restrict temperature gradient to a range'))
        self.chk_grad_restrict.setChecked(True)
        p0r.addWidget(self.chk_grad_restrict)
        gf = QFormLayout()
        self.grad_min = QDoubleSpinBox()
        self.grad_min.setRange(-10, 10)
        self.grad_min.setValue(-5)
        self.grad_max = QDoubleSpinBox()
        self.grad_max.setRange(-10, 10)
        self.grad_max.setValue(5)
        gf.addRow(tr('Min. value'), self.grad_min)
        gf.addRow(tr('Max. value'), self.grad_max)
        p0r.addLayout(gf)
        p0r.addStretch(1)
        p0h.addLayout(p0r)

        # 模式 2：constant（默认 -0.65 °C/100m）
        p2 = QWidget()
        p2v = QVBoxLayout(p2)
        p2v.addWidget(QLabel(tr('Enter constant temperature gradient')))
        f2 = QFormLayout()
        self.grad_const = QDoubleSpinBox()
        self.grad_const.setRange(-10, 10)
        self.grad_const.setDecimals(3)
        self.grad_const.setValue(self._default_grad())
        f2.addRow(tr('Constant temperature gradient (°C/100m)'),
                  self.grad_const)
        p2v.addLayout(f2)
        p2v.addStretch(1)

        hour_lb = [f'{h:02d}:00- {h + 1:02d}:00' for h in range(24)]
        self.tbl_grad_month = self._make_table(12, 2, 'Month', self.MONTH_LB)
        cap_m = self._wrap(self.tbl_grad_month,
                           tr('Enter temperature gradient by month'))
        self.tbl_grad_hour = self._make_table(24, 2, 'Hour', hour_lb)
        cap_h = self._wrap(self.tbl_grad_hour,
                           tr('Enter temperature gradient by hour of day'))
        self.tbl_grad_sector = self._make_table(16, 2, 'Direction Sector', None)
        cap_s = self._wrap(self.tbl_grad_sector,
                           tr('Enter temperature gradient by direction sector'))
        self.tbl_grad_mh = self._make_table(24, 13, 'Hour', self.MONTH_LB)
        cap_mh = self._wrap(self.tbl_grad_mh,
                            tr('Enter temperature gradient by month and hour of day'))
        self.tbl_grad_sm = self._make_table(16, 13, 'Direction Sector', self.MONTH_LB)
        cap_sm = self._wrap(self.tbl_grad_sm,
                            tr('Enter temperature gradient by direction sector and month'))
        self.tbl_grad_sh = self._make_table(16, 25, 'Direction Sector', hour_lb)
        cap_sh = self._wrap(self.tbl_grad_sh,
                            tr('Enter temperature gradient by hour of day and direction sector'))

        self.grad_stack = QStackedWidget()
        for pg in (p0, p2, cap_m, cap_h, cap_s, cap_mh, cap_sm, cap_sh):
            self.grad_stack.addWidget(pg)
        v.addWidget(self.ex_temp_row_w)
        v.addWidget(self.sector_row_temp_w)
        v.addWidget(self.grad_stack, 1)

        def _on_grad_mode(i):
            self.ex_temp_row_w.setVisible(i != 0)
            self.sector_row_temp_w.setVisible(i in (4, 6, 7))
            self.grad_stack.setCurrentIndex(i)
            if i in (4, 6, 7):
                self._on_grad_sectors_changed()

        self.grad_method.currentIndexChanged.connect(_on_grad_mode)
        _on_grad_mode(1)
        return w

    def _checked_temp_src(self) -> list[tuple[str, float]]:
        out = []
        for i in range(self.src_temp.count()):
            it = self.src_temp.item(i)
            if it.checkState() == Qt.Checked:
                col = it.data(Qt.UserRole)
                ch = self._ds.channels.get(col)
                if ch is not None and ch.height and col in self._ds.df.columns:
                    out.append((col, float(ch.height)))
        return out

    def _grad_step(self) -> np.ndarray:
        """每个时间步的温度梯度（°C/100m）：T 对 z 线性拟合 ×100。"""
        srcs = sorted(self._checked_temp_src(), key=lambda x: x[1])
        idx = self._ds.df.index
        if len(srcs) < 2:
            return np.full(len(idx), np.nan)
        z = np.array([h for _, h in srcs])
        mz = z.mean()
        T = np.column_stack([_to_num(self._ds.df[c]).to_numpy()
                             for c, _ in srcs])
        mT = np.nanmean(T, axis=1)
        num = np.nansum((T - mT[:, None]) * (z - mz), axis=1)
        den = float(((z - mz) ** 2).sum())
        grad = num / den * 100.0 if den else np.full(len(idx), np.nan)
        grad = np.asarray(grad, dtype=float)
        grad[~np.isfinite(grad)] = np.nan
        return grad

    def _default_grad(self) -> float:
        g = self._grad_step()
        g = g[np.isfinite(g)]
        return float(np.clip(np.median(g), -10, 10)) if len(g) else -0.65

    def _on_grad_sectors_changed(self):
        n = self.grad_sector_spin.value()
        for r in range(min(n, self.tbl_grad_sector.rowCount())):
            it = QTableWidgetItem(self._sector_label(r, n))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.tbl_grad_sector.setItem(r, 0, it)
        self._prefill_grad_tables()

    def _prefill_grad_tables(self):
        grads = self._grad_step()
        if not np.isfinite(grads).any():
            return
        idx = self._ds.df.index
        fill_1d(self.tbl_grad_month,
                [float(np.nanmedian(grads[idx.month == m]))
                 for m in range(1, 13)])
        fill_1d(self.tbl_grad_hour,
                [float(np.nanmedian(grads[idx.hour == h]))
                 for h in range(24)])
        n = self.grad_sector_spin.value()
        dcol = self.grad_dir_combo.currentData()
        if not dcol or dcol not in self._ds.df.columns:
            return
        sec = self._sector_index(
            _to_num(self._ds.df[dcol]).to_numpy(), n)
        fill_1d(self.tbl_grad_sector,
                [float(np.nanmedian(grads[sec == i])) for i in range(n)])
        months = idx.month.values - 1
        hours = idx.hour.values
        fill_2d(self.tbl_grad_mh,
                [[float(np.nanmedian(grads[(hours == h) & (months == m)]))
                  for m in range(12)] for h in range(24)])
        fill_2d(self.tbl_grad_sm,
                [[float(np.nanmedian(grads[(sec == i) & (months == m)]))
                  for m in range(12)] for i in range(n)])
        fill_2d(self.tbl_grad_sh,
                [[float(np.nanmedian(grads[(sec == i) & (hours == h)]))
                  for h in range(24)] for i in range(n)])

    def _grad_lookup(self) -> np.ndarray:
        idx = self._ds.df.index
        mode = self.grad_method.currentIndex()
        n = len(idx)
        if mode == 1:
            return np.full(n, self.grad_const.value())
        months = idx.month.values - 1
        hours = idx.hour.values
        if mode == 2:
            col = read_col(self.tbl_grad_month)
            return np.array([col[m] for m in months])
        if mode == 3:
            col = read_col(self.tbl_grad_hour)
            return np.array([col[h] for h in hours])
        n_sec = self.grad_sector_spin.value()
        dcol = self.grad_dir_combo.currentData()
        dirs = _to_num(self._ds.df[dcol]).to_numpy() if dcol else None
        if dirs is None:
            return np.full(n, np.nan)
        sec = self._sector_index(dirs, n_sec)
        if mode == 4:
            col = read_col(self.tbl_grad_sector)
            return np.array([col[s] for s in sec])
        if mode == 5:
            mat = read_mat(self.tbl_grad_mh)
            return np.array([mat[hours[i], months[i]] for i in range(n)])
        if mode == 6:
            mat = read_mat(self.tbl_grad_sm)
            return np.array([mat[sec[i], months[i]] for i in range(n)])
        if mode == 7:
            mat = read_mat(self.tbl_grad_sh)
            return np.array([mat[sec[i], hours[i]] for i in range(n)])
        return np.full(n, np.nan)

    def _auto_sd(self, zt: float, res: pd.Series, ref_col: str,
                 v_ref: pd.Series):
        """按参考高度的风速比值缩放参考 SD 列，自动生成 zt 高度 SD 列。"""
        ch = self._ds.channels.get(ref_col)
        sd_ref = None
        if ch is not None and ch.sd_col and ch.sd_col in self._ds.df.columns:
            sd_ref = ch.sd_col
        elif ch is not None:
            for c2, c in self._ds.channels.items():
                if c.kind == 'speed' and c.role == 'SD' \
                        and (c.height or -1) == (ch.height or -1) \
                        and c2 in self._ds.df.columns:
                    sd_ref = c2
                    break
        if not sd_ref:
            return
        out = build_canon_name('Speed', zt, '', 'SD')
        if out in self._ds.df.columns:
            return
        vr = v_ref.copy()
        vr[vr.abs() < 0.05] = np.nan
        self._ds.df[out] = _to_num(self._ds.df[sd_ref]) * (res / vr)
        self._ds.channels[out] = Channel(name=out, kind='speed', height=zt,
                                         units='m/s', role='SD')

    # ---------- 工具 ----------
    def _src_check_list(self, cols: list[str]) -> QListWidget:
        lst = QListWidget()
        lst.setSelectionMode(QAbstractItemView.NoSelection)
        for c in cols:
            it = QListWidgetItem(display_name(c))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, c)
            lst.addItem(it)
        return lst

    def _src_combo(self, cols: list[str]) -> QComboBox:
        combo = QComboBox()
        for c in cols:
            combo.addItem(display_name(c), c)
        return combo

    def _default_target_height(self) -> float:
        hs = [c.height for c in self._ds.channels.values()
              if c.kind == 'speed' and c.height]
        if not hs:
            return 160.0
        return max(round(max(hs) * 1.33 / 10) * 10, max(hs) + 10)

    def _checked_speed_src(self) -> list[tuple[str, float]]:
        out = []
        for i in range(self.src_speed.count()):
            it = self.src_speed.item(i)
            if it.checkState() == Qt.Checked:
                col = it.data(Qt.UserRole)
                ch = self._ds.channels.get(col)
                if ch is not None and ch.height and col in self._ds.df.columns:
                    out.append((col, float(ch.height)))
        return out

    def _step_alphas(self) -> np.ndarray:
        """每个时间步的幂律指数（对勾选源做 ln v ~ ln z 拟合，向量化）。"""
        if self._alpha_cache is not None:
            return self._alpha_cache
        srcs = self._checked_speed_src()
        idx = self._ds.df.index
        if len(srcs) < 2:
            self._alpha_cache = np.full(len(idx), np.nan)
            return self._alpha_cache
        z = np.array([h for _, h in srcs])
        lz = np.log(z)
        mz = lz.mean()
        V = np.column_stack([_to_num(self._ds.df[c]).to_numpy()
                             for c, _ in srcs])
        with np.errstate(all='ignore'):
            L = np.log(V)
        mL = np.nanmean(L, axis=1)
        num = np.nansum((L - mL[:, None]) * (lz - mz), axis=1)
        den = float(((lz - mz) ** 2).sum())
        alpha = num / den if den else np.full(len(idx), np.nan)
        alpha[~np.isfinite(alpha)] = np.nan
        self._alpha_cache = alpha
        return self._alpha_cache

    def _default_alpha(self) -> float:
        a = self._step_alphas()
        a = a[~np.isnan(a)]
        return float(np.median(a)) if len(a) else 0.14

    def _sector_index(self, dirs: np.ndarray, n: int) -> np.ndarray:
        width = 360.0 / n
        return (np.floor(((dirs + width / 2) % 360) / width)).astype(int) % n

    def _sector_label(self, i: int, n: int) -> str:
        width = 360.0 / n
        lo = (i * width - width / 2) % 360
        hi = ((i + 1) * width - width / 2) % 360
        return f'{lo:.2f}°- {hi:.2f}°'

    def _on_sectors_changed(self):
        """扇区数变化：重建扇区表行标签，空白格按数据预填。"""
        n = self.sector_spin.value()
        for tbl in (self.tbl_sector, self.tbl_sector_month,
                    self.tbl_sector_hour):
            for r in range(min(n, tbl.rowCount())):
                it = QTableWidgetItem(self._sector_label(r, n))
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                tbl.setItem(r, 0, it)
        self._prefill_sector_tables()

    def _prefill_tables(self):
        """按数据预填各指数表（每桶中位数 alpha）；只填空白格。"""
        alpha = self._step_alphas()
        if not np.isfinite(alpha).any():
            return
        idx = self._ds.df.index
        fill_1d(self.tbl_month, [float(np.nanmedian(alpha[idx.month == m]))
                                 for m in range(1, 13)])
        fill_1d(self.tbl_hour, [float(np.nanmedian(alpha[idx.hour == h]))
                                for h in range(24)])
        self._prefill_sector_tables()
        months = idx.month.values - 1
        hours = idx.hour.values
        fill_2d(self.tbl_month_hour,
                [[float(np.nanmedian(alpha[(hours == h) & (months == m)]))
                  for m in range(12)] for h in range(24)])

    def _prefill_sector_tables(self):
        alpha = self._step_alphas()
        if not np.isfinite(alpha).any():
            return
        n = self.sector_spin.value()
        idx = self._ds.df.index
        dcol = self.dir_combo.currentData()
        if not dcol or dcol not in self._ds.df.columns:
            return
        dirs = _to_num(self._ds.df[dcol]).to_numpy()
        sec = self._sector_index(dirs, n)
        months = idx.month.values - 1
        hours = idx.hour.values
        fill_1d(self.tbl_sector,
                [float(np.nanmedian(alpha[sec == i])) for i in range(n)])
        fill_2d(self.tbl_sector_month,
                [[float(np.nanmedian(alpha[(sec == i) & (months == m)]))
                  for m in range(12)] for i in range(n)])
        fill_2d(self.tbl_sector_hour,
                [[float(np.nanmedian(alpha[(sec == i) & (hours == h)]))
                  for h in range(24)] for i in range(n)])

    # ---------- 执行 ----------
    def _read_heights(self) -> list[float]:
        out = []
        for r in range(self.heights.rowCount()):
            it = self.heights.item(r, 1)
            if it and it.text().strip():
                try:
                    v = float(it.text().strip())
                    if v > 0:
                        out.append(v)
                except ValueError:
                    pass
        return out

    def _alpha_lookup(self) -> np.ndarray:
        """按当前模式为每个时间步生成 alpha 数组。"""
        idx = self._ds.df.index
        mode = self.alpha_method.currentIndex()
        n = len(idx)
        if mode == 1:
            return np.full(n, self.alpha_const.value())
        months = idx.month.values - 1
        hours = idx.hour.values
        if mode == 2:
            col = read_col(self.tbl_month)
            return np.array([col[m] for m in months])
        if mode == 3:
            col = read_col(self.tbl_hour)
            return np.array([col[h] for h in hours])
        n_sec = self.sector_spin.value()
        dcol = self.dir_combo.currentData()
        dirs = _to_num(self._ds.df[dcol]).to_numpy() if dcol else None
        if dirs is None:
            return np.full(n, np.nan)
        sec = self._sector_index(dirs, n_sec)
        if mode == 4:
            col = read_col(self.tbl_sector)
            return np.array([col[s] for s in sec])
        if mode == 5:
            mat = read_mat(self.tbl_month_hour)
            return np.array([mat[hours[i], months[i]] for i in range(n)])
        if mode == 6:
            mat = read_mat(self.tbl_sector_month)
            return np.array([mat[sec[i], months[i]] for i in range(n)])
        if mode == 7:
            mat = read_mat(self.tbl_sector_hour)
            return np.array([mat[sec[i], hours[i]] for i in range(n)])
        return np.full(n, np.nan)

    def _on_ok(self):
        ds = self._ds
        heights = self._read_heights()
        if not heights:
            QMessageBox.warning(self, tr('参数不足'),
                                tr('请至少指定一个源高度和一个目标高度'))
            return
        idx = ds.df.index
        generated = []

        # ---- Wind speed ----
        if self.chk_speed.isChecked():
            mode = self.alpha_method.currentIndex()
            if mode == 0:
                srcs = self._checked_speed_src()
                if len(srcs) < 2:
                    QMessageBox.warning(self, tr('参数不足'),
                                        tr('至少需要两层风速'))
                    return
                z = np.array([h for _, h in srcs])
                lz = np.log(z)
                mz = lz.mean()
                V = np.column_stack([_to_num(ds.df[c]).to_numpy()
                                     for c, _ in srcs])
                with np.errstate(all='ignore'):
                    L = np.log(V)
                valid = np.isfinite(L).all(axis=1)
                mL = np.where(valid, np.nanmean(L, axis=1), 0)
                num = np.nansum((L - mL[:, None]) * (lz - mz), axis=1)
                den = float(((lz - mz) ** 2).sum())
                alpha = np.where(valid, num / den if den else np.nan, np.nan)
                if self.chk_restrict.isChecked():
                    alpha = np.clip(alpha, self.alpha_min.value(),
                                    self.alpha_max.value())
                a_int = np.where(valid, mL - alpha * mz, np.nan)
                ref0, z_ref0 = srcs[0]
                v_ref0 = _to_num(ds.df[ref0])
                for zt in heights:
                    res = pd.Series(np.exp(a_int + alpha * np.log(zt)),
                                    index=idx)
                    out = build_canon_name('Speed', zt, '', 'Avg')
                    if not self._emit(out, res, 'speed', zt):
                        return
                    generated.append(out)
                    self._auto_sd(zt, res, ref0, v_ref0)
            else:
                ref = self.ref_combo.currentData()
                if not ref or ref not in ds.df.columns:
                    QMessageBox.warning(self, tr('参数不足'),
                                        tr('请至少指定一个源高度和一个目标高度'))
                    return
                z_ref = ds.channels[ref].height or 10.0
                v_ref = _to_num(ds.df[ref])
                alpha_t = self._alpha_lookup()
                for zt in heights:
                    res = v_ref * (zt / z_ref) ** alpha_t
                    out = build_canon_name('Speed', zt, '', 'Avg')
                    if not self._emit(out, res, 'speed', zt):
                        return
                    generated.append(out)
                    self._auto_sd(zt, res, ref, v_ref)

        # ---- Wind direction ----
        if self.chk_dir.isChecked():
            ref = self.veer_ref.currentData()
            if not ref or ref not in ds.df.columns:
                QMessageBox.warning(self, tr('参数不足'),
                                    tr('请勾选 Wind direction'))
                return
            z_ref = ds.channels[ref].height or 10.0
            d_ref = _to_num(ds.df[ref]).to_numpy()
            mode = self.veer_method.currentIndex()
            if mode == 0:
                rates = self._veer_step_rates()
                if self.chk_veer_restrict.isChecked():
                    rates = np.clip(rates, self.veer_min.value(),
                                    self.veer_max.value())
            else:
                rates = self._veer_lookup()
            sd_ref = self._find_dir_sd(ref)
            for zt in heights:
                d_h = (d_ref + rates * (zt - z_ref) / 100.0) % 360.0
                res = pd.Series(d_h, index=idx)
                out = build_canon_name('Dir', zt, '', 'Avg')
                if not self._emit(out, res, 'dir', zt):
                    return
                generated.append(out)
                if sd_ref:
                    sd_out = build_canon_name('Dir', zt, '', 'SD')
                    if sd_out not in ds.df.columns:
                        ds.df[sd_out] = ds.df[sd_ref]
                        ds.channels[sd_out] = Channel(
                            name=sd_out, kind='dir', height=zt, units='deg',
                            role='SD')

        # ---- Temperature ----
        if self.chk_temp.isChecked():
            ref = self.temp_ref.currentData()
            if not ref or ref not in ds.df.columns:
                QMessageBox.warning(self, tr('参数不足'),
                                    tr('请勾选 Temperature'))
                return
            z_ref = ds.channels[ref].height or 10.0
            t_ref = _to_num(ds.df[ref])
            mode = self.grad_method.currentIndex()
            if mode == 0:
                srcs = sorted(self._checked_temp_src(), key=lambda x: x[1])
                if len(srcs) < 2:
                    QMessageBox.warning(self, tr('参数不足'),
                                        tr('至少需要两层温度'))
                    return
                z = np.array([h for _, h in srcs])
                mz = z.mean()
                T = np.column_stack([_to_num(ds.df[c]).to_numpy()
                                     for c, _ in srcs])
                mT = np.nanmean(T, axis=1)
                num = np.nansum((T - mT[:, None]) * (z - mz), axis=1)
                den = float(((z - mz) ** 2).sum())
                grad = np.where(num is not None,
                                num / den * 100.0 if den else np.nan, np.nan)
                grad = np.asarray(grad, dtype=float)
                grad[~np.isfinite(grad)] = np.nan
                if self.chk_grad_restrict.isChecked():
                    grad = np.clip(grad, self.grad_min.value(),
                                   self.grad_max.value())
                b_int = np.where(np.isfinite(grad),
                                 mT - (grad / 100.0) * mz, np.nan)
                for zt in heights:
                    res = pd.Series(b_int + (grad / 100.0) * zt, index=idx)
                    out = build_canon_name('Temp', zt, '', 'Avg')
                    if not self._emit(out, res, 'temp', zt):
                        return
                    generated.append(out)
            else:
                grad_t = self._grad_lookup()
                for zt in heights:
                    res = t_ref + grad_t * (zt - z_ref) / 100.0
                    out = build_canon_name('Temp', zt, '', 'Avg')
                    if not self._emit(out, res, 'temp', zt):
                        return
                    generated.append(out)

        self._info = tr('已生成外推通道') + f' ({len(generated)})'
        self.accept()

    def _emit(self, out: str, res: pd.Series, kind: str, zt: float) -> bool:
        df = self._ds.df
        if out in df.columns:
            QMessageBox.warning(None, tr('重名'),
                                tr('输出通道「{}」已存在', out))
            return False
        units = {'speed': 'm/s', 'dir': 'deg', 'temp': '°C'}.get(kind, '')
        df[out] = res
        self._ds.channels[out] = Channel(name=out, kind=kind, height=zt,
                                         units=units, role='Avg')
        return True

    def result_info(self):
        return self._info


def fill_1d(tbl: QTableWidget, values: list[float]):
    """填充第 1 列指数；空白格才填（保留用户编辑），NaN 跳过。"""
    for r, v in enumerate(values):
        if r >= tbl.rowCount() or v is None or not np.isfinite(v):
            continue
        old = tbl.item(r, 1)
        if old is not None and old.text().strip():
            continue
        tbl.setItem(r, 1, QTableWidgetItem(f'{v:.4g}'))


def fill_2d(tbl: QTableWidget, mat: list[list[float]]):
    for r, row in enumerate(mat):
        if r >= tbl.rowCount():
            continue
        for c, v in enumerate(row):
            if c + 1 >= tbl.columnCount():
                continue
            if v is None or not np.isfinite(v):
                continue
            old = tbl.item(r, c + 1)
            if old is not None and old.text().strip():
                continue
            tbl.setItem(r, c + 1, QTableWidgetItem(f'{v:.4g}'))


def read_col(tbl: QTableWidget) -> list[float]:
    out = []
    for r in range(tbl.rowCount()):
        it = tbl.item(r, 1)
        try:
            out.append(float(it.text()) if it else np.nan)
        except (ValueError, TypeError):
            out.append(np.nan)
    return out


def read_mat(tbl: QTableWidget) -> list[list[float]]:
    out = []
    for r in range(tbl.rowCount()):
        row = []
        for c in range(1, tbl.columnCount()):
            it = tbl.item(r, c)
            try:
                row.append(float(it.text()) if it else np.nan)
            except (ValueError, TypeError):
                row.append(np.nan)
        out.append(row)
    return np.array(out, dtype=float)
