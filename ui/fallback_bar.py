"""Fallback 顶部菜单栏/工具栏实现。

当 PySide6 的 QMenuBar/QToolBar 在 Windows 某些环境下无法作为普通子 widget
渲染时，用纯 QWidget + QToolButton + QMenu 实现可稳定显示的替代方案。

设计目标：视觉上尽量贴近原生 QMenuBar/QToolBar——菜单项紧密排列、
工具栏图标+小字紧凑、整体严格左对齐、无多余按钮边框。
"""
import re

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QMenu, QSizePolicy,
                               QToolButton, QWidget)


class FallbackMenuBar(QWidget):
    """纯 QWidget 实现的菜单栏，使用 QToolButton（InstantPopup）。"""

    def __init__(self, parent=None, bg='#eef1f5', fg='#212529',
                 hover='#d9e0e8', pressed='#a8b8c8', font_size=12,
                 height=24):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(f'background:{bg};')
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._menus: dict[str, QMenu] = {}
        self._buttons: dict[str, QToolButton] = {}
        self._style = (
            "QToolButton{{"
            "  background:transparent;"
            "  color:{fg};"
            "  border:none;"
            "  border-radius:0px;"
            "  margin:0px;"
            "  padding:0px 5px;"
            "  font-size:{fs}px;"
            "  outline:none;"
            "}}"
            "QToolButton:hover{{background:{hover};}}"
            "QToolButton:pressed,QToolButton:checked{{background:{pressed};}}"
            "QToolButton::menu-indicator{{image:none;width:0px;}}"
        ).format(fg=fg, hover=hover, pressed=pressed, fs=font_size)

    @staticmethod
    def _clean_menubar_text(text: str) -> str:
        """去掉菜单按钮上的助记符，保持简洁。"""
        text = text.replace('&', '')
        text = re.sub(r'\s*\([A-Za-z]\)\s*$', '', text)
        return text.strip()

    def add_menu(self, title: str, menu: QMenu) -> QToolButton:
        """添加一个顶级菜单按钮，点击即弹出菜单。"""
        display_title = self._clean_menubar_text(title)
        btn = QToolButton(self)
        btn.setObjectName('menuBtn')
        btn.setText(display_title)
        btn.setMenu(menu)
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn.setStyleSheet(self._style)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding)
        self._layout.addWidget(btn, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self._menus[title] = menu
        self._buttons[title] = btn
        return btn

    def set_menu_title(self, old_title: str, new_title: str):
        """更新菜单按钮文案（语言切换用）。"""
        btn = self._buttons.get(old_title)
        if btn is None:
            return
        display_title = self._clean_menubar_text(new_title)
        btn.setText(display_title)
        menu = self._menus.pop(old_title, None)
        if menu is not None:
            self._menus[new_title] = menu
        self._buttons.pop(old_title, None)
        self._buttons[new_title] = btn

    def add_space(self):
        """在末尾添加弹性占位。"""
        self._layout.addStretch(1)

    def clear(self):
        """清空所有按钮（不会删除 QMenu 对象）。"""
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._menus.clear()
        self._buttons.clear()

    def menus(self) -> list[QMenu]:
        """返回已注册的全部 QMenu。"""
        return list(self._menus.values())

    def actions(self) -> list[QAction]:
        """返回所有 QMenu 的 menuAction（兼容旧检查）。"""
        acts = []
        for title, m in self._menus.items():
            a = m.menuAction()
            a.setText(title)
            acts.append(a)
        return acts


class FallbackToolBar(QWidget):
    """纯 QWidget 实现的快捷工具栏（文字按钮，宽度不足时自动换行）。

    按钮数量超出可用宽度时自动折行，并按行数调整自身高度，
    通过 heightChanged 通知宿主调整顶栏高度。"""

    heightChanged = Signal(int)

    def __init__(self, parent=None, bg='#eef1f5', fg='#212529',
                 hover='#dde3e8', pressed='#c8d4e0', font_size=11,
                 height=24):
        super().__init__(parent)
        self._row_h = height
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            f'background:{bg};border-bottom:1px solid #c4ccd4;')
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._items: list[QWidget] = []       # 按钮与分隔线，按加入顺序
        self._pairs: list[tuple[QToolButton, QAction | None]] = []
        self._style = (
            "QToolButton{{"
            "  background:transparent;"
            "  color:{fg};"
            "  border:none;"
            "  border-radius:2px;"
            "  margin:0px;"
            "  padding:0px 4px;"
            "  font-size:{fs}px;"
            "  outline:none;"
            "}}"
            "QToolButton:hover{{background:{hover};}}"
            "QToolButton:pressed{{background:{pressed};}}"
            "QToolButton::menu-indicator{{image:none;width:0px;}}"
        ).format(fg=fg, hover=hover, pressed=pressed, fs=font_size)

    @staticmethod
    def _clean_tool_text(text: str) -> str:
        """去掉助记符和省略号，让工具栏按钮更紧凑。"""
        text = text.replace('&', '')
        # 去掉末尾 ' (X)...' / '(&X)...' / '(X)' / '(&X)' 助记符与省略号
        text = re.sub(r'\s*\(&?[A-Za-z]\)[.\s]*$', '', text)
        text = text.rstrip('.').strip()
        return text

    def add_action(self, action: QAction, icon: QIcon | None = None,
                   text: str | None = None,
                   icon_only: bool = False) -> QToolButton:
        """为 QAction 创建一个按钮并加入工具栏。

        text 覆盖按钮/悬停文案（默认用 action.text() 的净化版本）；
        icon_only=True 时只显示图标（悬停显示 text 文案）。"""
        display = text or self._clean_tool_text(action.text())
        btn = QToolButton(self)
        btn.setObjectName('toolBtn')
        btn.setAutoRaise(True)
        has_icon = icon is not None and not icon.isNull()
        if has_icon and icon_only:
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            btn.setText(display)               # 无障碍/兜底文案
            btn.setToolTip(display)
        else:
            btn.setText(display)
            btn.setToolTip(action.toolTip() or display)
            btn.setToolButtonStyle(
                Qt.ToolButtonTextBesideIcon if has_icon
                else Qt.ToolButtonTextOnly)
        if has_icon:
            btn.setIcon(icon)
            btn.setIconSize(QSize(16, 16))
        btn.setStyleSheet(self._style)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding)
        if text:
            # 固定文案（refresh_text 不随 action 文案改写）
            btn.setProperty('fixedText', display)
        btn.clicked.connect(action.trigger)
        self._items.append(btn)
        self._pairs.append((btn, action))
        self._relayout()
        return btn

    def add_separator(self):
        """添加竖向分隔线。"""
        sep = QWidget(self)
        sep.setFixedWidth(1)
        sep.setStyleSheet('background:#d0d7de;margin:4px 0;')
        sep.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._items.append(sep)
        self._relayout()

    def _relayout(self):
        """贪心换行：按可用宽度把按钮铺到多行，并同步自身高度。

        注意：已在布局中的 widget 直接 addWidget 到新坐标即为"移动"，
        不要 setParent(None) 再加回——那个中间无父状态会在窗口销毁阶段
        触发原生层崩溃。销毁期间布局可能已析构，静默跳过。"""
        try:
            avail = max(self.width(), 200)
            row, col, x = 0, 0, 0
            for w in self._items:
                hint = w.sizeHint().width()
                if col > 0 and x + hint > avail:
                    row += 1
                    col = 0
                    x = 0
                self._layout.addWidget(w, row, col)
                x += hint
                col += 1
            rows = row + 1
            new_h = rows * self._row_h + 1
            if self.height() != new_h:
                self.setFixedHeight(new_h)
                self.heightChanged.emit(new_h)
        except RuntimeError:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event):
        super().showEvent(event)
        self._relayout()

    def clear(self):
        """清空工具栏按钮。"""
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._items.clear()
        self._pairs.clear()

    def actions(self) -> list[QAction]:
        """返回当前按钮关联的 QAction。"""
        return [a for _, a in self._pairs if a is not None]

    def refresh_text(self):
        """按 QAction 当前 text 刷新按钮文案（固定文案与图标按钮除外）。"""
        for btn, action in self._pairs:
            if action is None:
                continue
            fixed = btn.property('fixedText')
            if btn.toolButtonStyle() == Qt.ToolButtonIconOnly:
                btn.setToolTip(fixed or self._clean_tool_text(action.text()))
                continue
            btn.setText(fixed or self._clean_tool_text(action.text()))
            btn.setToolTip(action.toolTip() or fixed or '')
