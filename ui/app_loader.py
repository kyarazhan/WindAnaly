"""LoaderMixin：数据装载与来源解析（打开/增加/目录合并/台账库链接）。"

从 app.py 拆出（S2）。纯合并/扫描逻辑在 core/loader.py；
本 Mixin 只做带 UI 的编排，self.* 引用经 MRO 在运行期解析。
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
from core.loader import (FILE_OPEN_FILTER, _SCAN_EXTS, merge_frames,
                         scan_data_files)


class LoaderMixin:
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
