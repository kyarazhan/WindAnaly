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




class ExportImageDialog(QDialog):
    """导出图片：对齐原版布局，支持 PNG / 剪贴板，含尺寸、字体、线宽、预览。"""

    def __init__(self, canvas: PlotCanvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self.setWindowTitle(tr('Export Image'))
        self.resize(640, 520)

        lay = QVBoxLayout(self)
        settings = QGridLayout()
        settings.setHorizontalSpacing(12)
        settings.setVerticalSpacing(8)

        # Image dimensions
        settings.addWidget(QLabel(tr('Image dimensions')), 0, 0)
        self.sp_w = QSpinBox()
        self.sp_w.setRange(100, 4000)
        self.sp_w.setValue(800)
        self.sp_h = QSpinBox()
        self.sp_h.setRange(100, 4000)
        self.sp_h.setValue(500)
        h_dim = QHBoxLayout()
        h_dim.addWidget(self.sp_w)
        h_dim.addWidget(QLabel('px by'))
        h_dim.addWidget(self.sp_h)
        h_dim.addWidget(QLabel('px'))
        h_dim.addStretch(1)
        settings.addLayout(h_dim, 0, 1, 1, 3)

        self.cb_actual_dim = QCheckBox(tr('Use actual plot dimensions'))
        settings.addWidget(self.cb_actual_dim, 1, 0, 1, 2)

        # Font size / Line width
        settings.addWidget(QLabel(tr('Font size')), 2, 0)
        self.cb_font = QComboBox()
        self.cb_font.addItems(['Small', 'Normal', 'Large'])
        self.cb_font.setCurrentIndex(1)
        settings.addWidget(self.cb_font, 2, 1)
        settings.addWidget(QLabel(tr('Line width')), 2, 2)
        self.cb_lw = QComboBox()
        self.cb_lw.addItems(['Thin', 'Normal', 'Thick'])
        self.cb_lw.setCurrentIndex(1)
        settings.addWidget(self.cb_lw, 2, 3)

        # Include axis labels
        h_labels = QHBoxLayout()
        self.cb_xlabel = QCheckBox(tr('x-axis'))
        self.cb_xlabel.setChecked(True)
        self.cb_ylabel = QCheckBox(tr('y-axis'))
        self.cb_ylabel.setChecked(True)
        h_labels.addWidget(QLabel(tr('Include axis labels')))
        h_labels.addWidget(self.cb_xlabel)
        h_labels.addWidget(self.cb_ylabel)
        h_labels.addStretch(1)
        settings.addLayout(h_labels, 3, 0, 1, 2)

        # Display
        h_disp = QHBoxLayout()
        self.cb_title = QCheckBox(tr('plot title'))
        self.cb_title.setChecked(True)
        self.cb_legend = QCheckBox(tr('legend'))
        self.cb_legend.setChecked(True)
        h_disp.addWidget(QLabel(tr('Display')))
        h_disp.addWidget(self.cb_title)
        h_disp.addWidget(self.cb_legend)
        h_disp.addStretch(1)
        settings.addLayout(h_disp, 3, 2, 1, 2)

        self.cb_transparent = QCheckBox(tr('Transparent background (for metafiles only)'))
        settings.addWidget(self.cb_transparent, 4, 0, 1, 4)

        lay.addLayout(settings)

        # Preview
        lay.addWidget(QLabel(tr('Image preview')))
        self.preview = QLabel()
        self.preview.setMinimumHeight(260)
        self.preview.setStyleSheet('background-color:#eef1f5; border:1px solid #d5dbe2;')
        self.preview.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.preview, 1)
        self.lbl_scale = QLabel()
        self.lbl_scale.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl_scale)

        for w in (self.cb_actual_dim, self.cb_xlabel, self.cb_ylabel,
                  self.cb_title, self.cb_legend, self.cb_transparent):
            w.stateChanged.connect(self._update_preview)

        # Bottom buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        help_btn = QPushButton(tr('Help'))
        cancel = QPushButton(tr('Cancel'))
        self.cb_export_type = QComboBox()
        self.cb_export_type.addItems(['Copy bitmap to clipboard', 'Save PNG'])
        self.btn_action = QPushButton(tr('Copy'))
        self.btn_action.setObjectName('primaryBtn')
        help_btn.clicked.connect(self._help)
        cancel.clicked.connect(self.reject)
        self.cb_export_type.currentIndexChanged.connect(self._on_type_changed)
        self.btn_action.clicked.connect(self._export)
        btns.addWidget(help_btn)
        btns.addWidget(QLabel(tr('Export type')))
        btns.addWidget(self.cb_export_type)
        btns.addWidget(self.btn_action)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        for w in (self.sp_w, self.sp_h):
            w.valueChanged.connect(self._update_preview)
        for w in (self.cb_font, self.cb_lw, self.cb_export_type):
            w.currentIndexChanged.connect(self._update_preview)

        self._update_preview()

    def _on_type_changed(self, idx: int):
        self.btn_action.setText('Copy' if idx == 0 else 'Save')

    def _update_preview(self):
        if self.cb_actual_dim.isChecked():
            self.sp_w.setValue(self._canvas.width())
            self.sp_h.setValue(self._canvas.height())
        self._canvas.set_export_flags(
            show_title=self.cb_title.isChecked(),
            show_xlabel=self.cb_xlabel.isChecked(),
            show_ylabel=self.cb_ylabel.isChecked(),
            show_legend=self.cb_legend.isChecked(),
        )
        pix = self._canvas.grab()
        self._canvas.reset_export_flags()
        if pix.isNull():
            return
        scaled = pix.scaled(self.preview.width(), self.preview.height(),
                            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(scaled)
        scale = scaled.width() / pix.width() * 100 if pix.width() else 100
        self.lbl_scale.setText(f'Image shown at {scale:.0f}% scale')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()

    def _export(self):
        w, h = self.sp_w.value(), self.sp_h.value()
        bg = QColor('#eef1f5')
        if self.cb_transparent.isChecked():
            bg = Qt.transparent
        self._canvas.set_export_flags(
            show_title=self.cb_title.isChecked(),
            show_xlabel=self.cb_xlabel.isChecked(),
            show_ylabel=self.cb_ylabel.isChecked(),
            show_legend=self.cb_legend.isChecked(),
        )
        from PySide6.QtCore import QPoint
        pix = QPixmap(w, h)
        pix.fill(bg)
        p = QPainter(pix)
        self._canvas.render(p, QPoint(0, 0))
        p.end()
        self._canvas.reset_export_flags()
        typ = self.cb_export_type.currentIndex()
        if typ == 0:
            QApplication.clipboard().setPixmap(pix)
            self.accept()
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, 'Save Image', 'plot.png', 'PNG (*.png);;All files (*.*)')
            if path:
                pix.save(path)
                self.accept()

    def _help(self):
        QMessageBox.information(self, 'Export Image',
                                'Set image dimensions and options, then copy to clipboard or save as PNG.')
