"""语言设置对话框。

英文为底座，提供三列：英文底座 / 英文修正 / 中文翻译。
展示英文菜单时，优先使用英文修正列（若已填写）；软件完成后，
英文修正列将替换为英文底座。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from core import settings
from core.i18n import DEFAULT_TRANSLATIONS, ensure_defaults, switch, tr


class LanguageSettingsDialog(QDialog):
    """切换界面语言，并维护英文底座 → 英文修正 / 中文翻译 的对照表。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Language Settings / 语言设置'))
        self.resize(900, 650)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr('界面语言 / Language：')))
        self.lang_combo = QComboBox()
        self.lang_combo.addItem(tr('中文'), 'zh')
        self.lang_combo.addItem(tr('English'), 'en')
        cur = settings.get('language', 'zh')
        self.lang_combo.setCurrentIndex(0 if cur == 'zh' else 1)
        top.addWidget(self.lang_combo)
        top.addSpacing(20)
        self.use_correction = QCheckBox(tr('展示英文修正列 / Use English corrections'))
        self.use_correction.setChecked(
            settings.get('use_english_correction', False))
        top.addWidget(self.use_correction)
        top.addStretch(1)
        self.btn_restore = QPushButton(tr('恢复默认中文 / Restore Default Chinese'))
        self.btn_restore.clicked.connect(self._restore_defaults)
        top.addWidget(self.btn_restore)
        lay.addLayout(top)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr('英文底座 / English Base'),
             tr('英文修正 / English Correction'),
             tr('中文翻译 / Chinese')])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 260)
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr('取消 / Cancel'))
        ok = QPushButton(tr('确定 / OK'))
        ok.setObjectName('primaryBtn')
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._on_ok)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        self._load_table()

    def _load_table(self):
        ensure_defaults()
        trans = settings.get('translations', {})
        corrections = settings.get('english_corrections', {})
        items = sorted(DEFAULT_TRANSLATIONS.items(), key=lambda x: x[0])
        self.table.setRowCount(len(items))
        for r, (en, zh_default) in enumerate(items):
            en_item = QTableWidgetItem(en)
            en_item.setFlags(en_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 0, en_item)
            corr_item = QTableWidgetItem(corrections.get(en, ''))
            self.table.setItem(r, 1, corr_item)
            zh_item = QTableWidgetItem(trans.get(en, zh_default))
            self.table.setItem(r, 2, zh_item)

    def _restore_defaults(self):
        for r in range(self.table.rowCount()):
            en = self.table.item(r, 0).text()
            self.table.item(r, 1).setText('')
            self.table.item(r, 2).setText(DEFAULT_TRANSLATIONS.get(en, ''))

    def _on_ok(self):
        lang = self.lang_combo.currentData()
        switch(lang)
        trans = {}
        corrections = {}
        for r in range(self.table.rowCount()):
            en = self.table.item(r, 0).text()
            corr = self.table.item(r, 1).text().strip()
            zh = self.table.item(r, 2).text().strip()
            corrections[en] = corr
            trans[en] = zh if zh else DEFAULT_TRANSLATIONS.get(en, en)
        settings.set('translations', trans)
        settings.set('english_corrections', corrections)
        settings.set('use_english_correction',
                     self.use_correction.isChecked())
        parent = self.parent()
        if parent is not None and hasattr(parent, '_retranslate_ui'):
            parent._retranslate_ui()
        self.accept()
