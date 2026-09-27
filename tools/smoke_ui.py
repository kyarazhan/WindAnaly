"""GUI 离屏冒烟脚本（run_checks.bat 第三步）。

QT_QPA_PLATFORM=offscreen 下创建主窗口与全部 Tab，载入合成数据集刷新，
并构造台账库链接对话框，验证 UI 基本可用。退出码 0 = 通过。
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication([])
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
win.project.add_dataset(ds)
win._update_selection(ds)
win._refresh_tabs()
app.processEvents()

# 台账库链接对话框构造（只读库）
from ui.modules.views import LinkLibraryDialog
dlg = LinkLibraryDialog(win)

win.close()
print('UI SMOKE PASS: title=%s tabs=%d menus=%d' % (
    win.windowTitle(), win.tabs.count(), len(menus)))
