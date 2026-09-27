"""Export Data 格式选项卡（拆分自 export_dialog，B3）。"""
from __future__ import annotations

import math
import os
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QRadioButton, QSizePolicy, QSpinBox, QStackedWidget, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QDoubleSpinBox,
)

from core.dataset import KIND_DIR, KIND_SPEED, Dataset
from core.i18n import tr
from ui.dialogs.compare_dialogs import (
    _col_disp, _dir_cols, _height_of, _numeric_cols, _speed_cols,
)


class _XMLMetadataTab(QWidget):
    def __init__(self, ds, preview, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.preview = preview
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        g = QGroupBox(tr('XML Metadata'))
        v = QVBoxLayout(g)
        v.setContentsMargins(4, 4, 4, 4)
        lbl = QLabel(tr('This file describes the data set and its data columns, '
                     'but contains no time series data.'))
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        self.btn_update = QPushButton(tr('Update Preview'))
        self.btn_update.clicked.connect(self._update_preview)
        v.addWidget(self.btn_update)
        lay.addWidget(g)
        self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(self.generate_text())

    def generate_text(self) -> str:
        root = Element('windographerxml', {
            'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'xsi:noNamespaceSchemaLocation': 'windographerxml1.xsd',
            'version': '1.0',
        })
        md = SubElement(root, 'metadata')
        SubElement(md, 'site_name').text = self.ds.name
        SubElement(md, 'site_description').text = self.ds.description
        SubElement(md, 'latitude').text = str(self.ds.attrs.get('latitude', ''))
        SubElement(md, 'longitude').text = str(self.ds.attrs.get('longitude', ''))
        SubElement(md, 'elevation').text = str(self.ds.attrs.get('elevation', ''))
        if not self.ds.df.empty:
            SubElement(md, 'POR_start').text = self.ds.df.index[0].strftime('%Y-%m-%dT%H:%M:%S')
            SubElement(md, 'POR_end').text = self.ds.df.index[-1].strftime('%Y-%m-%dT%H:%M:%S')
        for c in self.ds.channels.values():
            dc = SubElement(md, 'data_column')
            SubElement(dc, 'label').text = c.name
            SubElement(dc, 'type').text = c.kind.upper()
            SubElement(dc, 'units').text = c.units
            SubElement(md, 'height').text = str(c.height if c.height is not None else '')
            SubElement(dc, 'color').text = c.color or '16367522'
            SubElement(dc, 'visible').text = 'yes'
            cal = SubElement(dc, 'calibration_period')
            SubElement(cal, 'start_time').text = ''
            SubElement(cal, 'serial_no').text = ''
            SubElement(cal, 'scale').text = '1'
        raw = tostring(root, encoding='unicode')
        return raw

    def do_export(self, parent):
        path, _ = QFileDialog.getSaveFileName(
            parent, '导出 XML Metadata', f'{self.ds.name}.xml',
            'XML (*.xml);;All files (*.*)')
        if not path:
            return False
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.generate_text())
        return True
