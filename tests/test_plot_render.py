"""PlotCanvas 渲染冒烟测试（B4 验收：拆分后各图型路径不回归）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope='module')
def canvas():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from ui.modules.plot import PlotCanvas
    c = PlotCanvas()
    yield c
    c.close()


def _assert_rendered(c):
    pm = c.grab()
    assert not pm.isNull()
    assert pm.size().width() >= 50


def test_plot_line(canvas):
    idx = pd.date_range('2026-01-01', periods=500, freq='h')
    canvas.plot_line(idx, np.sin(np.linspace(0, 20, 500)), label='WS80')
    _assert_rendered(canvas)


def test_plot_lines_multi(canvas):
    x = np.arange(300)
    canvas.plot_lines([('A', x, np.random.rand(300)),
                       ('B', x, np.random.rand(300))])
    _assert_rendered(canvas)


def test_plot_scatter(canvas):
    n = 200
    canvas.plot_scatter(np.random.rand(n) * 10, np.random.rand(n) * 10)
    _assert_rendered(canvas)


def test_plot_histogram(canvas):
    counts, edges = np.histogram(np.random.normal(8, 2, 1000), bins=20)
    canvas.plot_histogram(edges, counts)
    _assert_rendered(canvas)


def test_plot_bar(canvas):
    canvas.plot_bar(['a', 'b', 'c'], [1.0, 2.0, 3.0])
    _assert_rendered(canvas)


def test_plot_heatmap(canvas):
    canvas.plot_heatmap(np.random.rand(12, 4),
                        [str(i) for i in range(4)],
                        [str(m) for m in range(1, 13)])
    _assert_rendered(canvas)


def _box_stats(arr):
    return {'min': float(arr.min()), 'max': float(arr.max()),
            'q1': float(np.percentile(arr, 25)),
            'q3': float(np.percentile(arr, 75)),
            'med': float(np.median(arr)), 'mean': float(arr.mean())}


def test_plot_box(canvas):
    a, b = np.random.rand(50), np.random.rand(50)
    canvas.plot_box([('A', _box_stats(a)), ('B', _box_stats(b))])
    _assert_rendered(canvas)


def test_plot_table(canvas):
    canvas.plot_table([['WS80', '7.9'], ['WS50', '7.1']], ['Ch', 'Mean'])
    _assert_rendered(canvas)


def test_plot_polar(canvas):
    n = 500
    sectors = 16
    speed = np.random.rand(n) * 12
    dirs = np.random.rand(n) * 360
    freq = np.zeros(sectors)
    idx = np.minimum((dirs / (360 / sectors)).astype(int), sectors - 1)
    for i in idx:
        freq[i] += 1
    freq /= freq.sum()
    canvas.plot_polar(sectors, freq, title='Rose')
    _assert_rendered(canvas)
