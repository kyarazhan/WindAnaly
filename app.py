"""WindAnaly：测风塔数据风资源分析工作台（主窗口）。

入口 windanaly.py 创建本窗口；构造时接受 dataset_spec（台账库序号或
文件路径）并自动载入。
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

ICON = resource_path('icon.png')

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

# ---------------------------------------------------------------------------
# 数据文件格式（对齐 Windographer 原版「Open」对话框的过滤器架构）
# ---------------------------------------------------------------------------
# 各厂商后缀 → 说明
_EXT_WIND = ('.windog', '.rwd', '.ndf', '.txt', '.csv', '.xls', '.xlsx',
             '.rld', '.nsd', '.zph', '.sta', '.wnd', '.dat', '.tsv')
_EXT_WINDOGRAPHER = ('.windog',)
_EXT_SYMPHONIE = ('.rwd', '.nsd')
_EXT_SYMPHONIE_PRO = ('.rld',)
_EXT_NOMAD2 = ('.ndf',)
_EXT_ZEPHIR = ('.csv', '.zph')
_EXT_WINDCUBE = ('.sta',)
_EXT_KINTECH = ('.wnd',)
_EXT_TEXT = ('.txt', '.tsv', '.dat')
_EXT_EXCEL = ('.xls', '.xlsx')
_EXT_CSV = ('.csv',)

# 递归扫描目录时接受的全部后缀（覆盖上面所有厂商格式）
_SCAN_EXTS = tuple(sorted(set(
    _EXT_WIND + _EXT_SYMPHONIE + _EXT_SYMPHONIE_PRO + _EXT_NOMAD2
    + _EXT_ZEPHIR + _EXT_WINDCUBE + _EXT_KINTECH + _EXT_TEXT
    + _EXT_EXCEL + _EXT_CSV + _EXT_WINDOGRAPHER)))


def _ext_filter(name: str, exts) -> str:
    """构造 '说明 (*.a *.b)' 形式的 Qt 文件过滤器。"""
    return f'{name} ({" ".join("*" + e for e in exts)})'


# 项目文件优先，其后按原版顺序列出各厂商格式
FILE_OPEN_FILTER = ';;'.join([
    'WindAnaly 项目 (*.windanaly *.windrefine)',
    _ext_filter('Wind Data Files', _EXT_WIND),
    _ext_filter('Windographer Files', _EXT_WINDOGRAPHER),
    _ext_filter('Symphonie Data Logger Files', _EXT_SYMPHONIE),
    _ext_filter('SymphoniePRO Files', _EXT_SYMPHONIE_PRO),
    _ext_filter('Nomad2 Data Files', _EXT_NOMAD2),
    _ext_filter('ZephIR Data Files', _EXT_ZEPHIR),
    _ext_filter('Windcube Statistics Files', _EXT_WINDCUBE),
    _ext_filter('Kintech Engineering Data Files', _EXT_KINTECH),
    _ext_filter('Text Files', _EXT_TEXT),
    _ext_filter('CSV Files', _EXT_CSV),
    _ext_filter('Excel Files', _EXT_EXCEL),
    'All Files (*.*)',
])


def merge_frames(base_df: pd.DataFrame | None, new_df: pd.DataFrame) -> pd.DataFrame:
    """时间轴拼接 + 同名列覆盖，用于「增加」语义。

    - 已存在的时间戳：用新数据按列覆盖（NaN 不覆盖，避免把有效值抹掉）；
    - 新出现的时间戳：整行追加；
    - 新出现的通道列：在旧数据上补 NaN 后填充。
    结果按时间排序。
    """
    if base_df is None or base_df.empty:
        return new_df.sort_index()
    df = base_df.copy()
    if new_df is None or new_df.empty:
        return df.sort_index()
    # 新增列先以 NaN 补齐，保持列对齐
    for c in new_df.columns:
        if c not in df.columns:
            df[c] = np.nan
    # 同索引位置用新值覆盖（update 只写非 NA，逐列对齐）
    df.update(new_df)
    # 追加旧数据里没有的时间戳
    extra = new_df.index.difference(df.index)
    if len(extra):
        df = pd.concat([df, new_df.loc[extra]], axis=0)
    return df.sort_index()


def scan_data_files(folder: str, recursive: bool = True) -> list[str]:
    """递归收集目录下所有支持的数据文件（含 n 级子目录）。"""
    out: list[str] = []
    if not folder or not os.path.isdir(folder):
        return out
    if recursive:
        for root, _dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(_SCAN_EXTS):
                    out.append(os.path.join(root, f))
    else:
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if os.path.isfile(p) and f.lower().endswith(_SCAN_EXTS):
                out.append(p)
    return sorted(out)


class AnalysisApp(UpdateMixin, QMainWindow):
    """WindAnaly 主窗口。

    顶部为 Windographer 风格一级 Tab（Summary/Time Series/Wind Rose/...），
    每个 Tab 内部采用「左侧控制面板 + 右侧绘图/表格区」布局。
    """

    TABS = [
        ('Summary', SummaryTab),
        ('Time Series', TimeSeriesTab),
        ('Wind Rose', WindRoseTab),
        ('Diurnal Profile', DiurnalTab),
        ('Histogram', HistogramTab),
        ('Scatter Plot', ScatterTab),
        ('Data Table', TablesTab),
        ('Report', ReportsTab),
    ]

    def __init__(self, dataset_spec: str = '', project: Project | None = None,
                 confirm: bool = True):
        super().__init__()
        self.setWindowTitle('WindAnaly · Data Analysis')
        self.resize(1360, 840)
        self._confirm = confirm        # 是否在载入时弹出通道确认对话框
        if os.path.exists(ICON):
            self.setWindowIcon(QIcon(ICON.replace('\\', '/')))

        self.project = project if project is not None else Project()
        self.dataset_spec = dataset_spec

        i18n.ensure_defaults()
        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._setup_update()
        self._retranslate_ui()

        # 构造完成后再载入数据，确保各 Tab 已存在并可刷新
        if dataset_spec:
            ok, msg = self._load_spec(dataset_spec)
            self.statusBar().showMessage(msg)
            if ok:
                self._refresh_tabs()
        else:
            self.statusBar().showMessage(
                '就绪 · 未载入数据集 · 可「数据管理软件」载入')

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部栏：菜单栏 + 工具栏（作为普通 widget 放进布局，
        # 完全不依赖 QMainWindow.setMenuBar/addToolbar/QMenuBar/QToolBar，
        # 避免某些 Windows 环境下原生菜单栏/工具栏完全不渲染的问题。
        self._top_bar = QWidget()
        self._top_bar.setObjectName('topBar')
        self._top_bar.setFixedHeight(48)
        self._top_bar.setStyleSheet('background:#eef1f5;')
        top_lay = QVBoxLayout(self._top_bar)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(0)
        self._menubar = FallbackMenuBar(self._top_bar, height=24)
        self._menubar.setObjectName('mainMenuBar')
        top_lay.addWidget(self._menubar)
        self._toolbar = FallbackToolBar(self._top_bar, height=24)
        self._toolbar.setObjectName('quickToolbar')
        top_lay.addWidget(self._toolbar)
        # 快捷工具栏换行增高时，顶栏高度随之调整（菜单 24 + 工具栏行数×24）
        # BISECT: self._toolbar.heightChanged.connect(self._on_toolbar_height)
        root.addWidget(self._top_bar)

        # 主 Tab 区
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)
        self._tab_pages = []
        for name, cls in self.TABS:
            page = cls()
            page.set_project(self.project)
            self.tabs.addTab(page, name)
            self._tab_pages.append(page)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        # 诊断期：强制左到右排版，排除 RTL 环境导致菜单栏/工具栏右对齐
        self.setLayoutDirection(Qt.LeftToRight)
        self._update_geom_hud()

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

    # ---- 文件/窗口/帮助等菜单 handler ----
    # ---- Window 菜单：子窗口级联/平铺/全部关闭 ----
    def _child_windows(self):
        """本软件打开的可见子窗口（QMainWindow，不含主窗口与启动器）。"""
        from PySide6.QtWidgets import QMainWindow
        out = []
        for w in QApplication.topLevelWidgets():
            if (isinstance(w, QMainWindow) and w is not self
                    and w.isVisible()):
                out.append(w)
        return out

    def _cascade_windows(self):
        for i, w in enumerate(self._child_windows()):
            w.showNormal()
            w.move(self.x() + 40 + 30 * i, self.y() + 40 + 30 * i)
            w.raise_()

    def _tile_windows(self):
        wins = self._child_windows()
        if not wins:
            return
        screen = self.screen().availableGeometry()
        n = len(wins)
        rows = int(n ** 0.5)
        cols = -(-n // rows) if rows else 1
        w_w = max(screen.width() // max(cols, 1), 200)
        w_h = max(screen.height() // max(rows, 1), 150)
        for i, w in enumerate(wins):
            r, c = divmod(i, cols)
            w.showNormal()
            w.setGeometry(screen.x() + c * w_w, screen.y() + r * w_h,
                          w_w, w_h)

    def _close_all_windows(self):
        for w in self._child_windows():
            w.close()

    def _export_translations(self):
        """导出翻译对照表 CSV 供用户编辑。"""
        from core import i18n
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Translation Table',
            os.path.join(os.path.expanduser('~'), 'Desktop',
                         'windanaly_translations.csv'),
            'CSV (*.csv)')
        if not path:
            return
        i18n.export_translation_table(path)
        QMessageBox.information(self, 'Export',
                                f'Translation table exported to:\n{path}')

    def _import_translations(self):
        """导入用户编辑后的翻译对照表。"""
        from core import i18n
        path, _ = QFileDialog.getOpenFileName(
            self, 'Import Translation Table', '',
            'CSV (*.csv);;All Files (*)')
        if not path:
            return
        i18n.import_translation_table(path)
        self._retranslate_ui()
        self._refresh_toolbar()
        QMessageBox.information(
            self, 'Import',
            f'Translation table imported from:\n{path}\n'
            f'UI text refreshed.')

    def _on_new(self):
        """新建项目：清空当前会话。"""
        self.project = Project()
        self._last_project_path = ''
        for p in self._tab_pages:
            p.set_project(self.project)
            p.refresh()
        self.statusBar().showMessage('已新建项目')

    def _on_open(self):
        """打开：既支持 .windanaly/.windrefine 项目，也支持各厂商原始数据格式。"""
        path, _ = QFileDialog.getOpenFileName(
            self, '打开', '', FILE_OPEN_FILTER)
        if not path:
            return
        if path.lower().endswith(('.windanaly', '.windrefine')):
            self._load_project_path(path)
        else:
            ok, msg = self._load_files([path], mode='open')
            self.statusBar().showMessage(msg)
            if ok:
                self._add_recent_file(path, os.path.basename(path), 'file')
                self._refresh_tabs()

    def _on_link_vault(self):
        """从测风塔台账数据库链接数据集，或直接打开台账数据库。"""
        dlg = LinkLibraryDialog(self)
        dlg.exec()

    def _export_to_db(self):
        """把当前活动数据集导出到台账数据库（internal 宽表）。"""
        from core.db_transfer import export_dataset_to_db
        from core.i18n import tr
        ds = self.project.active_dataset
        if ds is None or not ds.has_data():
            QMessageBox.warning(
                self, tr('Export to Database...'),
                tr('No active data set. Open a data set first.'))
            return
        try:
            serial, name, n = export_dataset_to_db(ds)
        except Exception as e:
            QMessageBox.critical(self, tr('Export to Database...'), str(e))
            return
        self.project.log('导出到数据库', f'序列号 {serial} · {name}', 'WindAnaly')
        self.statusBar().showMessage(
            tr('Exported to database: serial {} · {} · {} columns',
               serial, name, n))
        QMessageBox.information(
            self, tr('Export to Database...'),
            tr('Exported to database:\nSerial {} · {}\n'
               '{} columns stored.', serial, name, n))

    def _on_open_folder(self):
        """打开文件夹：递归读取目录及所有子目录里的数据文件，合并为一个数据集。"""
        folder = QFileDialog.getExistingDirectory(self, '打开文件夹', '')
        if not folder:
            return
        paths = scan_data_files(folder)
        if not paths:
            QMessageBox.information(
                self, '无数据文件',
                f'该目录及其子目录下未找到支持的数据文件。\n\n'
                f'支持的后缀：{" ".join(_SCAN_EXTS)}')
            return
        ok, msg = self._load_files(paths, mode='open', folder=folder)
        self.statusBar().showMessage(msg)
        if ok:
            self._refresh_tabs()

    def _on_append(self):
        """增加：把新数据文件的通道拼接/覆盖到已打开的数据上。"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, '增加数据', '', FILE_OPEN_FILTER)
        if not paths:
            return
        ok, msg = self._load_files(paths, mode='append')
        self.statusBar().showMessage(msg)
        if ok:
            self._add_recent_file(paths[0], os.path.basename(paths[0]), 'file')
            self._refresh_tabs()

    def _on_append_folder(self):
        """增加目录：递归读取目录及所有子目录的数据，拼接到已打开的数据上。"""
        folder = QFileDialog.getExistingDirectory(self, '增加目录', '')
        if not folder:
            return
        paths = scan_data_files(folder)
        if not paths:
            QMessageBox.information(
                self, '无数据文件',
                f'该目录及其子目录下未找到支持的数据文件。\n\n'
                f'支持的后缀：{" ".join(_SCAN_EXTS)}')
            return
        ok, msg = self._load_files(paths, mode='append', folder=folder)
        self.statusBar().showMessage(msg)
        if ok:
            self._refresh_tabs()

    def _on_close_dataset(self):
        """关闭当前数据集。"""
        name = (self.project.active_dataset.name
                if self.project.active_dataset else '')
        self.project.log('关闭数据集', name)
        self.project.datasets.clear()
        self.project.active = -1
        for p in self._tab_pages:
            p.refresh()
        self.statusBar().showMessage('已关闭数据集')

    def _on_save(self):
        """保存项目；若已有路径则直接覆盖，否则弹出另存为。"""
        if getattr(self, '_last_project_path', ''):
            self._save_project_to(self._last_project_path)
        else:
            self._on_save_as()

    def _on_save_as(self):
        """另存为项目。"""
        ds = self.project.active_dataset
        if ds is None:
            QMessageBox.information(self, '无数据', '请先载入数据集再保存项目')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '另存为', 'WindAnaly项目.windanaly',
            'WindAnaly 项目 (*.windanaly);;所有文件 (*.*)')
        if path:
            self._save_project_to(path)

    def _save_project_to(self, path: str):
        """实际保存项目到 path，并更新最近文件。"""
        if not path.lower().endswith(('.windanaly', '.windrefine')):
            path += '.windanaly'
        try:
            self.project.save_project(
                path, source=getattr(self.project, '_source', None))
            self._last_project_path = path
            self._add_recent_file(path, os.path.basename(path), 'project')
            self.statusBar().showMessage(f'项目已保存：{path}')
            self.project.log('保存项目', path)
        except Exception as e:
            QMessageBox.warning(self, '保存失败', f'{e}')

    def _on_new_window(self):
        """新建一个 WindAnaly 窗口。"""
        win = AnalysisApp()
        win.show()
        win.raise_()
        self.statusBar().showMessage('已新建窗口')

    def _open_homepage(self):
        """访问项目主页（GitHub 仓库）。"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(
            QUrl('https://github.com/kyarazhan/WindAnaly'))

    def _on_version_history(self):
        """查看版本历史（GitHub Releases 页，含各版更新说明）。"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(
            QUrl('https://github.com/kyarazhan/WindAnaly/releases'))

    def _show_about(self):
        """关于对话框。"""
        from core.version import VERSION
        QMessageBox.about(
            self, '关于 WindAnaly',
            f'<b>WindAnaly</b> v{VERSION}<br>测风塔数据风资源分析工作台<br><br>'
            '基于 PySide6 构建，参考 Windographer 工程方法设计。')

    def _on_configure_dataset(self):
        """打开 Configure Data Set 对话框。"""
        ds = self.project.active_dataset
        if ds is None or ds.df.empty:
            QMessageBox.information(self, '无数据', '请先载入数据集')
            return
        dlg = ConfigureDatasetDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._update_selection(ds)
            self._refresh_tabs()
            self.project.log('配置数据集', f'{len(ds.channels)} 通道启用', ds.name)
            self.statusBar().showMessage(
                f'数据集已配置：{len(ds.channels)} 通道启用')

    def _on_calibration(self):
        """打开 Calibration 校准对话框。"""
        ds = self.project.active_dataset
        if ds is None or ds.df.empty:
            QMessageBox.information(self, '无数据', '请先载入数据集')
            return
        dlg = CalibrationDialog(ds, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('校准', '已更新校准常量', ds.name)
            self.statusBar().showMessage('校准常量已更新')

    # ---- 修正(R) 子功能 ----
    def _revise_guard(self) -> Dataset | None:
        """修正类功能的统一数据守卫。"""
        ds = self.project.active_dataset
        if ds is None or ds.df.empty:
            QMessageBox.information(self, '无数据', '请先载入数据集')
            return None
        return ds

    def _on_apply_scale_offset(self):
        ds = self._revise_guard()
        if ds is None:
            return
        dlg = ApplyScaleOffsetDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._update_selection(ds)
            self._refresh_tabs()
            self.project.log('应用比例与偏移', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage('已应用比例与偏移')

    def _on_apply_time_shift(self):
        ds = self._revise_guard()
        if ds is None:
            return
        dlg = ApplyTimeShiftDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('应用时移',
                             f'平移 {getattr(dlg, "_shift", "")}', ds.name)
            self.statusBar().showMessage('已应用时移')

    def _on_delete_data(self):
        ds = self._revise_guard()
        if ds is None:
            return
        dlg = DeleteDataDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._update_selection(ds)
            self._refresh_tabs()
            self.project.log('删除数据', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage('已删除数据')

    def _on_fill_gaps(self):
        ds = self._revise_guard()
        if ds is None:
            return
        dlg = FillGapsDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('插补缺失值', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage('已插补缺失值')

    def _on_fix_quantization(self):
        ds = self._revise_guard()
        if ds is None:
            return
        dlg = FixQuantizationDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('修复量化', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage('已修复量化')

    def _on_combine_sensors(self):
        ds = self._revise_guard()
        if ds is None:
            return
        dlg = CombineSensorsDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._update_selection(ds)
            self._refresh_tabs()
            self.project.log('组合风速仪', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage('已组合风速仪')

    def _on_vertical_extrapolation(self):
        ds = self._revise_guard()
        if ds is None:
            return
        dlg = VerticalExtrapolationDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._update_selection(ds)
            self._refresh_tabs()
            self.project.log('垂直外推', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage('已垂直外推')

    def _on_language_settings(self):
        """打开语言设置。"""
        dlg = LanguageSettingsDialog(self)
        dlg.exec()

    # ---- 标记菜单 ----
    def _guard_data(self, title: str = '无数据'):
        ds = self.project.active_dataset
        if ds is None or ds.df.empty:
            QMessageBox.information(self, title, '请先载入数据集')
            return None
        return ds

    def _on_flag_manually(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = ManualFlagDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('手动标记', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage(getattr(dlg, '_info', '手动标记已应用'))

    def _on_flag_scatter(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = FlagByScatterDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('散点图标记', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage(getattr(dlg, '_info', '散点图标记已应用'))

    def _on_flag_rule(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = FlagWithRulesDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('规则标记', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage(getattr(dlg, '_info', '规则标记已执行'))

    def _on_flag_tower_shadow(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = FlagTowerShadowDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('塔影标记', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage(getattr(dlg, '_info', '塔影标记已执行'))

    def _on_flag_inspect(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = InspectFlagsDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('检查标记', getattr(dlg, '_info', ''), ds.name)
            self.statusBar().showMessage(getattr(dlg, '_info', '标记已检查'))

    def _on_define_flags(self):
        ds = self.project.active_dataset
        dlg = DefineFlagsDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('定义标记', '已更新标记类型', ds.name if ds else '')
            self.statusBar().showMessage('标记类型已更新')

    def _on_define_favorite_flags(self):
        ds = self.project.active_dataset
        dlg = DefineFavoriteFlagsDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_tabs()
            self.project.log('定义常用标记', '已更新常用标记', ds.name if ds else '')
            self.statusBar().showMessage('常用标记已更新')

    def _on_view_favorite_rules(self):
        ds = self.project.active_dataset
        dlg = ViewFavoriteFlagRulesDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    # ---- 分析菜单 ----
    def _on_data_recovery(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = DataRecoveryDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_turbulence(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = TurbulenceDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_wind_shear(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = WindShearDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_wind_speed_distribution(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = WindSpeedDistributionDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_speed_ratios(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = WindSpeedRatiosDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_tower_distortion(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = TowerDistortionDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_temperature_profile(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = TemperatureProfileDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_turbine_output(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = WindTurbineOutputDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_inflow_angle(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = InflowAngleDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_wind_power_class(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = WindPowerClassDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_short_time_interval(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = ShortTimeIntervalDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_long_term_analysis(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = LongTermAnalysisDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_exceedance_probability(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = ProbabilityOfExceedenceDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_extreme_wind(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = ExtremeWindAnalysisDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_representative_year(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = RepresentativeYearDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_forecast_error(self):
        ds = self._guard_data()
        if ds is None:
            return
        dlg = ForecastErrorAnalysisDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    # ---- Compare 菜单 ----
    def _on_compare_datasets(self):
        # Compare Data Sets 允许空数据进入，用户可在对话框内再选择/导入数据
        dlg = CompareDataSetsDialog(self.project.datasets, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_mcp(self):
        # MCP 是独立工具流程，允许空数据进入，用户可在 Import Data Tab 中导入
        dlg = MeasureCorrelatePredictDialog(self.project.datasets, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    # ---- Tools 菜单 ----
    def _on_standard_atmosphere(self):
        dlg = StandardAtmosphereDialog(parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_air_density(self):
        dlg = AirDensityDialog(parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_synthesize_wind(self):
        dlg = SynthesizeWindDataDialog(parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_wind_shear_tool(self):
        dlg = WindShearToolDialog(parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_extreme_wind_tool(self):
        dlg = ExtremeWindToolDialog(parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_turbine_output_estimator(self):
        dlg = WindTurbineOutputEstimatorDialog(parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_turbine_library(self):
        dlg = WindTurbineLibraryDialog(parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    def _on_options(self):
        dlg = OptionsDialog(parent=self)
        dlg.exec()

    # ---- 最近文件 ----
    def _add_recent_file(self, path: str, name: str, kind: str):
        """向 settings 写入一条最近文件/项目记录，最多保留 3 条。"""
        recents = settings.get('analy_recent_files', [])
        recents = [r for r in recents if r.get('path') != path]
        recents.insert(0, {'path': path, 'name': name, 'kind': kind})
        recents = recents[:3]
        settings.set('analy_recent_files', recents)
        self._update_recent_menu()

    def _update_recent_menu(self):
        """刷新文件菜单的「最近文件」子菜单。"""
        if self._recent_menu is None:
            return
        self._recent_menu.clear()
        recents = settings.get('analy_recent_files', [])
        if not recents:
            a = self._recent_menu.addAction('(无)')
            a.setEnabled(False)
            return
        for i, r in enumerate(recents, 1):
            name = r.get('name') or os.path.basename(r.get('path', ''))
            a = self._recent_menu.addAction(
                f'{i} {name}',
                lambda p=r.get('path'), k=r.get('kind'): self._open_recent(p, k))
            a.setToolTip(r.get('path', ''))

    def _open_recent(self, path: str, kind: str):
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, '文件不存在', f'路径已失效：{path}')
            return
        if kind == 'project':
            self._load_project_path(path)
        else:
            ok, msg = self._load_spec(f'file:{path}')
            self.statusBar().showMessage(msg)
            if ok:
                self._add_recent_file(path, os.path.basename(path), 'file')
                self._refresh_tabs()

    def _load_project_path(self, path: str):
        """打开指定路径的项目文件；若用户误选数据文件，自动降级为打开数据。"""
        # 非 .windanaly/.windrefine 文件 → 作为原始数据打开（避免用户误点「打开项目」选 txt/csv 后报编码错）
        if not path.lower().endswith(('.windanaly', '.windrefine')):
            ok, msg = self._load_spec(f'file:{path}')
            self.statusBar().showMessage(msg)
            if ok:
                self._add_recent_file(path, os.path.basename(path), 'file')
                self._refresh_tabs()
            else:
                QMessageBox.warning(self, '打开失败', msg)
            return
        try:
            self.project.load_project(path)
            self._last_project_path = path
            self._add_recent_file(path, os.path.basename(path), 'project')
            ds = self.project.active_dataset
            if ds is not None:
                self._update_selection(ds)
            self._refresh_tabs()
            n = self.project.active_dataset.n_flags() if ds else 0
            self.statusBar().showMessage(f'项目已恢复：{path}（剔除 {n} 点）')
            self.project.log('恢复项目', path, ds.name if ds else '')
        except Exception as e:
            QMessageBox.warning(self, '打开失败', f'{e}')

    def _toggle_toolbar(self):
        if self._toolbar is not None:
            self._toolbar.setVisible(not self._toolbar.isVisible())

    def _toggle_statusbar(self):
        self.statusBar().setVisible(not self.statusBar().isVisible())

    def _save_screenshot(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '保存截图', 'WindAnaly.png',
            'PNG 图像 (*.png);;所有文件 (*.*)')
        if path:
            self.grab().save(path)
            self.statusBar().showMessage(f'截图已保存：{path}')

    def _export_data(self):
        ds = self.project.active_dataset
        if ds is None or ds.df.empty:
            QMessageBox.information(self, '无数据', '无数据可导出')
            return
        from ui.dialogs.export_dialog import ExportDataDialog
        dlg = ExportDataDialog(ds, parent=self)
        self._place_dialog_below_menubar(dlg)
        dlg.exec()

    # ---- 剔除标记 ----
    def _flag_by_range(self):
        ds = self.project.active_dataset
        if ds is None or ds.df.empty:
            QMessageBox.information(self, '无数据', '请先载入数据集')
            return
        from PySide6.QtWidgets import QInputDialog
        s, ok1 = QInputDialog.getText(self, '标记剔除', '起始时间 (YYYY-MM-DD HH:MM)：',
                                      text=str(ds.df.index[0]))
        if not ok1:
            return
        e, ok2 = QInputDialog.getText(self, '标记剔除', '结束时间 (YYYY-MM-DD HH:MM)：',
                                      text=str(ds.df.index[-1]))
        if not ok2:
            return
        try:
            ds.set_flag_range(s, e)
        except Exception as ex:
            QMessageBox.warning(self, '标记失败', f'{ex}')
            return
        self._refresh_tabs()
        self.statusBar().showMessage(f'已标记剔除：{ds.n_flags()} 个时间点')
        self.project.log('标记剔除', f'{s} ~ {e}', f'{ds.n_flags()} 点')

    def _clear_flags(self):
        ds = self.project.active_dataset
        if ds is None:
            return
        ds.clear_flags()
        self._refresh_tabs()
        self.statusBar().showMessage('已清除全部剔除标记')

    def _show_flag_stats(self):
        ds = self.project.active_dataset
        if ds is None or ds.df.empty:
            QMessageBox.information(self, '无数据', '无数据')
            return
        n = ds.n_flags()
        rate = n / len(ds.df) * 100 if len(ds.df) else 0
        QMessageBox.information(
            self, '剔除统计',
            f'数据集：{ds.name}\n总点数：{len(ds.df):,}\n'
            f'已剔除：{n:,}（{rate:.2f}%）')

    def _on_tab_changed(self, idx: int):
        if 0 <= idx < len(self._tab_pages):
            self._tab_pages[idx].refresh()

    def _refresh_tabs(self):
        for p in self._tab_pages:
            p.refresh()
        # 保险：每次刷新后强制菜单栏/工具栏可见
        try:
            if hasattr(self, '_menubar') and self._menubar is not None:
                self._menubar.setVisible(True)
            if hasattr(self, '_toolbar') and self._toolbar is not None:
                self._toolbar.setVisible(True)
            self._update_geom_hud()
        except Exception:
            pass

    def _place_dialog_below_menubar(self, dlg):
        """把子对话框定位到菜单栏+工具栏下方，避免遮挡顶部操作区。"""
        try:
            from PySide6.QtWidgets import QApplication
            mb_h = self._menubar.height()
            tb_h = self._toolbar.height() if getattr(self, '_toolbar', None) else 0
            top = mb_h + tb_h + 2
            screen = QApplication.primaryScreen().availableGeometry()
            w = min(dlg.width(), screen.width())
            h = min(dlg.height(), max(300, screen.height() - top - 20))
            dlg.resize(w, h)
            dlg.move(max(0, (screen.width() - w) // 2), top)
        except Exception:
            pass

    # ---- 首页展示 / Tab 可见性 ----
    def _apply_tab_visibility(self):
        """按 settings['analy_tabs_visible'] 恢复各 Tab 的显示状态。

        兼容旧版中文 Tab 名：自动映射为英文底座并回写 settings，
        避免切换语言底座后所有 Tab 被隐藏。
        """
        raw = settings.get('analy_tabs_visible',
                           [t for t, _ in self.TABS])
        en_titles = {t for t, _ in self.TABS}
        # 旧版英文/中文 Tab 名 -> 现名（Diurnal 改版为 Diurnal Profile）
        legacy = {'Diurnal': 'Diurnal Profile', '日变化': 'Diurnal Profile'}
        # 中文翻译 -> 英文底座
        zh_to_en = {i18n.DEFAULT_TRANSLATIONS.get(t, t): t for t in en_titles}
        normalized = []
        for name in raw:
            if name in en_titles:
                normalized.append(name)
            elif name in legacy:
                normalized.append(legacy[name])
            elif name in zh_to_en:
                normalized.append(zh_to_en[name])
        if normalized != raw:
            settings.set('analy_tabs_visible', normalized)
        visible = set(normalized)
        for idx, (title, _) in enumerate(self.TABS):
            self.tabs.setTabVisible(idx, title in visible)
        # 若当前页被隐藏，切到首个可见页
        if not self.tabs.isTabVisible(self.tabs.currentIndex()):
            for i in range(self.tabs.count()):
                if self.tabs.isTabVisible(i):
                    self.tabs.setCurrentIndex(i)
                    break

    def _on_tab_visibility(self, idx: int, checked: bool):
        """勾选/取消首页展示中的 Tab，控制其在主窗口的显示。"""
        self.tabs.setTabVisible(idx, checked)
        if checked:
            self.tabs.setCurrentIndex(idx)
        else:
            for i in range(self.tabs.count()):
                if self.tabs.isTabVisible(i):
                    self.tabs.setCurrentIndex(i)
                    break
        # 持久化可见列表（始终使用英文底座）
        if self._tab_actions:
            vis = [t for t, a in self._tab_actions.items() if a.isChecked()]
            settings.set('analy_tabs_visible', vis)
        self._refresh_tabs()

    # ---- 独立视图窗口 ----
    def _open_data_coverage(self):
        DataCoverageWindow(self).show()

    def _open_doc_history(self):
        DocumentHistoryWindow(self).show()

    def _open_dmap(self):
        DMapWindow(self).show()

    def _open_boxplot(self):
        BoxplotWindow(self).show()

    def _open_cdf(self):
        CDFWindow(self).show()

    # ---- 自动载入唤醒数据 ----
    def _load_spec(self, spec: str, confirm: bool | None = None):
        """解析 dataset_spec（library:<ds_id> / file:<路径>）载入 Project。

        confirm 控制是否弹出通道确认对话框；None 时使用实例的 self._confirm。"""
        from core.io_import import parse_file
        try:
            if spec.startswith('library:'):
                ds_id = int(spec.split(':', 1)[1])
                lib = Library()
                ds_rows = [d for d in lib.list_datasets() if d['id'] == ds_id]
                if not ds_rows:
                    return False, f'未找到数据集（id={ds_id}），可能已被删除'
                row = ds_rows[0]
                rec = lib.get_station(int(row['serial_no'])) or {}
                if row['mode'] == 'internal':
                    df = lib.load_series(ds_id)
                else:
                    df = parse_file(row['path']).df
                name = (f"{rec.get('station_no') or rec.get('location') or ds_id}"
                        f"（{row['t_start']}~{row['t_end']}）")
                channels = row.get('channels') or []
            elif spec.startswith('file:'):
                path = spec.split(':', 1)[1]
                if not os.path.exists(path):
                    return False, f'文件不存在：{path}'
                p = parse_file(path)
                df, row = p.df, None
                rec = {'station_no': p.station_no, 'location': p.location,
                       'lat': p.lat, 'lon': p.lon, 'elevation': p.elevation,
                       'device_type': getattr(p, 'device_type', '未知')}
                name = os.path.basename(path)
                channels = p.channels
            else:
                return False, f'无法识别的数据集标识：{spec}'

            # 构建通道定义（含启用状态），供导入确认与持久化。
            # orig = 导入时的真实原始列名（文件分支从 col_origins 反查，
            # 库分支 channels_json 已带），保证「原始标签」列不与
            # 标准化标签混同。
            file_origins = {}
            if spec.startswith('file:'):
                file_origins = {v: k for k, v in
                                (getattr(p, 'col_origins', {}) or {}).items()}
            parsed = []
            for ch in (channels or []):
                if isinstance(ch, str):
                    try:
                        ch = json.loads(ch)
                    except Exception:
                        continue
                orig = file_origins.get(ch['name'],
                                        ch.get('orig') or ch['name'])
                parsed.append({
                    'name': ch['name'], 'kind': ch.get('kind', 'other'),
                    'height': ch.get('height'), 'units': ch.get('units', ''),
                    'role': ch.get('role', ''), 'orig': orig, 'enabled': True,
                })
            # 构建 Dataset（先按默认分类填充）
            ds = Dataset(name=name)
            ds.df = df
            ds.attrs = {
                'lat': rec.get('lat'),
                'lon': rec.get('lon'),
                'elevation': rec.get('elevation'),
                't_start': rec.get('t_start') or (row.get('t_start') if row else None),
                't_end': rec.get('t_end') or (row.get('t_end') if row else None),
                'device_type': rec.get('device_type'),
            }
            ds.import_meta = parsed
            for ch in parsed:
                if not ch.get('enabled', True):
                    continue
                ds.add_channel(Channel(
                    name=ch['name'], kind=ch.get('kind', 'other'),
                    height=ch.get('height'), units=ch.get('units', ''),
                    role=ch.get('role', '')))

            # 导入确认 / 配置数据集：两 Tab 对话框，取消则中止导入
            do_confirm = (self._confirm if confirm is None else confirm)
            if do_confirm and parsed and QApplication.instance() is not None \
                    and not os.environ.get('WINDREFINE_TEST'):
                dlg = ConfigureDatasetDialog(ds, parent=self)
                # 定位到主窗口菜单栏+工具栏下方，避免遮挡顶部
                self._place_dialog_below_menubar(dlg)
                if dlg.exec() != QDialog.Accepted:
                    return False, '用户取消配置数据集，导入已中止'
            # 记录来源（项目持久化 / 恢复用）
            src = ({'type': 'library', 'ds_id': ds_id, 'name': name}
                   if spec.startswith('library:')
                   else {'type': 'file',
                         'path': (path if 'path' in locals() else spec.split(':', 1)[1]),
                         'name': name})
            self.project._source = src
            self.project.datasets.clear()
            self.project.add_dataset(ds)
            self._update_selection(ds)
            self.project.log('载入数据',
                             f'{len(df)} 行 · {len(ds.channels)} 通道', name)
            return True, (f'已载入：{name} · {len(df)} 行 · '
                          f'{len(ds.channels)} 通道（启用）')
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, f'载入失败：{e}'

    # ------------------------------------------------------------------
    # 多文件载入：打开 / 打开文件夹 / 增加 / 增加目录
    # ------------------------------------------------------------------
    def _load_files(self, paths: list[str], mode: str = 'open',
                    folder: str = '') -> tuple[bool, str]:
        """解析一个或多个数据文件并载入。

        mode='open'   → 替换当前数据集（打开 / 打开文件夹）
        mode='append' → 拼接/覆盖到已打开的数据集上（增加 / 增加目录）
        识别逻辑与「打开」完全一致（共用 parse_file）。
        """
        from core.io_import import parse_file

        paths = [p for p in (paths or []) if p and os.path.exists(p)]
        if not paths:
            return False, '未选择任何文件'
        base = self.project.active_dataset
        if mode == 'append' and (base is None or base.df.empty):
            mode = 'open'          # 没有已打开的数据，退化为打开
            base = None

        dfs: list[pd.DataFrame] = []
        chan_map: dict = {}
        first: object | None = None
        failed: list[str] = []
        for p in paths:
            try:
                parsed = parse_file(p)
            except Exception as e:
                failed.append(f'{os.path.basename(p)}: {e}')
                continue
            if parsed.df is None or parsed.df.empty:
                failed.append(f'{os.path.basename(p)}: 无有效数据行')
                continue
            dfs.append(parsed.df)
            if first is None:
                first = parsed
            for ch in (parsed.channels or []):
                old = chan_map.get(ch['name'])
                if old is None:
                    chan_map[ch['name']] = dict(ch)
                else:
                    # 同名通道：保留先解析到的定义，缺失项由后者补齐
                    for k, v in ch.items():
                        if not old.get(k):
                            old[k] = v
        if not dfs:
            return False, '所选文件均无法解析为测风数据' + (
                '：' + '；'.join(failed[:3]) if failed else '')

        # 多文件合并（时间轴拼接 + 覆盖）
        df = dfs[0]
        for extra_df in dfs[1:]:
            df = merge_frames(df, extra_df)
        channels = list(chan_map.values())

        # 「增加」：与已打开数据按时间轴拼接/覆盖
        if mode == 'append' and base is not None:
            df = merge_frames(base.df, df)
            for name, ch in (base.channels or {}).items():
                old = chan_map.get(name)
                if old is None:
                    chan_map[name] = {
                        'name': name, 'kind': ch.kind, 'height': ch.height,
                        'units': ch.units, 'role': ch.role}
            channels = list(chan_map.values())

        # 站点元信息取首个成功解析的文件
        p0 = first
        rec = {'station_no': getattr(p0, 'station_no', ''),
               'location': getattr(p0, 'location', ''),
               'lat': getattr(p0, 'lat', None),
               'lon': getattr(p0, 'lon', None),
               'elevation': getattr(p0, 'elevation', None),
               'device_type': getattr(p0, 'device_type', '未知')}
        if folder:
            name = f'{os.path.basename(folder)}（{len(dfs)} 个文件）'
        elif len(paths) == 1:
            name = os.path.basename(paths[0])
        else:
            name = f'{len(dfs)} 个文件'

        # 构建 Dataset
        parsed_meta = []
        for ch in channels:
            parsed_meta.append({
                'name': ch['name'], 'kind': ch.get('kind', 'other'),
                'height': ch.get('height'), 'units': ch.get('units', ''),
                'role': ch.get('role', ''), 'enabled': True,
            })
        ds = Dataset(name=name)
        ds.df = df
        ds.attrs = {
            'lat': rec.get('lat'), 'lon': rec.get('lon'),
            'elevation': rec.get('elevation'),
            't_start': str(df.index[0]) if len(df) else None,
            't_end': str(df.index[-1]) if len(df) else None,
            'device_type': rec.get('device_type'),
        }
        ds.import_meta = parsed_meta
        for ch in parsed_meta:
            ds.add_channel(Channel(
                name=ch['name'], kind=ch.get('kind', 'other'),
                height=ch.get('height'), units=ch.get('units', ''),
                role=ch.get('role', '')))

        # 配置数据集确认（文件夹/多文件也只弹一次）
        if self._confirm and parsed_meta and QApplication.instance() is not None \
                and not os.environ.get('WINDREFINE_TEST'):
            dlg = ConfigureDatasetDialog(ds, parent=self)
            self._place_dialog_below_menubar(dlg)
            if dlg.exec() != QDialog.Accepted:
                return False, '用户取消配置数据集，导入已中止'

        self.project._source = {
            'type': 'folder' if folder else 'file',
            'path': folder or paths[0], 'name': name,
            'files': paths, 'mode': mode,
        }
        if mode == 'open':
            self.project.datasets.clear()
            self.project.add_dataset(ds)
        else:
            # 增加：替换当前数据集（内容已含旧数据），保持只有一个活动数据集
            if self.project.datasets:
                idx = max(0, self.project.active)
                if idx < len(self.project.datasets):
                    self.project.datasets[idx] = ds
                else:
                    self.project.add_dataset(ds)
            else:
                self.project.add_dataset(ds)
        self._update_selection(ds)
        self.project.log('载入数据' if mode == 'open' else '增加数据',
                         f'{len(df)} 行 · {len(ds.channels)} 通道', name)
        verb = '已载入' if mode == 'open' else '已增加'
        tail = ''
        if failed:
            tail = f'（{len(failed)} 个文件跳过）'
        return True, (f'{verb}：{name} · {len(df)} 行 · '
                      f'{len(ds.channels)} 通道{tail}')

    def _update_selection(self, ds: Dataset):
        """根据通道类型设定默认活动通道。"""
        sel = self.project.selection
        speeds = [c.name for c in ds.channels.values() if c.kind == 'speed']
        dirs = [c.name for c in ds.channels.values() if c.kind == 'dir']
        temps = [c.name for c in ds.channels.values() if c.kind == 'temp']
        pres = [c.name for c in ds.channels.values() if c.kind == 'pres']
        if speeds:
            # 优先选择高度最大者作为默认主风速
            speeds_h = [(c.height or 0, c.name) for c in ds.channels.values()
                        if c.kind == 'speed']
            sel['speed'] = max(speeds_h, key=lambda x: x[0])[1]
        if dirs:
            sel['dir'] = dirs[0]
        if temps:
            sel['temp'] = temps[0]
        if pres:
            sel['pres'] = pres[0]
        sel['sectors'] = 16

    def _open_data_dialog(self):
        """弹窗让用户选择库内数据集或 CSV 文件。"""
        choices = ['台账库内数据集', 'CSV/TXT 原始文件']
        from PySide6.QtWidgets import QInputDialog
        choice, ok = QInputDialog.getItem(
            self, '打开数据', '数据来源：', choices, 0, False)
        if not ok:
            return
        if choice == choices[0]:
            lib = Library()
            rows = lib.list_datasets()
            items = [f"{r['id']} · 序列号 {r['serial_no']} · {r['t_start']}~{r['t_end']}"
                     for r in rows]
            if not items:
                QMessageBox.information(self, '无数据', '台账库中暂无数据集')
                return
            item, ok = QInputDialog.getItem(self, '选择数据集', '数据集：', items, 0, False)
            if ok:
                ds_id = int(item.split('·')[0].strip())
                ok2, msg = self._load_spec(f'library:{ds_id}')
                self.statusBar().showMessage(msg)
                if ok2:
                    self._refresh_tabs()
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, '选择原始数据文件', '',
                '测风数据文件 (*.txt *.csv *.xls *.xlsx *.asc *.sta *.row '
                '*.rwd *.rld *.ndf);;所有文件 (*.*)')
            if path:
                ok2, msg = self._load_spec(f'file:{path}')
                self.statusBar().showMessage(msg)
                if ok2:
                    self._refresh_tabs()

    def closeEvent(self, event):
        self._stop_update()
        super().closeEvent(event)

    def showEvent(self, event):
        """每次显示都强制顶部栏可见，并同步顶栏高度（工具栏可能已换行）。"""
        super().showEvent(event)
        try:
            if hasattr(self, '_menubar') and self._menubar is not None:
                self._menubar.setVisible(True)
            if hasattr(self, '_toolbar') and self._toolbar is not None:
                self._toolbar.setVisible(True)
                if hasattr(self, '_top_bar') and self._top_bar is not None:
                    self._top_bar.setVisible(True)
                    self._top_bar.setFixedHeight(24 + self._toolbar.height())
            self._update_geom_hud()
        except Exception:
            pass

    def resizeEvent(self, event):
        """窗口缩放时刷新顶部栏几何诊断，并同步顶栏高度。"""
        super().resizeEvent(event)
        try:
            if hasattr(self, '_top_bar') and self._top_bar is not None \
                    and hasattr(self, '_toolbar') and self._toolbar is not None:
                self._top_bar.setFixedHeight(24 + self._toolbar.height())
        except RuntimeError:
            pass
        self._update_geom_hud()

    def _update_geom_hud(self):
        """原临时诊断已移除；保留空方法避免调用点改动。"""
        pass


def run_analysis(dataset_spec: str = '', confirm: bool = True):
    """独立运行 WindAnaly（可携带来源 spec）。

    confirm=True 时载入原始文件会弹出通道确认对话框。"""
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    qss = os.path.abspath(os.path.join(
        os.path.dirname(__file__), 'ui', 'theme.qss'))
    if os.path.exists(qss):
        with open(qss, 'r', encoding='utf-8') as f:
            app.setStyleSheet(f.read())
    win = AnalysisApp(dataset_spec=dataset_spec, confirm=confirm)
    win.show()
    app.exec()


if __name__ == '__main__':
    run_analysis()
