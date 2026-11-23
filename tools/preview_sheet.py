# -*- coding: utf-8 -*-
"""帧序列对比拼图。

把目录里的 PNG 按两种锚点各排一行，输出一张 PNG 便于肉眼比对：

  第一行：画布底边对齐（保留作者原始坐标系）
  第二行：内容底边对齐（强制脚底贴地）

做序列帧动画前必须看清这两行的差别，否则会出现「跑动时角色上下抖」
或者「脚永远悬空」这类只能靠肉眼发现的错误。

用法：
    python tools/preview_sheet.py assets/images/hero docs/hero_sheet.png
    python tools/preview_sheet.py assets/images/hero docs/x.png --zoom 2 --from run
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pygame

CELL_W = 116
CELL_H = 132
PAD_TOP = 26
LABEL_H = 16
BG = (250, 248, 243)
INK = (30, 30, 30)
LINE_A = (200, 60, 60)
LINE_B = (60, 110, 200)


def pick_font(size):
    """按文件路径探测中文字体，和 config.py 用同一套候选。"""
    import config
    for folder in config.FONT_DIRS:
        for name in ("simhei.ttf", "msyh.ttc", "simkai.ttf"):
            path = os.path.join(folder, name) if folder else name
            if os.path.isfile(path):
                try:
                    return pygame.font.Font(path, size)
                except Exception:
                    continue
    return pygame.font.Font(None, size)


def content_bottom(surf):
    """内容 bbox 的底边 y（画布坐标）。"""
    rect = surf.get_bounding_rect()
    if rect.height <= 0:
        return surf.get_height()
    return rect.y + rect.height


def main(argv):
    if len(argv) < 3:
        print(u"用法：python tools/preview_sheet.py <素材目录> <输出png>")
        return 2
    folder, out_path = argv[1], argv[2]

    zoom = 1.0
    if "--zoom" in argv:
        try:
            zoom = float(argv[argv.index("--zoom") + 1])
        except (IndexError, ValueError):
            zoom = 1.0
    only = None
    if "--from" in argv:
        only = argv[argv.index("--from") + 1].split(",")

    pygame.init()
    pygame.display.set_mode((64, 64), 0, 32)
    font = pick_font(int(11 * max(1.0, zoom)))

    names = sorted([n for n in os.listdir(folder) if n.lower().endswith(".png")])
    if only:
        names = [n for n in names if any(n.startswith(p) for p in only)]
    if not names:
        print(u"目录里没有匹配的 PNG")
        return 1

    frames = []
    for name in names:
        surf = pygame.image.load(os.path.join(folder, name))
        surf = surf.convert_alpha()
        # 缩放前记下内容底边占画布高的比例，缩放后按比例还原，
        # 避免用缩放后的 bbox 重新测（smoothscale 会让半透明边缘扩张）
        ratio_canvas = 1.0
        ratio_bbox = content_bottom(surf) / float(surf.get_height())
        if zoom != 1.0:
            w = max(1, int(surf.get_width() * zoom))
            h = max(1, int(surf.get_height() * zoom))
            surf = pygame.transform.smoothscale(surf, (w, h))
        frames.append((name, surf, ratio_canvas, ratio_bbox))

    cell_w = int(CELL_W * zoom)
    cell_h = int(CELL_H * zoom)
    label_h = int(LABEL_H * zoom)
    pad_top = int(PAD_TOP * zoom)

    cols = len(frames)
    width = cols * cell_w
    height = pad_top + (cell_h + label_h) * 2 + 34
    sheet = pygame.Surface((width, height))
    sheet.fill(BG)

    title = font.render(u"upper: canvas-bottom aligned   lower: bbox-bottom aligned",
                        True, INK)
    sheet.blit(title, (8, 6))

    for row in range(2):
        base_y = pad_top + row * (cell_h + label_h)
        floor_y = base_y + cell_h - int(12 * zoom)
        line_color = LINE_A if row == 0 else LINE_B
        pygame.draw.line(sheet, line_color, (0, floor_y), (width, floor_y),
                         max(2, int(2 * zoom)))

        for i, (name, surf, rc, rb) in enumerate(frames):
            cx = i * cell_w + cell_w // 2
            bottom = int(surf.get_height() * (rb if row else rc))
            x = cx - surf.get_width() // 2
            y = floor_y - bottom
            sheet.blit(surf, (x, y))
            label = font.render(name.replace(".png", ""), True, INK)
            sheet.blit(label, (cx - label.get_width() // 2, floor_y + 4))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    pygame.image.save(sheet, out_path)
    print(u" 输出 :", out_path)
    print(u" 尺寸 : %dx%d（%d 帧 × 2 行）" % (width, height, cols))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
