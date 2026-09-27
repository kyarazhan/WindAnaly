"""ProjectIoMixin：项目文件（.windanaly）新建/保存/载入 + 最近文件管理。"

从 app.py 拆出（S2）。仅包装「项目持久化」，self.* 引用经 MRO 在运行期解析。
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


class ProjectIoMixin:
    def _on_new(self):
        """新建项目：清空当前会话。"""
        self.project = Project()
        self._last_project_path = ''
        for p in self._tab_pages:
            p.set_project(self.project)
            p.refresh()
        self.statusBar().showMessage('已新建项目')

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
