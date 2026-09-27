"""MenusMixin：主窗口菜单/工具栏构建、语言重翻译、自定义工具栏对话框。

从 app.py 拆出（S2）。仅包装「界面骨架」，动作 handler 仍在 app.py；
self.* 引用经 MRO 在运行期解析，Mixin 不反向 import app。
"""
import json
import os

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog,
                               QFileDialog, QHBoxLayout, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSplitter, QStyle,
                               QTabWidget, QVBoxLayout, QWidget)

from core import i18n, settings
from core.dataset import Channel, Dataset
from core.library import Library
from core.project import Project
from ui.dialogs.calibration import CalibrationDialog
from ui.dialogs.analysis_dialogs import (
    DataRecoveryDialog, TurbulenceDialog, WindShearDialog,
    WindSpeedDistributionDialog, WindSpeedRatiosDialog,
    TowerDistortionDialog, TemperatureProfileDialog,
    WindTurbineOutputDialog, InflowAngleDialog,
    WindPowerClassDialog, ShortTimeIntervalDialog,
    LongTermAnalysisDialog, ProbabilityOfExceedenceDialog,
    ExtremeWindAnalysisDialog, RepresentativeYearDialog,
    ForecastErrorAnalysisDialog)
from ui.dialogs.compare_dialogs import (
    CompareDataSetsDialog, MeasureCorrelatePredictDialog)
from ui.dialogs.configure_dataset import ConfigureDatasetDialog
from ui.dialogs.flag_dialogs import (
    DefineFavoriteFlagsDialog, DefineFlagsDialog, FlagByScatterDialog,
    FlagTowerShadowDialog, FlagWithRulesDialog, InspectFlagsDialog,
    ManualFlagDialog, ViewFavoriteFlagRulesDialog)
from ui.dialogs.language_settings import LanguageSettingsDialog
from ui.dialogs.revise_dialogs import (ApplyScaleOffsetDialog,
                                              ApplyTimeShiftDialog,
                                              CombineSensorsDialog,
                                              DeleteDataDialog,
                                              FillGapsDialog,
                                              FixQuantizationDialog,
                                              VerticalExtrapolationDialog)
from ui.dialogs.tools_dialogs import (
    AirDensityDialog, ExtremeWindToolDialog, OptionsDialog,
    StandardAtmosphereDialog, SynthesizeWindDataDialog,
    WindShearToolDialog, WindTurbineLibraryDialog,
    WindTurbineOutputEstimatorDialog)
from ui.fallback_bar import FallbackMenuBar, FallbackToolBar
from ui.modules.analysis_tabs import (DiurnalTab, HistogramTab,
                                              ReportsTab, ScatterTab,
                                              SummaryTab, TablesTab,
                                              TimeSeriesTab, WindRoseTab)
from ui.modules.views import (CDFWindow, BoxplotWindow,
                                      DMapWindow, DataCoverageWindow,
                                      DocumentHistoryWindow,
                                      LinkLibraryDialog)
from ui.toolbar_icons import toolbar_icon
from ui.update_tools import UpdateMixin

from core.paths import resource_path


# 快捷工具栏按钮的固定文案（与菜单原文不同，按用户指定命名；
# 未列出的 key 使用 QAction 文本净化后的结果）
TOOLBAR_LABELS = {
    'flag_manual': 'Flag Manually',
    'flag_scatter': 'Flag By Scatter Plot',
    'flag_rule': 'Flag With Rules',
    'flag_tower_shadow': 'Flag Tower Shading',
    'flag_inspect': 'Inspect and Remove Flags',
    'data_recovery': 'Data Recovery Analysis',
    'turbulence': 'Turbulence Analysis',
    'wind_shear_analysis': 'Wind Shear Analysis',
    'wind_speed_dist': 'Wind Speed Distribution Analysis',
    'tower_distortion': 'Tower Distortion Analysis',
    'inflow_angle': 'Inflow Angle',
    'turbine_output': 'Wind Turbine Output',
    'short_time_interval': 'Short Time Interval Analysis',
    'about': 'About WindAnaly',
    'help': 'Help',
}


