"""PlotCanvas：QPainter 自绘图表控件（零新增依赖）。
from __future__ import annotations

支持：plot_line / plot_bar / plot_scatter / plot_polar(风玫瑰) / plot_table
      / plot_heatmap(数据覆盖·DMap) / plot_box(箱线图)。
布局采用 "10% padding" 原则：
  - X 轴标签在下 8%，Y 轴在左 8%，标题在上 5%。
  - 实际绘图区 = rect 剩余内部。
颜色遵循中文工程报告习惯：风速蓝、风向绿、温度橙、气压紫、湿度青。
"""


import math
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetrics, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPushButton,
                               QSizePolicy, QSpinBox, QTabWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from core.i18n import tr




class PlotPropertiesDialog(QDialog):
    """图表属性：Axes / Channels / Fonts 三页。"""

    def __init__(self, canvas: PlotCanvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self.setWindowTitle(tr('Properties'))
        self.resize(520, 420)

        data = canvas._data
        props = canvas._props
        self._orig = {
            'title': canvas.title,
            'xlabel': data.get('xlabel', props.get('xlabel', '')),
            'ylabel': data.get('ylabel', props.get('ylabel', '')),
            'y2label': props.get('y2label', ''),
            'xunit': props.get('xunit', ''),
            'yunit': props.get('yunit', ''),
            'y2unit': props.get('y2unit', ''),
            'xaxis_log': props.get('xaxis_log', False),
            'yaxis_log': props.get('yaxis_log', False),
            'y2axis_log': props.get('y2axis_log', False),
            'xaxis_min': props.get('xaxis_min'),
            'xaxis_max': props.get('xaxis_max'),
            'yaxis_min': data.get('ymin', props.get('yaxis_min')),
            'yaxis_max': data.get('ymax', props.get('yaxis_max')),
            'y2axis_min': props.get('y2axis_min'),
            'y2axis_max': props.get('y2axis_max'),
            'grid_major': props.get('grid_major', True),
            'grid_minor': props.get('grid_minor', True),
            'font_size': props.get('font_size', 10),
            'show_grid': getattr(canvas, '_show_grid', True),
        }

        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        self.tabs.addTab(self._build_axes_tab(), tr('Axes'))
        self.tabs.addTab(self._build_channels_tab(), tr('Channels'))
        self.tabs.addTab(self._build_fonts_tab(), tr('Fonts'))

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        ok = QPushButton('OK')
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _build_axes_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        # Labels
        g = QGridLayout()
        g.addWidget(QLabel(tr('Title')), 0, 0)
        self.e_title = QLineEdit(self._orig['title'])
        g.addWidget(self.e_title, 0, 1, 1, 2)

        g.addWidget(QLabel(tr('X axis label')), 1, 0)
        self.e_xlabel = QLineEdit(self._orig['xlabel'])
        g.addWidget(self.e_xlabel, 1, 1)
        g.addWidget(QLabel(tr('Units')), 1, 2)
        self.e_xunit = QLineEdit(self._orig['xunit'])
        g.addWidget(self.e_xunit, 1, 3)

        g.addWidget(QLabel(tr('Y axis label')), 2, 0)
        self.e_ylabel = QLineEdit(self._orig['ylabel'])
        g.addWidget(self.e_ylabel, 2, 1)
        g.addWidget(QLabel(tr('Units')), 2, 2)
        self.e_yunit = QLineEdit(self._orig['yunit'])
        g.addWidget(self.e_yunit, 2, 3)

        g.addWidget(QLabel(tr('Y2 axis label')), 3, 0)
        self.e_y2label = QLineEdit(self._orig['y2label'])
        g.addWidget(self.e_y2label, 3, 1)
        g.addWidget(QLabel(tr('Units')), 3, 2)
        self.e_y2unit = QLineEdit(self._orig['y2unit'])
        g.addWidget(self.e_y2unit, 3, 3)
        v.addLayout(g)

        # 三列轴设置
        h = QHBoxLayout()
        h.addLayout(self._axis_group('X axis', 'x'))
        h.addLayout(self._axis_group('Y axis', 'y'))
        h.addLayout(self._axis_group('Y2 axis', 'y2'))
        v.addLayout(h)
        v.addStretch(1)
        return w

    def _axis_group(self, title: str, prefix: str):
        g = QGridLayout()
        g.addWidget(QLabel(title), 0, 0, 1, 2)
        log = QCheckBox(tr('Logarithmic'))
        log.setChecked(self._orig[f'{prefix}axis_log'])
        g.addWidget(log, 1, 0, 1, 2)
        setattr(self, f'cb_{prefix}_log', log)

        g.addWidget(QLabel(tr('Fix minimum')), 2, 0)
        emin = QLineEdit('' if self._orig[f'{prefix}axis_min'] is None else str(self._orig[f'{prefix}axis_min']))
        emin.setMaximumWidth(60)
        g.addWidget(emin, 2, 1)
        setattr(self, f'e_{prefix}_min', emin)

        g.addWidget(QLabel(tr('Fix maximum')), 3, 0)
        emax = QLineEdit('' if self._orig[f'{prefix}axis_max'] is None else str(self._orig[f'{prefix}axis_max']))
        emax.setMaximumWidth(60)
        g.addWidget(emax, 3, 1)
        setattr(self, f'e_{prefix}_max', emax)

        # 对 Y/Y2 显示 grid 选项
        if prefix != 'x':
            cb_major = QCheckBox(tr('Gridlines at major division'))
            cb_major.setChecked(self._orig['grid_major'])
            g.addWidget(cb_major, 4, 0, 1, 2)
            setattr(self, f'cb_{prefix}_major', cb_major)
            cb_minor = QCheckBox(tr('Gridlines at minor division'))
            cb_minor.setChecked(self._orig['grid_minor'])
            g.addWidget(cb_minor, 5, 0, 1, 2)
            setattr(self, f'cb_{prefix}_minor', cb_minor)
        return g

    def _build_channels_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        # 通道列表
        self.lw_channels = QTableWidget()
        self.lw_channels.setColumnCount(3)
        self.lw_channels.setHorizontalHeaderLabels(['Channel', 'Label', 'Color'])
        self.lw_channels.setSelectionBehavior(QTableWidget.SelectRows)
        self.lw_channels.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        h.addWidget(self.lw_channels, 1)

        # 右侧属性
        form = QGridLayout()
        form.addWidget(QLabel(tr('Label')), 0, 0)
        self.e_ch_label = QLineEdit()
        form.addWidget(self.e_ch_label, 0, 1)
        form.addWidget(QLabel(tr('Color')), 1, 0)
        self.e_ch_color = QLineEdit()
        form.addWidget(self.e_ch_color, 1, 1)
        h.addLayout(form)
        v.addLayout(h)

        # 填充通道
        series = []
        if self._canvas._kind == 'lines':
            series = [s[0] for s in self._canvas._data.get('series', [])]
        elif self._canvas._kind == 'line':
            lbl = self._canvas._data.get('label', '')
            if lbl:
                series = [lbl]
        elif self._canvas._kind == 'polar':
            series = list(self._canvas._data.get('labels') or [])
        self.lw_channels.setRowCount(len(series))
        styles = self._canvas._props.get('channel_styles', {})
        for r, lbl in enumerate(series):
            item = QTableWidgetItem(lbl)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.lw_channels.setItem(r, 0, item)
            self.lw_channels.setItem(r, 1, QTableWidgetItem(styles.get(lbl, {}).get('label', lbl)))
            self.lw_channels.setItem(r, 2, QTableWidgetItem(styles.get(lbl, {}).get('color', '')))
        self.lw_channels.resizeColumnsToContents()
        self.lw_channels.itemSelectionChanged.connect(self._on_channel_select)
        self.e_ch_label.textChanged.connect(self._on_channel_label_changed)
        self.e_ch_color.textChanged.connect(self._on_channel_color_changed)
        return w

    def _on_channel_select(self):
        rows = self.lw_channels.selectedIndexes()
        if not rows:
            return
        r = rows[0].row()
        self.e_ch_label.setText(self.lw_channels.item(r, 1).text())
        self.e_ch_color.setText(self.lw_channels.item(r, 2).text())

    def _on_channel_label_changed(self, text: str):
        rows = self.lw_channels.selectedIndexes()
        if not rows:
            return
        self.lw_channels.item(rows[0].row(), 1).setText(text)

    def _on_channel_color_changed(self, text: str):
        rows = self.lw_channels.selectedIndexes()
        if not rows:
            return
        self.lw_channels.item(rows[0].row(), 2).setText(text)

    def _build_fonts_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(tr('Specify font sizes by entering sizes directly:')))
        g = QGridLayout()
        labels = ['Graph title', 'Axis titles', 'Axis numbers', 'Legend title', 'Legend text']
        self.font_edits = {}
        for r, lbl in enumerate(labels):
            g.addWidget(QLabel(lbl), r, 0)
            e = QSpinBox()
            e.setRange(6, 24)
            e.setValue(self._orig['font_size'])
            g.addWidget(e, r, 1)
            self.font_edits[lbl] = e
        v.addLayout(g)
        v.addStretch(1)
        return w

    def _accept(self):
        self._canvas.title = self.e_title.text()
        data = self._canvas._data
        data['xlabel'] = self.e_xlabel.text()
        data['ylabel'] = self.e_ylabel.text()
        props = self._canvas._props
        props['xlabel'] = self.e_xlabel.text()
        props['ylabel'] = self.e_ylabel.text()
        props['y2label'] = self.e_y2label.text()
        props['xunit'] = self.e_xunit.text()
        props['yunit'] = self.e_yunit.text()
        props['y2unit'] = self.e_y2unit.text()

        def f(edit):
            v = edit.text().strip()
            return float(v) if v else None

        for prefix in ('x', 'y', 'y2'):
            props[f'{prefix}axis_log'] = getattr(self, f'cb_{prefix}_log').isChecked()
            props[f'{prefix}axis_min'] = f(getattr(self, f'e_{prefix}_min'))
            props[f'{prefix}axis_max'] = f(getattr(self, f'e_{prefix}_max'))
        data['ymin'] = props['yaxis_min']
        data['ymax'] = props['yaxis_max']

        # 网格：三页共用一个开关，取 Y axis 的
        props['grid_major'] = getattr(self, 'cb_y_major', QCheckBox()).isChecked()
        props['grid_minor'] = getattr(self, 'cb_y_minor', QCheckBox()).isChecked()
        self._canvas._show_grid = props['grid_major']

        # 字号
        props['font_size'] = self.font_edits['Axis numbers'].value()

        # 通道样式
        styles = props.get('channel_styles', {})
        for r in range(self.lw_channels.rowCount()):
            orig = self.lw_channels.item(r, 0).text()
            label = self.lw_channels.item(r, 1).text()
            color = self.lw_channels.item(r, 2).text().strip()
            styles[orig] = styles.get(orig, {})
            styles[orig]['label'] = label
            if color:
                styles[orig]['color'] = color
        props['channel_styles'] = styles

        self._canvas.update()
        self.accept()
