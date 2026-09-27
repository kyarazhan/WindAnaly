"""GUI 离屏冒烟（pytest 由 tests/test_smoke_ui.py 调用；也可直接运行本脚本）。

创建主窗口与全部 Tab，载入合成数据集刷新，构造主要对话框（配置数据集/
数据恢复/导出/双数据集对比），验证 UI 基本可用。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _make_dataset():
    import numpy as np
    import pandas as pd
    from core.dataset import Channel, Dataset

    idx = pd.date_range('2026-01-01', periods=500, freq='10min')
    df = pd.DataFrame({
        'WS80_Avg': 7 + np.random.rand(500),
        'WD80_Avg': (np.random.rand(500) * 360).round(0),
    }, index=idx)
    ds = Dataset('smoke')
    ds.df = df
    ds.flags = pd.Series(False, index=df.index)
    ds.channels = {
        'WS80_Avg': Channel('WS80_Avg', 'speed', 80, 'm/s'),
        'WD80_Avg': Channel('WD80_Avg', 'dir', 80, 'deg'),
    }
    return ds


def run_smoke() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')

    from core import settings
    settings.apply_font_size(app)

    from app import AnalysisApp
    win = AnalysisApp()
    win.show()
    app.processEvents()

    assert win.windowTitle() == 'WindAnaly · Data Analysis', win.windowTitle()
    assert win.tabs.count() == 8, win.tabs.count()
    menus = list(getattr(win._menubar, '_menus', {}).keys())
    assert len(menus) == 9, menus

    win._refresh_tabs()
    app.processEvents()

    # 载入合成数据集并刷新全部 Tab
    ds = _make_dataset()
    win.project.add_dataset(ds)
    win._update_selection(ds)
    win._refresh_tabs()
    app.processEvents()

    # 主要对话框构造（不 exec，构造成功即通过）
    from ui.dialogs.analysis_dialogs import (
        DataRecoveryDialog, TurbulenceDialog, WindShearDialog)
    from ui.dialogs.compare_dialogs import CompareDataSetsDialog
    from ui.dialogs.configure_dataset import ConfigureDatasetDialog
    from ui.dialogs.export_dialog import ExportDataDialog
    from ui.modules.views import LinkLibraryDialog

    dialogs = [
        ConfigureDatasetDialog(ds, parent=win),
        DataRecoveryDialog(ds, parent=win),
        TurbulenceDialog(ds, parent=win),
        WindShearDialog(ds, parent=win),
        CompareDataSetsDialog([ds, ds], parent=win),
        ExportDataDialog(ds, parent=win),
        LinkLibraryDialog(win),
    ]
    for dlg in dialogs:
        app.processEvents()
        dlg.close()
        dlg.deleteLater()

    # 台账库链接（只读）
    link = [d for d in dialogs if isinstance(d, LinkLibraryDialog)][0]
    link.listw.count()

    win.close()
    app.processEvents()
    print('UI SMOKE PASS: title=%s tabs=%d menus=%d dialogs=%d' % (
        win.windowTitle(), win.tabs.count(), len(menus), len(dialogs)))


if __name__ == '__main__':
    run_smoke()
