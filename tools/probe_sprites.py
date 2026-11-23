# -*- coding: utf-8 -*-
"""贴图素材探测器。

打印每张 PNG 的画布尺寸与 alpha 包围盒。做序列帧动画时这两个数据
决定了「锚点对齐」怎么做：

  画布尺寸不一致 -> 直接 blit 会漂移
  bbox 底边不一致 -> 脚底悬空或陷地，跑动时上下抖
  bbox 水平中心不一致 -> 角色左右横跳

用法：
    python tools/probe_sprites.py assets/images/hero
    python tools/probe_sprites.py assets/images/hero --scale 26 70
"""
import os
import sys

import pygame


def bbox_of(surf):
    """返回不透明像素的包围盒；全透明返回 None。"""
    rect = surf.get_bounding_rect()
    if rect.width <= 0 or rect.height <= 0:
        return None
    return rect


def main(argv):
    if len(argv) < 2:
        print(u"用法：python tools/probe_sprites.py <目录> [--scale W H]")
        return 2
    folder = argv[1]
    if not os.path.isdir(folder):
        print(u"目录不存在：%s" % folder)
        return 2

    target_w = target_h = None
    if "--scale" in argv:
        i = argv.index("--scale")
        try:
            target_w = float(argv[i + 1])
            target_h = float(argv[i + 2])
        except (IndexError, ValueError):
            print(u"--scale 需要两个数字：宽 高")
            return 2

    pygame.init()
    try:
        pygame.display.set_mode((64, 64), 0, 32)
    except Exception:
        pass

    names = sorted([n for n in os.listdir(folder) if n.lower().endswith(".png")])
    if not names:
        print(u"目录里没有 PNG")
        return 1

    print("=" * 78)
    print(u" %-16s %-10s %-22s %-10s" % (u"文件", u"画布", u"内容bbox", u"底边距"))
    print("=" * 78)

    rows = []
    for name in names:
        path = os.path.join(folder, name)
        try:
            surf = pygame.image.load(path)
        except Exception as exc:
            print(u" %-16s 加载失败 %s" % (name, exc))
            continue
        if surf.get_alpha() is not None or surf.get_flags() & pygame.SRCALPHA:
            surf = surf.convert_alpha()
        box = bbox_of(surf)
        w, h = surf.get_size()
        if box is None:
            print(u" %-16s %-10s %s" % (name, "%dx%d" % (w, h), u"全透明"))
            continue
        bottom_gap = h - (box.y + box.height)
        rows.append((name, w, h, box, bottom_gap))
        print(u" %-16s %-10s %-22s %d"
              % (name, "%dx%d" % (w, h),
                 "x=%d y=%d w=%d h=%d" % (box.x, box.y, box.width, box.height),
                 bottom_gap))

    if not rows:
        return 1

    # 一致性统计：这决定了动画方案
    canvases = set((r[1], r[2]) for r in rows)
    bot_gaps = set(r[4] for r in rows)
    heights = set(r[3].height for r in rows)
    widths = set(r[3].width for r in rows)

    print("-" * 78)
    print(u" 画布尺寸一致 : %s (%d 种)" % (u"是" if len(canvases) == 1 else u"否", len(canvases)))
    print(u" 底边距一致   : %s (%s)" % (u"是" if len(bot_gaps) == 1 else u"否",
                                        ", ".join(str(g) for g in sorted(bot_gaps))))
    print(u" 内容高度范围 : %d ~ %d px" % (min(heights), max(heights)))
    print(u" 内容宽度范围 : %d ~ %d px" % (min(widths), max(widths)))

    tallest = max(rows, key=lambda r: r[3].height)
    print(u" 最高一帧     : %s (h=%d)" % (tallest[0], tallest[3].height))

    if target_h:
        s = target_h / float(tallest[3].height)
        print("-" * 78)
        print(u" 缩放到目标高 %.0f px 时：" % target_h)
        print(u"   比例系数   : %.4f" % s)
        print(u"   对应画布   : %.1f x %.1f"
              % (tallest[1] * s, tallest[2] * s))
        print(u"   最宽一帧内容宽 %.1f px（碰撞盒宽 %.0f）"
              % (max(widths) * s, target_w or 0))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
