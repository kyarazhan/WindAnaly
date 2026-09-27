"""风玫瑰图属性对话框（Windographer 风格）。

Tabs: Axes / Channels / Fonts
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDoubleSpinBox, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSlider, QSpinBox, QTabWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core import settings
from core.project import Project
from core.i18n import tr


_LINE_STYLES = [
    ('solid', '实线'),
    ('dash', '虚线'),
    ('dot', '点线'),
    ('dash_dot', '点划线'),
]

_MARKERS = [
    ('none', '无'),
    ('circle', '圆'),
    ('square', '方'),
    ('diamond', '菱形'),
    ('triangle', '三角'),
    ('cross', '+'),
    ('x', '×'),
]

_ROSE_STYLES = [
    ('filled_line', '填充+线'),
    ('filled', '仅填充'),
    ('line', '仅线'),
    ('bar', '柱状'),
]

_DEFAULT_PALETTE = [
    '#2c7be5', '#27ae60', '#f39c12', '#9b59b6',
    '#17a2b8', '#e74c3c', '#6c757d',
]


class RosePropertiesDialog(QDialog):
    def __init__(self, project: Project, current_cfg: dict,
                 labels: list[str], parent=None):
        super().__init__(parent)
        self.project = project
        self.current_cfg = current_cfg
        self.labels = labels or []
        self.setWindowTitle(tr('风玫瑰图属性'))
        self.resize(540, 420)

        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_axes(), tr('Axes'))
        self.tabs.addTab(self._build_channels(), tr('Channels'))
        self.tabs.addTab(self._build_fonts(), tr('Fonts'))

        # 底部按钮
        h = QHBoxLayout()
        h.addStretch(1)
        self.btn_defaults = QPushButton(tr('Restore Defaults'))
        self.btn_save_default = QPushButton(tr('Save as Default'))
        self.btn_ok = QPushButton('OK')
        self.btn_cancel = QPushButton(tr('Cancel'))
        self.btn_defaults.clicked.connect(self._on_restore_defaults)
        self.btn_save_default.clicked.connect(self._on_save_default)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        h.addWidget(self.btn_defaults)
        h.addWidget(self.btn_save_default)
        h.addWidget(self.btn_ok)
        h.addWidget(self.btn_cancel)
        v.addLayout(h)

        self._load()

    def _build_axes(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(8)

        self.edit_title = QLineEdit()
        self.edit_radial_label = QLineEdit()
        self.spin_sectors = QSpinBox()
        self.spin_sectors.setRange(4, 72)
        self.spin_sectors.setSingleStep(4)

        self.chk_fix_min_max = QCheckBox(tr('Fix min/max'))
        h = QHBoxLayout()
        self.spin_rmin = QDoubleSpinBox()
        self.spin_rmin.setRange(0, 9999)
        self.spin_rmax = QDoubleSpinBox()
        self.spin_rmax.setRange(0, 9999)
        h.addWidget(QLabel(tr('Min')))
        h.addWidget(self.spin_rmin)
        h.addWidget(QLabel(tr('Max')))
        h.addWidget(self.spin_rmax)

        self.spin_inner_circle = QSpinBox()
        self.spin_inner_circle.setRange(0, 100)
        self.spin_inner_circle.setSuffix('%')

        self.spin_fill_factor = QSpinBox()
        self.spin_fill_factor.setRange(10, 100)
        self.spin_fill_factor.setSuffix('%')

        self.chk_label_angular = QCheckBox(tr('Label angular axis'))
        self.chk_show_legend = QCheckBox(tr('Show legend'))

        form.addRow('Title', self.edit_title)
        form.addRow('Radial label', self.edit_radial_label)
        form.addRow('Default sectors', self.spin_sectors)
        form.addRow(self.chk_fix_min_max)
        form.addRow(h)
        form.addRow('Inner circle radius', self.spin_inner_circle)
        form.addRow('Fill factor', self.spin_fill_factor)
        form.addRow(self.chk_label_angular)
        form.addRow(self.chk_show_legend)
        form.addRow(QLabel(''))
        return w

    def _build_channels(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)

        self.list_channels = QListWidget()
        self.list_channels.setMaximumWidth(180)
        self.list_channels.currentRowChanged.connect(self._on_channel_changed)
        h.addWidget(self.list_channels)

        right = QVBoxLayout()
        form = QFormLayout()
        form.setSpacing(6)

        self.edit_ch_label = QLineEdit()
        self.btn_ch_color = QPushButton()
        self.btn_ch_color.setFixedSize(40, 20)
        self.btn_ch_color.clicked.connect(self._on_pick_color)

        self.chk_ch_border = QCheckBox(tr('Border'))

        self.cmb_rose_style = QComboBox()
        for key, label in _ROSE_STYLES:
            self.cmb_rose_style.addItem(label, key)

        self.cmb_line_style = QComboBox()
        for key, label in _LINE_STYLES:
            self.cmb_line_style.addItem(label, key)

        self.spin_line_width = QSpinBox()
        self.spin_line_width.setRange(1, 10)

        self.cmb_marker = QComboBox()
        for key, label in _MARKERS:
            self.cmb_marker.addItem(label, key)

        self.spin_marker_size = QSpinBox()
        self.spin_marker_size.setRange(1, 20)

        self.chk_ch_visible = QCheckBox(tr('Visible'))

        form.addRow('Label', self.edit_ch_label)
        form.addRow('Color', self.btn_ch_color)
        form.addRow(self.chk_ch_border)
        form.addRow('Rose style', self.cmb_rose_style)
        form.addRow('Line width', self.spin_line_width)
        form.addRow('Line pattern', self.cmb_line_style)
        form.addRow('Marker type', self.cmb_marker)
        form.addRow('Marker size', self.spin_marker_size)
        form.addRow(self.chk_ch_visible)

        right.addLayout(form)

        # Display settings（Windographer Channels 页底部，作用于当前选中通道）
        ds_box = QGroupBox(tr('Display settings'))
        ds_box.setStyleSheet(
            'QGroupBox{font-weight:bold;margin-top:8px;padding-top:6px;}'
            'QGroupBox::title{subcontrol-origin:margin;left:6px;padding:0 3px;}')
        ds_lay = QVBoxLayout(ds_box)
        ds_lay.setSpacing(4)
        self.chk_ds_show_in_legend = QCheckBox(tr('Show in legend'))
        self.chk_ds_show_values = QCheckBox(tr('Show values'))
        self.chk_ds_error_bars = QCheckBox(tr('Show error bars'))
        ds_lay.addWidget(self.chk_ds_show_in_legend)
        ds_lay.addWidget(self.chk_ds_show_values)
        ds_lay.addWidget(self.chk_ds_error_bars)
        right.addWidget(ds_box)

        right.addStretch(1)
        h.addLayout(right, 1)
        return w

    def _build_fonts(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        form = QFormLayout()
        self.spin_title_font = QSpinBox()
        self.spin_title_font.setRange(6, 24)
        self.spin_label_font = QSpinBox()
        self.spin_label_font.setRange(6, 20)
        self.spin_legend_font = QSpinBox()
        self.spin_legend_font.setRange(6, 20)
        form.addRow('Title font size', self.spin_title_font)
        form.addRow('Axis label font size', self.spin_label_font)
        form.addRow('Legend font size', self.spin_legend_font)
        v.addLayout(form)
        v.addStretch(1)
        return w

    def _load(self):
        cfg = self.project.plot_setting('wind_rose') if self.project else {}
        defaults = settings.get_wind_rose_defaults()
        cfg = {**defaults, **cfg}

        self.edit_title.setText(cfg.get('title', '风向玫瑰图'))
        self.edit_radial_label.setText(cfg.get('radial_label', ''))
        self.spin_sectors.setValue(cfg.get('sectors', 16))
        self.chk_fix_min_max.setChecked(cfg.get('fix_min_max', False))
        self.spin_rmin.setValue(cfg.get('radial_min', 0.0))
        self.spin_rmax.setValue(cfg.get('radial_max', 100.0))
        self.spin_inner_circle.setValue(int(cfg.get('inner_circle_pct', 0.0)))
        self.spin_fill_factor.setValue(int(cfg.get('fill_factor', 0.85) * 100))
        self.chk_label_angular.setChecked(cfg.get('label_angular', True))
        self.chk_show_legend.setChecked(cfg.get('show_legend', True))

        self.spin_title_font.setValue(cfg.get('title_font', 11))
        self.spin_label_font.setValue(cfg.get('label_font', 9))
        self.spin_legend_font.setValue(cfg.get('legend_font', 8))

        # channels
        raw_styles = cfg.get('channel_styles', {})
        if isinstance(raw_styles, dict):
            self._channel_styles = [dict(v) for v in raw_styles.values()]
        else:
            self._channel_styles = [dict(s) for s in raw_styles]
        while len(self._channel_styles) < len(self.labels):
            self._channel_styles.append({
                'color': _DEFAULT_PALETTE[len(self._channel_styles) % len(_DEFAULT_PALETTE)],
                'rose_style': 'filled_line',
                'line_width': 2,
                'line_style': 'solid',
                'marker': 'none',
                'marker_size': 5,
                'fill_alpha': 45,
                'border': False,
                'visible': True,
                'show_in_legend': True,
                'show_values': False,
                'show_error_bars': False,
            })
        self.list_channels.clear()
        for lab in self.labels:
            self.list_channels.addItem(lab)
        if self.labels:
            self.list_channels.setCurrentRow(0)
            self._on_channel_changed(0)

    def _on_channel_changed(self, row: int):
        if row < 0 or row >= len(self._channel_styles):
            return
        st = self._channel_styles[row]
        self.edit_ch_label.setText(st.get('label', self.labels[row]))
        self._set_color_btn(st.get('color', _DEFAULT_PALETTE[row % len(_DEFAULT_PALETTE)]))
        self.chk_ch_border.setChecked(st.get('border', False))
        idx = self.cmb_rose_style.findData(st.get('rose_style', 'filled_line'))
        self.cmb_rose_style.setCurrentIndex(max(0, idx))
        self.spin_line_width.setValue(st.get('line_width', 2))
        idx = self.cmb_line_style.findData(st.get('line_style', 'solid'))
        self.cmb_line_style.setCurrentIndex(max(0, idx))
        idx = self.cmb_marker.findData(st.get('marker', 'none'))
        self.cmb_marker.setCurrentIndex(max(0, idx))
        self.spin_marker_size.setValue(st.get('marker_size', 5))
        self.chk_ch_visible.setChecked(st.get('visible', True))
        # Display settings（当前选中通道）
        self.chk_ds_show_in_legend.setChecked(st.get('show_in_legend', True))
        self.chk_ds_show_values.setChecked(st.get('show_values', False))
        self.chk_ds_error_bars.setChecked(st.get('show_error_bars', False))

    def _apply_current_channel(self):
        row = self.list_channels.currentRow()
        if row < 0:
            return
        st = self._channel_styles[row]
        st['label'] = self.edit_ch_label.text()
        st['border'] = self.chk_ch_border.isChecked()
        st['rose_style'] = self.cmb_rose_style.currentData()
        st['line_width'] = self.spin_line_width.value()
        st['line_style'] = self.cmb_line_style.currentData()
        st['marker'] = self.cmb_marker.currentData()
        st['marker_size'] = self.spin_marker_size.value()
        st['visible'] = self.chk_ch_visible.isChecked()
        st['show_in_legend'] = self.chk_ds_show_in_legend.isChecked()
        st['show_values'] = self.chk_ds_show_values.isChecked()
        st['show_error_bars'] = self.chk_ds_error_bars.isChecked()

    def _on_pick_color(self):
        row = self.list_channels.currentRow()
        if row < 0:
            return
        st = self._channel_styles[row]
        c = QColor(st.get('color', _DEFAULT_PALETTE[row % len(_DEFAULT_PALETTE)]))
        new = QColorDialog.getColor(c, self, '选择颜色')
        if new.isValid():
            st['color'] = new.name()
            self._set_color_btn(st['color'])

    def _set_color_btn(self, color):
        self.btn_ch_color.setStyleSheet(
            f'background-color: {color}; border: 1px solid #888;')

    def _on_restore_defaults(self):
        defaults = settings.get_wind_rose_defaults()
        self.edit_title.setText(defaults.get('title', '风向玫瑰图'))
        self.edit_radial_label.setText(defaults.get('radial_label', ''))
        self.spin_sectors.setValue(defaults.get('sectors', 16))
        self.chk_fix_min_max.setChecked(defaults.get('fix_min_max', False))
        self.spin_rmin.setValue(defaults.get('radial_min', 0.0))
        self.spin_rmax.setValue(defaults.get('radial_max', 100.0))
        self.spin_inner_circle.setValue(int(defaults.get('inner_circle_pct', 0.0)))
        self.spin_fill_factor.setValue(int(defaults.get('fill_factor', 0.85) * 100))
        self.chk_label_angular.setChecked(defaults.get('label_angular', True))
        self.chk_show_legend.setChecked(defaults.get('show_legend', True))
        raw_styles = defaults.get('channel_styles', {})
        if isinstance(raw_styles, dict):
            self._channel_styles = [dict(v) for v in raw_styles.values()]
        else:
            self._channel_styles = [dict(s) for s in raw_styles]
        self.chk_ds_show_in_legend.setChecked(True)
        self.chk_ds_show_values.setChecked(False)
        self.chk_ds_error_bars.setChecked(False)

    def _on_save_default(self):
        self._apply_current_channel()
        cfg = self._collect_cfg()
        settings.set_wind_rose_defaults(cfg)

    def _collect_cfg(self) -> dict:
        return {
            'title': self.edit_title.text(),
            'radial_label': self.edit_radial_label.text(),
            'sectors': self.spin_sectors.value(),
            'fix_min_max': self.chk_fix_min_max.isChecked(),
            'radial_min': self.spin_rmin.value(),
            'radial_max': self.spin_rmax.value(),
            'inner_circle_pct': self.spin_inner_circle.value(),
            'fill_factor': self.spin_fill_factor.value() / 100.0,
            'label_angular': self.chk_label_angular.isChecked(),
            'show_legend': self.chk_show_legend.isChecked(),
            'title_font': self.spin_title_font.value(),
            'label_font': self.spin_label_font.value(),
            'legend_font': self.spin_legend_font.value(),
            'channel_styles': self._channel_styles,
        }

    def accept(self):
        self._apply_current_channel()
        if self.project is not None:
            cfg = self._collect_cfg()
            self.project.set_plot_setting('wind_rose', cfg)
        super().accept()
