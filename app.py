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
from ui.app_loader import LoaderMixin
from ui.app_menus import MenusMixin
from ui.app_project import ProjectIoMixin


ICON = resource_path('icon.png')


class AnalysisApp(UpdateMixin, MenusMixin, ProjectIoMixin, LoaderMixin,
                  QMainWindow):
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
