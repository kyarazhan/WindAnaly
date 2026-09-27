"""UI 离屏冒烟的 pytest 入口（S3-4：纳入回归）。

QT_QPA_PLATFORM=offscreen 下创建主窗口、8 Tab、9 菜单与主要对话框；
在无显示环境（CI）与开发机均可运行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def test_ui_smoke():
    from tools.smoke_ui import run_smoke
    run_smoke()
