"""生成 updater 专用图标 updater/updater_icon.ico（可重复运行）。

v2 设计（专业扁平风）：深蓝对角渐变圆角方 + 白色 300° 刷新环
（单箭头，切线方向实心三角）+ 居中下载箭头，顶部玻璃高光。
"""
import math
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'updater', 'updater_icon.ico')
S = 1024


def base_tile(size: int) -> Image.Image:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    grad = Image.new('RGBA', (size, size))
    top, bot = (43, 122, 214, 255), (16, 58, 118, 255)
    # 对角渐变：左上 → 右下
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(4))
            px[x, y] = c
    mask = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1],
                        radius=int(size * 0.225), fill=255)
    img.paste(grad, (0, 0), mask)
    # 顶部玻璃高光（上半区 6% 白）
    hl = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    dh = ImageDraw.Draw(hl)
    dh.rounded_rectangle([0, 0, size - 1, int(size * 0.52)],
                         radius=int(size * 0.225), fill=(255, 255, 255, 16))
    img = Image.alpha_composite(img, hl)
    return img


def draw_mark(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    s = img.size[0]
    white = (255, 255, 255, 255)
    soft = (224, 238, 255, 255)

    # ---- 刷新环：300° 圆弧 + 切线箭头 ----
    ring_w = int(s * 0.062)
    pad = int(s * 0.205)
    box = [pad, pad, s - pad, s - pad]
    d.arc(box, start=-20, end=235, fill=white, width=ring_w)
    # 箭头位于弧线终点角度 -20°（顺时针末端）
    ang = math.radians(-20)
    r = (s - 2 * pad) / 2
    ex, ey = s / 2 + r * math.cos(ang), s / 2 + r * math.sin(ang)
    tangent = ang + math.pi / 2                      # 顺时针方向
    L, W = s * 0.115, s * 0.105
    tip = (ex + L * math.cos(tangent), ey + L * math.sin(tangent))
    n = tangent - math.pi / 2
    b1 = (ex + W * math.cos(n) * 0.9, ey + W * math.sin(n) * 0.9)
    b2 = (ex - W * math.cos(n) * 0.9, ey - W * math.sin(n) * 0.9)
    d.polygon([tip, b1, b2], fill=white)

    # ---- 居中下载箭头（竖杆 + 三角头）----
    cx = s / 2
    cy = s * 0.505
    shaft_w = s * 0.062
    shaft_top = s * 0.335
    head_w = s * 0.21
    head_h = s * 0.145
    d.rectangle([cx - shaft_w / 2, shaft_top,
                 cx + shaft_w / 2, cy - head_h * 0.25], fill=soft)
    d.polygon([(cx - head_w / 2, cy - head_h * 0.25),
               (cx + head_w / 2, cy - head_h * 0.25),
               (cx, cy + head_h * 0.75)], fill=soft)
    # 底部托盘
    tray_w = s * 0.34
    d.rounded_rectangle([cx - tray_w / 2, cy + head_h * 0.9,
                         cx + tray_w / 2, cy + head_h * 0.9 + s * 0.045],
                        radius=s * 0.02, fill=soft)


def main():
    img = base_tile(S)
    draw_mark(img)
    img.save(OUT, format='ICO',
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                    (128, 128), (256, 256)])
    print('written', OUT, os.path.getsize(OUT), 'bytes')
    prev = os.path.join(ROOT, 'updater', 'updater_icon_preview.png')
    img.resize((256, 256), Image.LANCZOS).save(prev)
    print('preview', prev)


if __name__ == '__main__':
    main()