class MenusMixin:
    def _build_menus(self):
        # 菜单栏已在 _build_ui 中创建并放进 _top_bar 布局（不走 QMainWindow 原生插槽），
        # 这里只往里加菜单；文案以英文为底座，经 i18n.tr() 显示。
        bar = self._menubar
        self._actions = {}          # key -> QAction，供工具栏复用

        # File
        fm = QMenu('&File')
        bar.add_menu('&File', fm)
        fm.setObjectName('menu_file')
        fm.menuAction().setData('&File')
        self._add_menu_action(fm, 'new', '&New...', self._on_new, 'Ctrl+N')
        self._add_menu_action(fm, 'open', '&Open...', self._on_open,
                              'Ctrl+O')
        self._add_menu_action(fm, 'open_folder', 'Open Folder...',
                              self._on_open_folder)
        self._add_menu_action(fm, 'append', '&Append...', self._on_append)
        self._add_menu_action(fm, 'append_folder', 'Append Directory...',
                              self._on_append_folder)
        self._add_menu_action(fm, 'close', '&Close', self._on_close_dataset)
        fm.addSeparator()
        self._add_menu_action(fm, 'save', '&Save', self._on_save, 'Ctrl+S')
        self._add_menu_action(fm, 'save_as', 'Save &As...', self._on_save_as)
        self._add_menu_action(fm, 'export_data', '&Export Data...',
                              self._export_data)
        fm.addSeparator()
        # Import from Database 子菜单
        im = fm.addMenu('Import from Database...')
        im.setObjectName('menu_import_db')
        im.menuAction().setData('Import from Database...')
        a = im.addAction('Link Database...', self._on_link_vault)
        a.setData('Link Database...')
        a = fm.addAction('Export to Database...')
        a.setEnabled(True)
        a.triggered.connect(self._export_to_db)
        a.setData('Export to Database...')
        fm.addSeparator()
        self._recent_menu = fm.addMenu('Recent Files')
        self._recent_menu.menuAction().setData('Recent Files')
        self._update_recent_menu()
        fm.addSeparator()
        self._add_menu_action(fm, 'exit', 'E&xit', self.close, 'Alt+F4')

        # View
        vm = QMenu('&View')
        bar.add_menu('&View', vm)
        vm.setObjectName('menu_view')
        vm.menuAction().setData('&View')
        home = vm.addMenu('Home Tabs')
        home.menuAction().setData('Home Tabs')
        self._tab_actions = {}
        visible = settings.get('analy_tabs_visible',
                               [t for t, _ in self.TABS])
        for idx, (title, _) in enumerate(self.TABS):
            act = home.addAction(title)
            act.setCheckable(True)
            act.setChecked(title in visible)
            act.setData(title)
            act.triggered.connect(
                lambda checked, i=idx: self._on_tab_visibility(i, checked))
            self._tab_actions[title] = act
        vm.addSeparator()
        self._view_actions = {}
        view_items = [
            ('data_coverage', 'Data Coverage...', self._open_data_coverage),
            ('doc_history', 'Document History...', self._open_doc_history),
            ('dmap', 'DMap...', self._open_dmap),
            ('boxplot', 'Boxplot...', self._open_boxplot),
            ('cdf', 'CDF...', self._open_cdf),
        ]
        for key, en, slot in view_items:
            a = vm.addAction(en, slot)
            a.setData(en)
            self._view_actions[en] = a
            self._actions[key] = a          # 供快捷工具栏复用
        vm.addSeparator()
        self._add_menu_action(vm, 'toggle_toolbar', 'Toolbar',
                              self._toggle_toolbar)
        self._add_menu_action(vm, 'toggle_statusbar', 'Status Bar',
                              self._toggle_statusbar)

        # Revise
        rm = QMenu('&Revise')
        bar.add_menu('&Revise', rm)
        rm.setObjectName('menu_revise')
        rm.menuAction().setData('&Revise')
        self._add_menu_action(rm, 'configure_dataset',
                              'Configure Data Set...',
                              self._on_configure_dataset)
        self._add_menu_action(rm, 'calibration', 'Calibration...',
                              self._on_calibration)
        self._add_menu_action(rm, 'apply_scale_offset',
                              'Apply Scale and Offset...',
                              self._on_apply_scale_offset)
        self._add_menu_action(rm, 'apply_time_shift',
                              'Apply Time Shift...',
                              self._on_apply_time_shift)
        self._add_menu_action(rm, 'delete_data', 'Delete Data...',
                              self._on_delete_data)
        rm.addSeparator()
        self._add_menu_action(rm, 'fill_gaps', 'Fill Gaps...',
                              self._on_fill_gaps)
        self._add_menu_action(rm, 'fix_quantization',
                              'Fix Quantization...',
                              self._on_fix_quantization)
        rm.addSeparator()
        self._add_menu_action(rm, 'combine_sensors', 'Combine Anemometers...',
                              self._on_combine_sensors)
        self._add_menu_action(rm, 'vertical_extrap',
                              'Vertical Extrapolation...',
                              self._on_vertical_extrapolation)

        # Flag（原版菜单名为单数）
        flm = QMenu('&Flag')
        bar.add_menu('&Flag', flm)
        flm.setObjectName('menu_flags')
        flm.menuAction().setData('&Flag')
        a = flm.addAction('Manual Flag...', self._on_flag_manually)
        a.setData('Manual Flag...')
        self._actions['flag_manual'] = a      # 供快捷工具栏复用
        a = flm.addAction('Flag by Scatter...', self._on_flag_scatter)
        a.setData('Flag by Scatter...')
        self._actions['flag_scatter'] = a
        a = flm.addAction('Flag by Rule...', self._on_flag_rule)
        a.setData('Flag by Rule...')
        self._actions['flag_rule'] = a
        a = flm.addAction('Flag Tower Shadow...', self._on_flag_tower_shadow)
        a.setData('Flag Tower Shadow...')
        self._actions['flag_tower_shadow'] = a
        a = flm.addAction('Check and Remove Flags...',
                          self._on_flag_inspect)
        a.setData('Check and Remove Flags...')
        self._actions['flag_inspect'] = a
        flm.addSeparator()
        self._add_menu_action(flm, 'clear_flags', 'Clear All Flags',
                              self._clear_flags)
        self._add_menu_action(flm, 'flag_stats', 'Flag Statistics',
                              self._show_flag_stats)
        flm.addSeparator()
        a = flm.addAction('Define Flags...', self._on_define_flags)
        a.setData('Define Flags...')
        a = flm.addAction('Define Common Flags...',
                          self._on_define_favorite_flags)
        a.setData('Define Common Flags...')
        a = flm.addAction('View Common Flag Rules...',
                          self._on_view_favorite_rules)
        a.setData('View Common Flag Rules...')

        # Analyze（原版菜单名）
        am = QMenu('&Analyze')
        bar.add_menu('&Analyze', am)
        am.setObjectName('menu_analysis')
        am.menuAction().setData('&Analyze')
        analysis_items = [
            ('data_recovery', 'Data Recovery...', self._on_data_recovery),
            ('turbulence', 'Turbulence...', self._on_turbulence),
            ('wind_shear_analysis', 'Wind Shear...', self._on_wind_shear),
            ('wind_speed_dist', 'Wind Speed Distribution...',
             self._on_wind_speed_distribution),
            ('speed_ratio', 'Speed Ratio...', self._on_speed_ratios),
            ('tower_distortion', 'Tower Shadow Distortion...',
             self._on_tower_distortion),
            ('temperature_profile', 'Temperature Profile...',
             self._on_temperature_profile),
            ('turbine_output', 'Turbine Output...', self._on_turbine_output),
            ('inflow_angle', 'Inflow Angle...', self._on_inflow_angle),
            ('wind_power_class', 'Wind Power Class...',
             self._on_wind_power_class),
        ]
        for key, en, handler in analysis_items:
            a = am.addAction(en, handler)
            a.setData(en)
            self._actions[key] = a           # 供快捷工具栏复用
        am.addSeparator()
        analysis_items2 = [
            ('short_time_interval', 'Short Time Interval...',
             self._on_short_time_interval),
            ('long_term', 'Long-term Analysis...', self._on_long_term_analysis),
            ('exceedance', 'Exceedance Probability...',
             self._on_exceedance_probability),
            ('extreme_wind', 'Extreme Wind Speed...', self._on_extreme_wind),
            ('representative_year', 'Representative Year...',
             self._on_representative_year),
            ('prediction_error', 'Prediction Error...',
             self._on_forecast_error),
        ]
        for key, en, handler in analysis_items2:
            a = am.addAction(en, handler)
            a.setData(en)
            self._actions[key] = a

        # Compare
        cm = QMenu('&Compare')
        bar.add_menu('&Compare', cm)
        cm.setObjectName('menu_compare')
        cm.menuAction().setData('&Compare')
        compare_items = [
            ('Compare Data Sets...', self._on_compare_datasets),
            ('Measure-Correlate-Predict (MCP)...', self._on_mcp),
        ]
        for en, handler in compare_items:
            a = cm.addAction(en, handler)
            a.setData(en)

        # Tools
        tm = QMenu('&Tools')
        bar.add_menu('&Tools', tm)
        tm.setObjectName('menu_tools')
        tm.menuAction().setData('&Tools')
        tools_items = [
            ('Standard Atmosphere...', self._on_standard_atmosphere),
            ('Air Density...', self._on_air_density),
            ('Synthesize Wind Speed Data...', self._on_synthesize_wind),
            ('Wind Shear...', self._on_wind_shear_tool),
            ('Extreme Winds...', self._on_extreme_wind_tool),
        ]
        for en, handler in tools_items:
            a = tm.addAction(en, handler)
            a.setData(en)
        tm.addSeparator()
        tools_items2 = [
            ('Wind Turbine Output Estimator...',
             self._on_turbine_output_estimator),
            ('Wind Turbine Library...', self._on_turbine_library),
        ]
        for en, handler in tools_items2:
            a = tm.addAction(en, handler)
            a.setData(en)
        tm.addSeparator()
        a = tm.addAction('Options...', self._on_options)
        a.setData('Options...')
        tm.addSeparator()
        a = tm.addAction('Customize Toolbar...', self._configure_toolbar)
        a.setData('Customize Toolbar...')
        tm.addSeparator()
        self._add_menu_action(tm, 'export_translations',
                              'Export Translation Table...',
                              self._export_translations)
        self._add_menu_action(tm, 'import_translations',
                              'Import Translation Table...',
                              self._import_translations)

        # Window
        wm = QMenu('&Window')
        bar.add_menu('&Window', wm)
        wm.setObjectName('menu_window')
        wm.menuAction().setData('&Window')
        self._add_menu_action(wm, 'new_window', 'New Window',
                              self._on_new_window)
        wm.addSeparator()
        self._add_menu_action(wm, 'cascade', 'Cascade', self._cascade_windows)
        self._add_menu_action(wm, 'tile', 'Tile', self._tile_windows)
        wm.addSeparator()
        self._add_menu_action(wm, 'close_all', 'Close All Windows',
                              self._close_all_windows)

        # Help：检查更新 / 项目主页 / 版本历史 / Language / About
        # （Contents / License 等占位项已移除；原 Settings 菜单的 Language... 移入此处）
        hm = QMenu('&Help')
        bar.add_menu('&Help', hm)
        hm.setObjectName('menu_help')
        hm.menuAction().setData('&Help')
        self._add_menu_action(hm, 'check_update', 'Check for Updates',
                              self._open_update)
        a = hm.addAction('Project Homepage...', self._open_homepage)
        a.setData('Project Homepage...')
        a = hm.addAction('Version History...', self._on_version_history)
        a.setData('Version History...')
        hm.addSeparator()
        a = hm.addAction('Language...', self._on_language_settings)
        a.setData('Language...')
        hm.addSeparator()
        a = hm.addAction('About WindAnaly', self._show_about)
        a.setData('About WindAnaly')
        self._actions['about'] = a          # 供快捷工具栏复用

        self._apply_tab_visibility()

    def _retranslate_ui(self):
        """按当前 language 刷新菜单、动作、Tab 文案。"""
        self.setWindowTitle(i18n.tr('WindAnaly · Data Analysis'))

        def _retranslate_action(act):
            base = act.data()
            if isinstance(base, str):
                try:
                    act.setText(i18n.tr(base))
                except RuntimeError:
                    # action 的 C++ 对象已被删除，跳过
                    pass

        def _walk(menu):
            for act in menu.actions():
                _retranslate_action(act)
                if act.menu() is not None:
                    try:
                        act.menu().setTitle(i18n.tr(act.data())
                                            if isinstance(act.data(), str)
                                            else act.menu().title())
                    except RuntimeError:
                        pass
                    _walk(act.menu())

        # FallbackMenuBar：遍历 QMenu 对象并重命名顶层按钮；
        # 顶层按钮以 menuAction().data() 中的英文底座为 key，避免切换后 key 丢失。
        for title, menu in list(self._menubar._menus.items()):
            _walk(menu)
            base = menu.menuAction().data()
            if isinstance(base, str):
                new_title = i18n.tr(base)
                if new_title != title:
                    self._menubar.set_menu_title(title, new_title)
        for i, (title, _) in enumerate(self.TABS):
            self.tabs.setTabText(i, i18n.tr(title))
        # _tab_actions / _view_actions 中的 QAction 均挂在 View / Home Tabs 菜单下，
        # 已被 _walk 处理；此处不再重复 setText，避免在某些 Qt 版本中触发
        # "Internal C++ object already deleted" 的竞态崩溃。
        self._toolbar.refresh_text()

    def _add_menu_action(self, menu, key, text, slot=None, shortcut=None):
        """创建 QAction 并注册到 self._actions，供工具栏复用。

        text 为中文 base；setData 保存原文以便切换语言时重刷。"""
        if slot is None:
            a = menu.addAction(text)
            a.setEnabled(False)
        else:
            a = menu.addAction(text, slot)
        if shortcut:
            a.setShortcut(shortcut)
        a.setData(text)
        self._actions[key] = a
        return a

    def _build_toolbar(self):
        # 工具栏已在 _build_ui 中创建并放进 _top_bar 布局（不走 QMainWindow.addToolBar）。
        self._refresh_toolbar()

    def _refresh_toolbar(self):
        """根据 settings['analy_toolbar'] 刷新工具栏按钮（彩色图标）。"""
        tb = self._toolbar
        if tb is None:
            return
        tb.clear()
        configured = settings.get('analy_toolbar',
                                  settings.QUICK_TOOLBAR_DEFAULT)
        # 旧默认布局 → 迁移到扩充后的新布局
        if configured == ['new_window', 'open', 'append', 'save']:
            configured = list(settings.QUICK_TOOLBAR_DEFAULT)
            settings.set('analy_toolbar', configured)
        # 既有布局若缺 about（后加），插到 help 之前
        if 'help' in configured and 'about' not in configured:
            configured = [k for k in configured if k != 'about']
            configured.insert(configured.index('help'), 'about')
            settings.set('analy_toolbar', configured)
        # 工具栏可用动作注册表（key 必须已在 _build_menus 中注册）
        for key in configured:
            if key == 'sep':
                tb.add_separator()
                continue
            a = self._actions.get(key)
            if a is None:
                continue
            label = TOOLBAR_LABELS.get(key) or self._toolbar._clean_tool_text(a.text())
            icon = toolbar_icon(key)
            if icon.isNull():
                tb.add_action(a, None, text=label)
            else:
                tb.add_action(a, icon, text=label, icon_only=True)

    def _toolbar_icon(self, key: str) -> QIcon:
        """返回工具栏按钮图标；缺失时返回空图标（纯文字）。"""
        return toolbar_icon(key, size=16)

    def _on_toolbar_height(self, h: int):
        """快捷工具栏换行增高时同步顶栏高度（菜单栏 24 + 工具栏高度）。

        窗口销毁期间信号可能晚到，此时顶栏 C++ 对象或已析构——忽略。"""
        try:
            self._top_bar.setFixedHeight(24 + h)
        except RuntimeError:
            pass

    def _configure_toolbar(self):
        """弹出对话框，让用户自定义工具栏展示的动作。"""
        dlg = QDialog(self)
        dlg.setWindowTitle('自定义工具栏')
        dlg.resize(520, 360)
        root = QVBoxLayout(dlg)

        available = [
            ('new', 'New'),
            ('new_window', 'New Window'),
            ('open', 'Open'),
            ('open_folder', 'Open Folder'),
            ('append', 'Append'),
            ('append_folder', 'Append Directory'),
            ('close', 'Close'),
            ('save', 'Save'),
            ('save_as', 'Save As'),
            ('export_data', 'Export Data'),
            ('data_coverage', 'Data Coverage'),
            ('doc_history', 'Document History'),
            ('configure_dataset', 'Configure Data Set'),
            ('vertical_extrap', 'Vertical Extrapolation'),
            ('calibration', 'Calibration'),
            ('flag_manual', 'Flag Manually'),
            ('flag_scatter', 'Flag By Scatter Plot'),
            ('flag_rule', 'Flag With Rules'),
            ('flag_tower_shadow', 'Flag Tower Shading'),
            ('flag_inspect', 'Inspect and Remove Flags'),
            ('data_recovery', 'Data Recovery Analysis'),
            ('turbulence', 'Turbulence Analysis'),
            ('wind_shear_analysis', 'Wind Shear Analysis'),
            ('wind_speed_dist', 'Wind Speed Distribution Analysis'),
            ('tower_distortion', 'Tower Distortion Analysis'),
            ('inflow_angle', 'Inflow Angle'),
            ('turbine_output', 'Wind Turbine Output'),
            ('short_time_interval', 'Short Time Interval Analysis'),
                        ('check_update', 'Check for Updates'),
            ('clear_flags', 'Clear All Flags'),
            ('flag_stats', 'Flag Statistics'),
            ('about', 'About WindAnaly'),
        ]
        current = settings.get('analy_toolbar',
                               settings.QUICK_TOOLBAR_DEFAULT)

        h = QHBoxLayout()
        self._avail_list = QListWidget()
        self._avail_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._sel_list = QListWidget()
        self._sel_list.setSelectionMode(QAbstractItemView.ExtendedSelection)

        def _add_item(lst, text, data):
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, data)
            lst.addItem(item)

        for k, t in available:
            if k not in current:
                _add_item(self._avail_list, t, k)
        for k in current:
            text = next((t for kk, t in available if kk == k), k)
            _add_item(self._sel_list, text, k)
        h.addWidget(self._avail_list)
        vbtns = QVBoxLayout()
        btn_add = QPushButton('>')
        btn_rem = QPushButton('<')
        btn_up = QPushButton('↑')
        btn_down = QPushButton('↓')
        vbtns.addStretch()
        vbtns.addWidget(btn_add)
        vbtns.addWidget(btn_rem)
        vbtns.addSpacing(10)
        vbtns.addWidget(btn_up)
        vbtns.addWidget(btn_down)
        vbtns.addStretch()
        h.addLayout(vbtns)
        h.addWidget(self._sel_list)
        root.addLayout(h)

        def _add():
            for it in self._avail_list.selectedItems():
                _add_item(self._sel_list, it.text(), it.data(Qt.UserRole))
            for it in list(self._avail_list.selectedItems()):
                self._avail_list.takeItem(self._avail_list.row(it))

        def _rem():
            for it in self._sel_list.selectedItems():
                _add_item(self._avail_list, it.text(), it.data(Qt.UserRole))
            for it in list(self._sel_list.selectedItems()):
                self._sel_list.takeItem(self._sel_list.row(it))

        def _up():
            rows = sorted({self._sel_list.row(it)
                           for it in self._sel_list.selectedItems()})
            for r in rows:
                if r > 0:
                    it = self._sel_list.takeItem(r)
                    self._sel_list.insertItem(r - 1, it)
                    it.setSelected(True)

        def _down():
            rows = sorted({self._sel_list.row(it)
                           for it in self._sel_list.selectedItems()}, reverse=True)
            for r in rows:
                if r < self._sel_list.count() - 1:
                    it = self._sel_list.takeItem(r)
                    self._sel_list.insertItem(r + 1, it)
                    it.setSelected(True)

        btn_add.clicked.connect(_add)
        btn_rem.clicked.connect(_rem)
        btn_up.clicked.connect(_up)
        btn_down.clicked.connect(_down)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton('取消')
        ok = QPushButton('确定')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(dlg.reject)

        def _accept():
            new_keys = []
            for i in range(self._sel_list.count()):
                new_keys.append(self._sel_list.item(i).data(Qt.UserRole))
            settings.set('analy_toolbar', new_keys)
            self._refresh_toolbar()
            dlg.accept()

        ok.clicked.connect(_accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)
        dlg.exec()
