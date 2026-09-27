"""绘图引擎拆分模块（B4，装饰器感知重建）。"""
from __future__ import annotations
"""PlotCanvas：QPainter 自绘图表控件（零新增依赖）。

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





class ExportingMixin:
    def _copy_bitmap(self):
        """将当前图表渲染为位图并复制到剪贴板。"""
        from PySide6.QtCore import QPoint
        pix = QPixmap(self.size())
        pix.fill(QColor('#eef1f5'))
        p = QPainter(pix)
        self.render(p, QPoint(0, 0))
        p.end()
        QApplication.clipboard().setPixmap(pix)

    def _export_image(self):
        """导出图片对话框。"""
        dlg = ExportImageDialog(self)
        dlg.exec()

    def _export_data(self):
        """导出图表底层数据，默认 .txt，文件头为英文规范名（对齐原版）。"""
        default_name = f"{self.export_header.replace(' ', '_')}.txt" if self.export_header else 'plot_data.txt'
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Data', default_name,
            'Text (*.txt);;CSV (*.csv);;All files (*.*)')
        if not path:
            return
        df = self._to_dataframe()
        if df is None or df.empty:
            QMessageBox.warning(self, tr('无数据'), tr('当前图表没有可导出的数据。'))
            return
        try:
            header = f'{self.export_header}\n' if self.export_header else ''
            if path.lower().endswith('.csv'):
                with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                    f.write(header)
                    df.to_csv(f, index=False)
            else:
                with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                    f.write(header)
                    df.to_csv(f, sep='\t', index=False)
        except Exception as e:
            QMessageBox.warning(self, tr('导出失败'), f'{e}')

    def _show_properties(self):
        """打开图表属性对话框。

        若外部（如 WindRoseWidget）设置了 properties_handler，优先调用，
        否则打开通用 PlotPropertiesDialog。
        """
        if self.properties_handler is not None:
            self.properties_handler()
            return
        dlg = PlotPropertiesDialog(self)
        dlg.exec()

    def _to_dataframe(self) -> pd.DataFrame | None:
        """把当前图表数据转换为 DataFrame，供导出。"""
        kind = self._kind
        data = self._data
        if kind == 'empty':
            return None
        if kind in ('line', 'bar', 'scatter'):
            return pd.DataFrame({
                'x': data.get('x', []),
                'y': data.get('y', []),
            })
        if kind == 'lines':
            rows = []
            for s in data.get('series', []):
                label, x, y = s[0], s[1], s[2]
                n = min(len(x), len(y))
                for i in range(n):
                    rows.append({'series': label, 'x': x[i], 'y': y[i]})
            return pd.DataFrame(rows) if rows else None
        if kind == 'polar':
            freq = np.asarray(data.get('freq', []))
            sector = np.arange(freq.shape[0] if freq.ndim else 0)
            if freq.ndim == 1:
                return pd.DataFrame({'sector': sector, 'frequency': freq})
            # 多通道玫瑰：逐通道输出列
            cols = {'sector': sector}
            for ci in range(freq.shape[1]):
                cols[f'frequency_ch{ci}'] = freq[:, ci]
            return pd.DataFrame(cols)
        if kind == 'box':
            rows = []
            for label, st in data.get('groups', []):
                st = st or {}
                rows.append({
                    'label': label, 'min': st.get('min'), 'q1': st.get('q1'),
                    'median': st.get('med'), 'q3': st.get('q3'),
                    'max': st.get('max'), 'mean': st.get('mean'), 'n': st.get('n'),
                })
            return pd.DataFrame(rows) if rows else None
        if kind == 'heatmap':
            return pd.DataFrame(data.get('matrix', []))
        if kind == 'table':
            return pd.DataFrame(data.get('rows', []),
                                columns=data.get('headers', []))
        return None
