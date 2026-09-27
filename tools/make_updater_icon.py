"""生成 updater 专用图标 updater/updater_icon.ico（可重复运行）。

设计：圆角深蓝渐变底 + 白色双弧循环刷新箭头（⟳），中心小风速计十字点缀，
传达「循环更新」。保留工具，改版品牌时可重新生成。
"""
import math
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'updater', 'updater_icon.ico')
S = 1024          # 超采样画布，缩出平滑小尺寸


def rounded_gradient(size: int) -> Image.Image:
    """圆角方块 + 垂直渐变底。"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    grad = Image.new('RGBA', (size, size))
    top, bot = (47, 127, 214, 255), (20, 66, 128, 255)
    px = grad.load()
    for y in range(size):
        t = y / (size - 1)
        c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(4))
        for x in range(size):
            px[x, y] = c
    mask = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(mask)
    radius = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)
    return img


def draw_arrows(img: Image.Image) -> None:
    """白色双弧刷新环 + 实心箭头。"""
    d = ImageDraw.Draw(img)
    s = img.size[0]
    w = int(s * 0.085)                     # 弧线宽
    pad = int(s * 0.20)
    box = [pad, pad, s - pad, s - pad]
    gap = 34                               # 每段弧留出的缺口（度）
    col = (255, 255, 255, 255)
    # 上弧：从 150° 到 30°（顺时针留缺口），下弧对称
    d.arc(box, start=-30 + gap, end=210 - gap, fill=col, width=w)
    d.arc(box, start=150 + gap, end=30 - gap, fill=col, width=w)

    def arrow(angle_deg: int, tip_cw: bool):
        """在弧线端点画实心三角箭头（沿顺时针方向）。"""
        a = math.radians(angle_deg)
        cx = (s - 2 * pad) / 2
        r = (s - 2 * pad) / 2
        ex, ey = s / 2 + r * math.cos(a), s / 2 + r * math.sin(a)
        # 切线方向（顺时针）：角度 + 90°
        t = a + math.pi / 2 if tip_cw else a - math.pi / 2
        L = s * 0.13                       # 箭头长度
        W = s * 0.115                      # 箭头半宽
        tip = (ex + L * math.cos(t), ey + L * math.sin(t))
        base_t = (ex - L * 0.2 * math.cos(t), ey - L * 0.2 * math.sin(t))
        n = t - math.pi / 2
        p1 = (base_t[0] + W * math.cos(n), base_t[1] + W * math.sin(n))
        p2 = (base_t[0] - W * math.cos(n), base_t[1] - W * math.sin(n))
        d.polygon([tip, p1, p2], fill=col)

    arrow(-30 + gap, True)                 # 上弧起点端（顺时针尾随箭头）
    arrow(150 + gap, True)
    # 中心点缀：小风车十字（圆心 + 三叶）
    cx = cy = s / 2
    rr = s * 0.055
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=col)
    for ang in (90, 210, 330):
        a = math.radians(ang)
        x2 = cx + s * 0.11 * math.cos(a)
        y2 = cy + s * 0.11 * math.sin(a)
        d.line([cx, cy, x2, y2], fill=col, width=int(s * 0.045))
        br = s * 0.035
        d.ellipse([x2 - br, y2 - br, x2 + br, y2 + br], fill=col)


def main():
    base = rounded_gradient(S)
    draw_arrows(base)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]
    base.save(OUT, format='ICO', sizes=sizes)
    print('written', OUT, os.path.getsize(OUT), 'bytes')
    # 预览图（便于人工确认）
    prev = os.path.join(ROOT, 'updater', 'updater_icon_preview.png')
    base.resize((256, 256), Image.LANCZOS).save(prev)
    print('preview', prev)


if __name__ == '__main__':
    main()
