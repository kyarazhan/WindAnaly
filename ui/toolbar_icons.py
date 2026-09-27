"""工具栏彩色图标：按 Windographer 原版风格用 QPainter 绘制，零外部资源。

每个 key 对应一个 16×16 彩色小图标（按 size 缩放绘制）；
未知 key 返回空图标（调用方回落为纯文字按钮）。
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap

# 常用色板
INK = '#3b4652'          # 描边深灰
BLUE = '#2c7be5'
NAVY = '#1a4e8a'
LBLUE = '#9ec3e8'
GREEN = '#27ae60'
RED = '#e03131'
ORANGE = '#f0932b'
YELLOW = '#f6c445'
GRAY = '#6b7683'
WHITE = '#ffffff'


def _pixmap(size: int, draw) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(INK))
    pen.setWidth(1)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    # 以 16×16 的逻辑坐标绘制，再适配任意尺寸
    p.scale(size / 16.0, size / 16.0)
    draw(p)
    p.end()
    return pm


def _fill_rect(p, x, y, w, h, fill, outline=None, lw=1.0):
    p.setPen(QPen(QColor(outline), lw) if outline else Qt.NoPen)
    p.setBrush(QColor(fill))
    p.drawRect(x, y, w, h)


def _page(p, x=3.0, y=1.0, w=9.0, h=13.0, lines=True):
    """白纸 + 折角 + 蓝色文字行。"""
    _fill_rect(p, x, y, w, h, WHITE, INK)
    p.setBrush(QColor('#dfe6ee'))
    p.setPen(QPen(QColor(INK), 0.8))
    p.drawPolygon([QPointF(x + w - 3, y), QPointF(x + w, y + 3),
                   QPointF(x + w - 3, y + 3)])
    if lines:
        p.setPen(QPen(QColor(BLUE), 1))
        for i, lw in enumerate((5, 5, 3)):
            p.drawLine(x + 2, y + 4 + i * 3, x + 2 + lw, y + 4 + i * 3)


def _folder(p, x=1.0, y=3.0, w=13.0, h=10.0):
    """黄色文件夹（后盖 + 前身）。"""
    p.setPen(QPen(QColor('#b8860b'), 1))
    p.setBrush(QColor('#ffd75e'))
    p.drawPolygon([QPointF(x, y + 2), QPointF(x + 4, y + 2),
                   QPointF(x + 6, y), QPointF(x + w, y),
                   QPointF(x + w, y + h), QPointF(x, y + h)])
    p.setBrush(QColor(YELLOW))
    p.drawRect(x, y + 3, w, h - 3)


def _plus(p, cx, cy, r=3.0, color=GREEN):
    """绿色加号。"""
    p.setPen(QPen(QColor(color), 2))
    p.drawLine(cx - r, cy, cx + r, cy)
    p.drawLine(cx, cy - r, cx, cy + r)


def _flag(p, x=3.0, y=1.0, w=8.0, h=5.0, color=RED):
    """杆 + 三角旗。"""
    p.setPen(QPen(QColor(GRAY), 1.2))
    p.drawLine(x, y, x, y + 13)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon([QPointF(x, y), QPointF(x + w, y + h / 2),
                   QPointF(x, y + h)])


def _clock(p, cx, cy, r=4.0, ring=GREEN):
    """小时钟：白面 + 彩色圈 + 指针。"""
    p.setPen(QPen(QColor(ring), 1.4))
    p.setBrush(QColor(WHITE))
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setPen(QPen(QColor(INK), 1))
    p.drawLine(cx, cy, cx, cy - r + 1.4)
    p.drawLine(cx, cy, cx + r - 1.6, cy)


def _circle_badge(p, cx=8.0, cy=8.0, r=6.5, glyph='?', ring=BLUE):
    """圆形徽章：彩色圆 + 白色字符（? / i）。"""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ring))
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setPen(QPen(QColor(WHITE), 1))
    f = QFont('Segoe UI', 9)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(cx - r, cy - r, 2 * r, 2 * r), Qt.AlignCenter, glyph)


def _gear(p, cx=8.0, cy=8.0, r=5.5, color=ORANGE):
    """橙色齿轮。"""
    p.setPen(QPen(QColor('#b8860b'), 1))
    p.setBrush(QColor(color))
    poly = []
    teeth = 8
    for i in range(teeth * 2):
        ang = math.pi * i / teeth
        rad = r if i % 2 == 0 else r - 1.6
        poly.append(QPointF(cx + rad * math.cos(ang),
                            cy + rad * math.sin(ang)))
    p.drawPolygon(poly)
    p.setBrush(QColor(WHITE))
    p.drawEllipse(QPointF(cx, cy), 2.0, 2.0)


def _bars(p, heights, x0=3.0, bw=2.4, gap=0.7, color=BLUE, base=14.0):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    x = x0
    for h in heights:
        p.drawRect(x, base - h, bw, h)
        x += bw + gap


# ---------------------------------------------------------------------------
# key → 绘制函数
# ---------------------------------------------------------------------------
def _d_new(p):
    _page(p)


def _d_open(p):
    _folder(p)


def _d_append(p):
    _folder(p, x=1.0, y=3.0, w=10.0, h=9.0)
    _plus(p, 12.0, 11.5, 3.0)


def _d_save(p):
    _fill_rect(p, 2, 2, 12, 12, '#2b6cb0', '#1a4e8a')
    _fill_rect(p, 5, 2, 6, 4, LBLUE)
    _fill_rect(p, 4, 9, 8, 5, WHITE)
    p.setPen(QPen(QColor(GRAY), 1))
    p.drawLine(5, 11, 11, 11)


def _d_data_coverage(p):
    colors = [BLUE, LBLUE, GREEN,
              LBLUE, GREEN, '#c9d4de',
              GREEN, '#c9d4de', BLUE]
    x0, y0, cell = 2.0, 2.0, 4.0
    for i, c in enumerate(colors):
        r_, c_ = divmod(i, 3)
        _fill_rect(p, x0 + c_ * cell, y0 + r_ * cell, cell - 0.6,
                   cell - 0.6, c)


def _d_doc_history(p):
    _page(p, 2, 1, 8, 11, lines=False)
    p.setPen(QPen(QColor(GRAY), 0.8))
    for i in range(3):
        p.drawLine(3.5, 4 + i * 2.4, 8.5, 4 + i * 2.4)
    _clock(p, 10.5, 10.0, 4.2)


def _d_configure_dataset(p):
    _gear(p)


def _d_vertical_extrap(p):
    p.setPen(QPen(QColor(GRAY), 0.8))
    p.drawLine(3, 14, 14, 14)
    p.setBrush(QColor(BLUE))
    p.setPen(Qt.NoPen)
    for x, y in ((4, 12), (7, 9.5), (10, 7)):
        p.drawEllipse(QPointF(x, y), 1.4, 1.4)
    p.setPen(QPen(QColor(RED), 1.3, Qt.DashLine))
    p.drawLine(10, 7, 13.5, 2.5)


def _d_calibration(p):
    p.setPen(QPen(QColor(RED), 1.4))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(8, 8), 6, 6)
    p.drawEllipse(QPointF(8, 8), 3, 3)
    p.setBrush(QColor(YELLOW))
    p.drawEllipse(QPointF(8, 8), 1.2, 1.2)
    p.setPen(QPen(QColor(GRAY), 0.8))
    p.drawLine(8, 1, 8, 3)
    p.drawLine(8, 13, 8, 15)
    p.drawLine(1, 8, 3, 8)
    p.drawLine(13, 8, 15, 8)


def _d_flag_manual(p):
    _flag(p)


def _d_flag_scatter(p):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(BLUE))
    for x, y in ((4, 13), (7, 11), (11, 12), (13, 9), (9, 8)):
        p.drawEllipse(QPointF(x, y), 1.1, 1.1)
    _flag(p, 2, 1, 6, 4)


def _d_flag_rule(p):
    _page(p, 2, 1, 9, 13, lines=False)
    p.setPen(QPen(QColor(GREEN), 1.4))
    for i in range(3):
        y = 4 + i * 3.4
        p.drawLine(3.5, y, 5, y + 1.2)
        p.drawLine(5, y + 1.2, 7.5, y - 1)
    _flag(p, 9, 2, 5.5, 4)


def _d_flag_tower_shadow(p):
    p.setPen(QPen(QColor(GRAY), 1.3))
    p.drawLine(5, 2, 3, 14)
    p.drawLine(5, 2, 7, 14)
    p.drawLine(3.8, 6, 6.2, 6)
    p.drawLine(3.2, 10, 6.8, 10)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor('#8d99a6'))
    p.drawPolygon([QPointF(8, 14), QPointF(11, 7), QPointF(14, 14)])
    _flag(p, 10, 1, 5, 3.6)


def _d_flag_inspect(p):
    _flag(p, 2, 1, 6, 4)
    p.setPen(QPen(QColor(BLUE), 1.5))
    p.setBrush(QColor(218, 232, 248, 200))
    p.drawEllipse(QPointF(9, 8), 3.6, 3.6)
    p.setPen(QPen(QColor(GRAY), 1.8))
    p.drawLine(11.6, 10.6, 14.5, 13.5)


def _d_data_recovery(p):
    _bars(p, (4.0, 6.5, 5.0))
    p.setPen(QPen(QColor(GREEN), 1.6))
    p.drawLine(3, 9, 7, 6.5)
    p.drawLine(7, 6.5, 12, 2.5)
    p.setBrush(QColor(GREEN))
    p.setPen(Qt.NoPen)
    p.drawPolygon([QPointF(13.5, 1.5), QPointF(12.5, 4.5),
                   QPointF(10.2, 2.2)])


def _d_turbulence(p):
    p.setPen(QPen(QColor(BLUE), 1.4))
    p.drawPolyline([QPointF(1, 8), QPointF(4, 4), QPointF(6, 11),
                    QPointF(9, 3), QPointF(11, 12), QPointF(15, 6)])
    red2 = QColor(RED)
    red2.setAlpha(160)
    p.setPen(QPen(red2, 1.1))
    p.drawPolyline([QPointF(1, 12), QPointF(5, 9), QPointF(8, 14),
                    QPointF(12, 8), QPointF(15, 10)])


def _d_wind_shear_analysis(p):
    p.setPen(QPen(QColor(GRAY), 0.8))
    p.drawLine(3, 14, 14, 14)
    p.drawLine(3, 14, 3, 2)
    p.setPen(QPen(QColor(NAVY), 1.4))
    p.drawLine(4, 12.5, 13.5, 3)
    p.setBrush(QColor(GREEN))
    p.setPen(Qt.NoPen)
    for x, y in ((4, 12.5), (8.5, 8), (13.5, 3)):
        p.drawEllipse(QPointF(x, y), 1.3, 1.3)


def _d_wind_speed_dist(p):
    _bars(p, (2.5, 5.5, 9.0, 7.0, 4.5), color=LBLUE, base=14.0)
    p.setPen(QPen(QColor(RED), 1.4))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(2.0, 1.0, 12.5, 20.0), 20 * 16, 140 * 16)


def _d_tower_distortion(p):
    p.setPen(QPen(QColor(GRAY), 1.3))
    p.drawLine(6, 2, 6, 14)
    p.drawLine(6, 4, 9, 8)
    p.setPen(QPen(QColor(ORANGE), 1.4))
    p.drawPolyline([QPointF(2, 12), QPointF(5, 6), QPointF(8, 5.2),
                    QPointF(11, 7), QPointF(14, 12)])


def _d_inflow_angle(p):
    p.setPen(QPen(QColor(GREEN), 1.5))
    p.drawLine(3, 13, 14, 13)
    p.drawLine(3, 13, 12, 3)
    p.setPen(QPen(QColor(INK), 1))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(3, 7, 12, 12), 0 * 16, 45 * 16)


def _d_turbine_output(p):
    p.setPen(QPen(QColor(GRAY), 1.4))
    p.drawLine(8, 8, 8, 15)
    p.setPen(QPen(QColor(BLUE), 1.8))
    for ang in (30, 150, 270):
        p.save()
        p.translate(8, 7)
        p.rotate(ang)
        p.drawLine(0, 0, 0, -6)
        p.restore()
    p.setBrush(QColor(WHITE))
    p.setPen(QPen(QColor(INK), 1))
    p.drawEllipse(QPointF(8, 7), 1.5, 1.5)


def _d_short_time_interval(p):
    _clock(p, 6.0, 8.0, 5.0, ring=BLUE)
    _bars(p, (3.0, 5.0, 4.0), x0=12.0, bw=1.2, gap=0.5, color=ORANGE,
          base=14.0)


def _d_about(p):
    _circle_badge(p, glyph='i')


def _d_help(p):
    _circle_badge(p, glyph='?')


_COLOR_DRAWERS = {
    'new': _d_new,
    'open': _d_open,
    'append': _d_append,
    'save': _d_save,
    'data_coverage': _d_data_coverage,
    'doc_history': _d_doc_history,
    'configure_dataset': _d_configure_dataset,
    'vertical_extrap': _d_vertical_extrap,
    'calibration': _d_calibration,
    'flag_manual': _d_flag_manual,
    'flag_scatter': _d_flag_scatter,
    'flag_rule': _d_flag_rule,
    'flag_tower_shadow': _d_flag_tower_shadow,
    'flag_inspect': _d_flag_inspect,
    'data_recovery': _d_data_recovery,
    'turbulence': _d_turbulence,
    'wind_shear_analysis': _d_wind_shear_analysis,
    'wind_speed_dist': _d_wind_speed_dist,
    'tower_distortion': _d_tower_distortion,
    'inflow_angle': _d_inflow_angle,
    'turbine_output': _d_turbine_output,
    'short_time_interval': _d_short_time_interval,
    'about': _d_about,
    'help': _d_help,
}


def toolbar_icon(key: str, size: int = 16) -> QIcon:
    """根据 key 返回彩色工具栏图标；未知 key 返回空图标（纯文字回落）。"""
    draw = _COLOR_DRAWERS.get(key)
    if draw is None:
        return QIcon()
    return QIcon(_pixmap(size, draw))
