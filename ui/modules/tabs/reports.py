"""分析 Tab 实现（拆分自 analysis_tabs，S2）。"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractSpinBox,QCheckBox, QComboBox, QDoubleSpinBox,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton,
                               QScrollArea, QScrollBar, QSizePolicy, QSpinBox,
                               QSplitter, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout,
                               QWidget)

from core.dataset import (KIND_DIR, KIND_PRES, KIND_RH, KIND_SPEED,
                                  KIND_SPEED_SD, KIND_TEMP, Dataset)
from core.project import Project
from ui.modules.diurnal_widget import DiurnalWidget
from ui.modules.histogram_widget import HistogramWidget
from ui.modules.plot import PlotCanvas, _EPOCH_ORDINAL
from ui.modules.scatter_widget import ScatterWidget
from ui.modules.tables_widget import TablesWidget
from ui.modules.wind_rose_widget import WindRoseWidget
from core.i18n import tr

from ._common import (AnalysisTab)

class ReportsTab(AnalysisTab):
    """Reports：风资源分析报告（对齐原版：Report combo + Create Report + Sections + Filter by）。"""

    SECTIONS = [
        ('summary', 'Data Set Summary'),
        ('env', 'Environmental Summary'),
        ('weibull', 'Wind Speed Distribution'),
        ('monthly', 'Monthly Statistics'),
        ('annual', 'Annual Statistics'),
        ('directional', 'Directional Statistics'),
        ('recovery', 'Data Recovery'),
    ]

    def __init__(self):
        super().__init__()
        self._layout.setContentsMargins(10, 10, 10, 10)

        from PySide6.QtWidgets import (QGroupBox, QTextBrowser, QDateTimeEdit,
                                       QDoubleSpinBox)
        from PySide6.QtCore import QDateTime

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)

        # ---- Report ----
        h_rpt = QHBoxLayout()
        h_rpt.setSpacing(6)
        h_rpt.addWidget(QLabel(tr('Report')))
        self.cmb_report = QComboBox()
        self.cmb_report.addItems(['Standard Report'])
        h_rpt.addWidget(self.cmb_report, 1)
        lv.addLayout(h_rpt)

        self.btn_create = QPushButton(tr('Create Report'))
        lv.addWidget(self.btn_create)

        # ---- Sections ----
        lv.addWidget(QLabel(tr('Sections')))
        self._section_boxes = []
        for key, label in self.SECTIONS:
            cb = QCheckBox(label)
            cb.setChecked(key in ('summary', 'weibull', 'monthly', 'annual'))
            cb.setProperty('key', key)
            cb.stateChanged.connect(self._on_changed)
            self._section_boxes.append(cb)
            lv.addWidget(cb)

        # ---- Filter by ----
        from core.dataset import KIND_DIR, KIND_SPEED
        flt = QGroupBox(tr('Filter by'))
        flt_lay = QVBoxLayout(flt)
        flt_lay.setSpacing(4)
        flt_lay.setContentsMargins(6, 6, 6, 6)

        h_flag = QHBoxLayout()
        self.chk_flag = QCheckBox(tr('Flag'))
        self.chk_include = QLabel(tr('Include'))
        self.chk_unflagged = QCheckBox(tr('<Unflagged data>'))
        self.chk_unflagged.setChecked(True)
        h_flag.addWidget(self.chk_flag)
        h_flag.addWidget(self.chk_include)
        h_flag.addWidget(self.chk_unflagged, 1)
        flt_lay.addLayout(h_flag)

        h_date = QHBoxLayout()
        self.chk_date = QCheckBox(tr('Date'))
        self.cmb_year = QComboBox(); self.cmb_year.addItem('<All>')
        self.cmb_month = QComboBox(); self.cmb_month.addItem('<All>')
        h_date.addWidget(self.chk_date)
        h_date.addWidget(QLabel(tr('Year')))
        h_date.addWidget(self.cmb_year)
        h_date.addWidget(QLabel(tr('Month')))
        h_date.addWidget(self.cmb_month, 1)
        flt_lay.addLayout(h_date)

        h_range = QHBoxLayout()
        self.chk_range = QCheckBox(tr('Date range'))
        self.dt_from = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_from.setCalendarPopup(True)
        self.dt_from.setDisplayFormat('yyyy/M/d')
        self.dt_to = QDateTimeEdit(QDateTime.currentDateTime())
        self.dt_to.setCalendarPopup(True)
        self.dt_to.setDisplayFormat('yyyy/M/d')
        self.dt_from.setEnabled(False)
        self.dt_to.setEnabled(False)
        h_range.addWidget(self.chk_range)
        h_range.addWidget(self.dt_from)
        h_range.addWidget(QLabel('to'))
        h_range.addWidget(self.dt_to, 1)
        flt_lay.addLayout(h_range)

        h_sec = QHBoxLayout()
        self.chk_sector = QCheckBox(tr('Direction sector'))
        self.cmb_sector = QComboBox(); self.cmb_sector.addItem(tr('All'))
        self.lbl_fsectors = QLabel(tr('Sectors'))
        self.sp_fsectors = QSpinBox(); self.sp_fsectors.setRange(4, 36)
        self.sp_fsectors.setValue(16)
        h_sec.addWidget(self.chk_sector)
        h_sec.addWidget(self.cmb_sector)
        h_sec.addWidget(self.lbl_fsectors)
        h_sec.addWidget(self.sp_fsectors)
        h_sec.addStretch(1)
        flt_lay.addLayout(h_sec)

        self.lbl_fsensor = QLabel(tr('Direction sensor'))
        self.cmb_fsensor = QComboBox()
        self.lbl_fsensor.setEnabled(False)
        self.cmb_fsensor.setEnabled(False)
        flt_lay.addWidget(self.lbl_fsensor)
        flt_lay.addWidget(self.cmb_fsensor)

        h_dcol = QHBoxLayout()
        self.chk_dcol = QCheckBox(tr('Data column'))
        self.cmb_fdata = QComboBox()
        h_dcol.addWidget(self.chk_dcol)
        h_dcol.addWidget(self.cmb_fdata, 1)
        flt_lay.addLayout(h_dcol)

        h_lim = QHBoxLayout()
        h_lim.setContentsMargins(8, 0, 0, 0)
        self.chk_min = QCheckBox(tr('Min'))
        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(-1e6, 1e6); self.spin_min.setValue(0.0)
        self.spin_min.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.chk_max = QCheckBox(tr('Max'))
        self.spin_max = QDoubleSpinBox()
        self.spin_max.setRange(-1e6, 1e6); self.spin_max.setValue(50.0)
        self.spin_max.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        h_lim.addWidget(self.chk_min)
        h_lim.addWidget(self.spin_min)
        h_lim.addWidget(self.chk_max)
        h_lim.addWidget(self.spin_max, 1)
        flt_lay.addLayout(h_lim)
        lv.addWidget(flt)

        # ---- Export ----
        h_exp = QHBoxLayout()
        btn_pdf = QPushButton(tr('Export PDF...'))
        btn_docx = QPushButton(tr('Export DOCX...'))
        h_exp.addWidget(btn_pdf)
        h_exp.addWidget(btn_docx)
        h_exp.addStretch(1)
        lv.addLayout(h_exp)
        self._layout.addWidget(left, 0)

        # ---- 右侧预览 ----
        self.preview = QTextBrowser()
        self._layout.addWidget(self.preview, 1)

        # ---- 信号 ----
        for cb in self._section_boxes:
            cb.stateChanged.connect(self._on_changed)
        self.btn_create.clicked.connect(self.refresh)
        btn_pdf.clicked.connect(self._export_pdf)
        btn_docx.clicked.connect(self._export_docx)

        self._populate_filters()
        self._sync_filter_enabled()

    def _populate_filters(self):
        """填充筛选下拉框（年份/月份/传感器/数据列）。"""
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            return
        try:
            years = sorted(ds.df.index.year.unique())
        except (AttributeError, TypeError):
            return
        for y in years:
            self.cmb_year.addItem(str(y), str(y))
        for m in range(1, 13):
            self.cmb_month.addItem(str(m), str(m))
        for n, ch in ds.channels.items():
            if ch.kind == 'dir' and getattr(ch, 'role', 'Avg') == 'Avg' \
                    and n in ds.df.columns:
                self.cmb_fsensor.addItem(n, n)
        for n in ds.channels:
            if n in ds.df.columns:
                self.cmb_fdata.addItem(n, n)
        idx0 = pd.Timestamp(ds.df.index[0])
        idx1 = pd.Timestamp(ds.df.index[-1])
        self.dt_from.setDateTime(idx0)
        self.dt_to.setDateTime(idx1)

    def _sync_filter_enabled(self):
        for w in (self.chk_include, self.chk_unflagged):
            w.setEnabled(self.chk_flag.isChecked())
        for w in (self.cmb_year, self.cmb_month):
            w.setEnabled(self.chk_date.isChecked())
        for w in (self.dt_from, self.dt_to):
            w.setEnabled(self.chk_range.isChecked())
        for w in (self.cmb_sector, self.lbl_fsectors, self.sp_fsectors,
                  self.cmb_fsensor):
            w.setEnabled(self.chk_sector.isChecked())
        for w in (self.chk_min, self.spin_min, self.chk_max, self.spin_max):
            w.setEnabled(self.chk_dcol.isChecked())

    def _filter_mask(self):
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            return None
        mask = pd.Series(True, index=ds.df.index)
        if self.chk_flag.isChecked():
            flags = getattr(ds, 'flags', None)
            if flags is not None and len(flags) == len(ds.df):
                if self.chk_unflagged.isChecked():
                    mask &= ~flags.astype(bool)
                else:
                    mask &= flags.astype(bool)
        if self.chk_date.isChecked():
            year = self.cmb_year.currentData()
            month = self.cmb_month.currentData()
            if year:
                mask &= ds.df.index.year == int(year)
            if month:
                mask &= ds.df.index.month == int(month)
        if self.chk_range.isChecked():
            mask &= ds.df.index >= pd.Timestamp(self.dt_from.dateTime().toPyDateTime())
            mask &= ds.df.index <= pd.Timestamp(self.dt_to.dateTime().toPyDateTime())
        if self.chk_dcol.isChecked():
            dcol = self.cmb_fdata.currentData()
            if dcol and dcol in ds.df.columns:
                v = pd.to_numeric(ds.df[dcol], errors='coerce')
                if self.chk_min.isChecked():
                    mask &= v >= self.spin_min.value()
                if self.chk_max.isChecked():
                    mask &= v <= self.spin_max.value()
        return mask if not mask.all() else None

    def _on_changed(self):
        self.refresh()

    def _model(self):
        from ui.modules.report_builder import ReportModel
        sections = [cb.property('key') for cb in self._section_boxes
                    if cb.isChecked()]
        return ReportModel(self.active_dataset(),
                           sections=sections,
                           title='Wind Resource Analysis Report')

    def _rose_png(self) -> bytes | None:
        from PySide6.QtCore import QBuffer, QIODevice
        from core.wind_rose import compute_rose
        ds = self.active_dataset()
        dir_col = None
        for n, ch in ds.channels.items():
            if ch.kind == 'dir' and getattr(ch, 'role', 'Avg') == 'Avg':
                dir_col = n
                break
        if not dir_col:
            return None
        r = compute_rose(ds.df, dir_col, sectors=16, display='frequency',
                         versus='direction')
        if r is None:
            return None
        canvas = PlotCanvas('Wind Rose')
        canvas.plot_polar(sectors=r.sectors, freq=r.values,
                          title='Wind Rose', labels=r.labels,
                          calm=r.calm, display_type='frequency',
                          unit=r.unit)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        canvas.grab().save(buf, 'PNG')
        return bytes(buf.data())

    def _monthly_png(self) -> bytes | None:
        from PySide6.QtCore import QBuffer, QIODevice
        ds = self.active_dataset()
        speeds = [(n, ch.height) for n, ch in ds.channels.items()
                  if ch.kind == 'speed' and getattr(ch, 'role', 'Avg') == 'Avg'
                  and n in ds.df.columns]
        if not speeds:
            return None
        name = speeds[-1][0]
        s = pd.to_numeric(ds.df[name], errors='coerce').dropna()
        if s.empty:
            return None
        monthly = s.groupby(s.index.month).mean()
        canvas = PlotCanvas('Monthly Mean Wind Speed')
        canvas.plot_bar(monthly.index.to_numpy(), monthly.to_numpy(),
                        xlabel='Month', ylabel='Mean wind speed (m/s)',
                        ymin=0)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        canvas.grab().save(buf, 'PNG')
        return bytes(buf.data())

    def refresh(self):
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            self.preview.setHtml('<p style="color:#999">No data loaded</p>')
            return
        model = self._model()
        blocks = model.blocks()
        rose = self._rose_png()
        if rose:
            blocks.append(('h2', 'Wind Rose'))
            blocks.append(('image', rose, 560, 400))
        monthly = self._monthly_png()
        if monthly:
            blocks.append(('h2', 'Monthly Mean Wind Speed'))
            blocks.append(('image', monthly, 560, 320))
        from ui.modules.report_builder import blocks_to_html
        self.preview.setHtml(blocks_to_html(blocks))

    def _export_pdf(self):
        from PySide6.QtCore import QMarginsF, QSizeF
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
        from ui.modules.report_builder import blocks_to_html
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            QMessageBox.information(self, 'Reports', 'No data loaded')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export PDF',
                                              'report.pdf', 'PDF (*.pdf)')
        if not path:
            return
        model = self._model()
        blocks = model.blocks()
        for png, h in ((self._rose_png(), 400), (self._monthly_png(), 320)):
            if png:
                blocks.append(('image', png, 560, h))
        with tempfile.TemporaryDirectory() as tmp:
            html = blocks_to_html(blocks, image_dir=tmp)
            writer = QPdfWriter(path)
            writer.setPageLayout(QPageLayout(
                QPageSize(QPageSize.A4), QPageLayout.Portrait,
                QMarginsF(15, 15, 15, 15)))
            writer.setResolution(96)
            doc = QTextDocument()
            doc.setHtml(html)
            doc.setPageSize(QSizeF(writer.width(), writer.height()))
            doc.print_(writer)
        QMessageBox.information(self, 'Reports', f'PDF exported: {path}')

    def _export_docx(self):
        from ui.modules.docx_writer import DocxBuilder
        ds = self.active_dataset()
        if ds is None or ds.df.empty:
            QMessageBox.information(self, 'Reports', 'No data loaded')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export DOCX',
                                              'report.docx', 'Word (*.docx)')
        if not path:
            return
        model = self._model()
        docx = DocxBuilder()
        rose = self._rose_png()
        monthly = self._monthly_png()
        for kind, payload in model.blocks():
            if kind == 'h1':
                docx.heading(payload, 1)
            elif kind == 'h2':
                docx.heading(payload, 2)
            elif kind == 'p':
                docx.paragraph(payload)
            elif kind == 'table':
                docx.table(payload)
        if rose:
            docx.image_png(rose, 560, 400)
            docx.paragraph('Wind Rose')
        if monthly:
            docx.image_png(monthly, 560, 320)
            docx.paragraph('Monthly Mean Wind Speed')
        docx.save(path)
        QMessageBox.information(self, 'Reports', f'DOCX exported: {path}')
