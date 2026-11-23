# -*- coding: utf-8 -*-
"""pygame 兼容层。

海龟编辑器（Pyblock / TurtleEditor）内置的是 **Python 3.6.5 + pygame 1.9.6**，
比常见的 pygame 2.x 少若干 API。所有"新 API"统一在这里兜底，业务代码只调用
本模块，避免在游戏逻辑里到处写版本判断。

实测缺失（2026-11-23，编辑器 Python 3.6.5 / pygame 1.9.6）：
  - ``pygame.draw.rect(..., border_radius=)``   -> 本模块 rounded_rect()
  - ``pygame.Rect.clipline()``                  -> 本模块 clip_line()
  - ``pygame.SCALED``                           -> 不使用，固定窗口尺寸
  - ``math.dist()``（Python 3.8+）              -> 用 hypot
  - 8 位调色板显示面（dummy 驱动默认）          -> set_mode 必须显式传 depth=32

可用（无需兜底）：smoothscale、Vector2.rotate、fill(BLEND_MULT)、set_alpha、
gfxdraw、draw.aalines。
"""

import math

import pygame


def rounded_rect_points(rect, radius, steps=6):
    """返回圆角矩形的多边形顶点（顺时针，可直接用于 draw.polygon）。"""
    x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    r = int(min(radius, w // 2, h // 2))
    if r <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]

    pts = []
    # 四个圆角：左上 180°→270°，右上 270°→360°，右下 0°→90°，左下 90°→180°
    corners = (
        (x + r, y + r, 180.0),
        (x + w - r, y + r, 270.0),
        (x + w - r, y + h - r, 0.0),
        (x + r, y + h - r, 90.0),
    )
    for cx, cy, start in corners:
        for i in range(steps + 1):
            a = math.radians(start + 90.0 * i / steps)
            pts.append((int(round(cx + r * math.cos(a))), int(round(cy + r * math.sin(a)))))
    return pts


def rounded_rect(surface, color, rect, radius=8, width=0, smooth=False):
    """圆角矩形，替代 pygame 2.x 的 ``border_radius`` 参数。

    width=0 为填充，width>0 为描边。smooth=True 时用 2 倍超采样再缩小，
    得到抗锯齿的圆角（静态面板用，逐帧绘制会掉帧）。

    实现说明：**不能用 gfxdraw.aapolygon 描边**——pygame 1.9.6 的 SDL_gfx
    在 28 个点的闭合路径上会漏画整条底边（实测，2026-11-23）。改用
    ``pygame.draw.lines(..., closed=True, width=w)``，绘制完整无缺口。
    """
    x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    pts = rounded_rect_points(rect, radius)

    if width and width > 0:
        pygame.draw.lines(surface, color, True, pts, int(width))
        return

    if smooth:
        big = pygame.Surface((w * 2, h * 2), pygame.SRCALPHA)
        big_pts = rounded_rect_points((0, 0, w * 2, h * 2), radius * 2)
        pygame.draw.polygon(big, color, big_pts)
        surface.blit(pygame.transform.smoothscale(big, (w, h)), (x, y))
        return

    pygame.draw.polygon(surface, color, pts)


def panel(surface, rect, radius=14, fill=(255, 255, 255), border=(45, 45, 45), width=3, smooth=True):
    """游戏内统一的面板样式：先填充再描边。"""
    rounded_rect(surface, fill, rect, radius, 0, smooth=smooth)
    if border is not None and width:
        rounded_rect(surface, border, rect, radius, width)


def clip_line(rect, p1, p2):
    """替代 pygame 2.0 的 ``Rect.clipline``：返回线段在矩形内的部分。

    无交集时返回 None，否则返回 ((x1, y1), (x2, y2))。
    """
    x0, y0, w, h = rect[0], rect[1], rect[2], rect[3]
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])

    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    edges = ((-dx, x1 - x0), (dx, x0 + w - x1), (-dy, y1 - y0), (dy, y0 + h - y1))
    for p, q in edges:
        if p == 0:
            if q < 0:
                return None
        else:
            t = q / p
            if p < 0:
                if t > t1:
                    return None
                if t > t0:
                    t0 = t
            else:
                if t < t0:
                    return None
                if t < t1:
                    t1 = t
    if t0 > t1:
        return None
    return (
        (x1 + dx * t0, y1 + dy * t0),
        (x1 + dx * t1, y1 + dy * t1),
    )


def dist(a, b):
    """替代 math.dist（Python 3.8+）。"""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def tint(surface, color):
    """给白底黑线的贴图染色，黑线与透明度保持不变。

    原理：新建一层铺满 color 且 alpha=255，再用 BLEND_RGBA_MULT 乘上原图。
    白色 (255,255,255) × color = color；黑线 (0,0,0) × color = 黑；
    alpha 由原图的 alpha 决定，所以透明背景仍然是透明。

    strength 混合（半透明染色）不在这里做——需要时对返回结果 set_alpha。
    """
    out = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    out.fill(tuple(color) + (255,))
    out.blit(surface, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return out


def make_display(size, depth=32):
    """创建显示面。必须显式指定 depth=32。

    pygame 1.9.6 在 SDL_VIDEODRIVER=dummy（无头自检、CI）下默认返回 8 位
    调色板表面，会导致文字变实心块、带 alpha 的贴图贴不上去。
    """
    try:
        return pygame.display.set_mode(size, 0, depth)
    except Exception:
        return pygame.display.set_mode(size)
