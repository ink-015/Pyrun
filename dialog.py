# -*- coding: utf-8 -*-
"""对话与告示牌文本面板（M6）。

为什么单独一个模块：这块只做"把几页文字画成一个会翻页的框"，不碰关卡、
不碰玩家、不碰输入。放在 scenes.py 里会让本已 900 行的场景再涨一截，
而且它天然可以脱机测试（给个 Surface 就能画）。

排版规则只有三条：

  1. 自动折行按**像素宽度**算，不按字数——中英文混排时按字数折会豁口。
  2. 面板高度由内容撑开，行数少时不会拖一大片空白。
  3. 边框是手绘抖动线，但抖动**确定性**（按顶点序号算），否则每帧重画
     会让框线像在抽筋。
"""

import math

import pygame

import compat
import config


def wrap_text(font, text, max_w):
    """按像素宽度折行。中文逐字断，英文尽量在空格处断。

    返回行列表。空字符串返回 [""]，这样"空一行"也能排版。
    """
    if not text:
        return [u""]

    lines = []
    cur = u""
    for ch in text:
        if ch == u"\n":
            lines.append(cur)
            cur = u""
            continue
        probe = cur + ch
        if font.size(probe)[0] <= max_w:
            cur = probe
            continue
        # 行放不下了。英文单词尽量整块换行，避免 "jump" 被切成 "jum/p"
        if ch != u" " and cur and u" " in cur:
            head, _, tail = cur.rpartition(u" ")
            if tail and font.size(tail + ch)[0] <= max_w:
                lines.append(head)
                cur = tail + ch
                continue
        lines.append(cur)
        cur = u"" if ch == u" " else ch
    lines.append(cur)
    return lines


def _wobble_rect(surface, rect, color, width=2, amp=1.5, step=26, seed=0):
    """画一个手绘感的矩形边框：每条边按 step 打点并做确定性抖动。"""
    pts = []
    for (x0, y0, x1, y1) in (
            (rect.left, rect.top, rect.right, rect.top),
            (rect.right, rect.top, rect.right, rect.bottom),
            (rect.right, rect.bottom, rect.left, rect.bottom),
            (rect.left, rect.bottom, rect.left, rect.top)):
        horizontal = (y0 == y1)
        length = abs(x1 - x0) if horizontal else abs(y1 - y0)
        n = max(2, int(length // step))
        for i in range(n):
            t = i / float(n)
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            h = (int(x) * 73856093) ^ (int(y) * 19349663) ^ (seed * 83492791)
            j = ((h & 0xFFFF) / 65535.0 - 0.5) * 2.0 * amp
            if horizontal:
                y += j
            else:
                x += j
            pts.append((int(round(x)), int(round(y))))
    pts.append(pts[0])
    pygame.draw.lines(surface, color, False, pts, width)


class Dialog(object):
    """一个可翻页的文本框。

    pages 是字符串列表；speaker 为空表示"没有人在说话"（告示牌），
    这时不画名字，改用一块小木牌图标，让玩家知道自己读的是牌子。
    """

    PAD_X = 22
    PAD_Y = 16
    WIDTH = 660
    LINE_H = 27
    TAIL = 14

    def __init__(self, speaker, pages, kind="npc"):
        self.speaker = speaker or u""
        self.pages = [p for p in pages if p is not None] or [u"…"]
        self.kind = kind
        self.index = 0
        self.age = 0.0

    # ---- 状态 ----
    def active(self):
        return self.index < len(self.pages)

    def page(self):
        if not self.active():
            return u""
        return self.pages[self.index]

    def advance(self):
        """翻到下一页。返回 False 表示看完了，可以关掉。"""
        self.index += 1
        self.age = 0.0
        return self.active()

    def update(self, dt):
        self.age += dt

    # ---- 绘制 ----
    def layout(self, font):
        """算出面板矩形与每一行文字。抽出来是为了能单独断言排版。"""
        inner_w = self.WIDTH - self.PAD_X * 2
        lines = wrap_text(font, self.page(), inner_w)
        head = 24 if self.speaker else 0
        height = self.PAD_Y * 2 + head + self.LINE_H * len(lines) + 22
        rect = pygame.Rect((config.WIDTH - self.WIDTH) // 2,
                           config.HEIGHT - 40 - height, self.WIDTH, height)
        return rect, lines

    def draw(self, surface, font, body_font=None, tail=None):
        rect, lines = self.layout(font)
        body = body_font or font

        # 半透明压暗：对话框盖住的画面不该还在抢注意力
        shade = pygame.Surface((config.WIDTH, config.HEIGHT), pygame.SRCALPHA)
        shade.fill((250, 247, 238, 60))
        surface.blit(shade, (0, 0))

        # 气泡尾巴：指向说话的人/牌子。只画 14px 的三角是不够的——玩家
        # 看不出它连着谁。三角之上再连一条细虚线到对象头顶，指向就明确了。
        if tail is not None:
            tx, ty = tail
            tx = max(rect.left + 40, min(rect.right - 40, int(tx)))
            tip = (tx + 3, rect.top - self.TAIL)
            pygame.draw.polygon(surface, (255, 255, 255),
                                [(tx - 12, rect.top + 4), (tx + 12, rect.top + 4),
                                 tip])
            for a, b in (((tx - 12, rect.top + 4), tip),
                         (tip, (tx + 12, rect.top + 4))):
                pygame.draw.line(surface, config.COLOR_INK, a, b, 2)
            if ty is not None and ty < rect.top - self.TAIL - 6:
                y = rect.top - self.TAIL - 6
                while y > ty:
                    pygame.draw.line(surface, (206, 200, 190), (tx, y),
                                     (tx, max(y - 6, ty)), 1)
                    y -= 12

        compat.rounded_rect(surface, (255, 255, 255), rect, radius=4, width=0)
        _wobble_rect(surface, rect, config.COLOR_INK, width=2, seed=7)

        y = rect.top + self.PAD_Y
        if self.speaker:
            name_font, _ = _font(17, True)
            color = (config.COLOR_NPC if self.kind == "npc"
                     else config.COLOR_MUTED)
            surface.blit(name_font.render(self.speaker, True, color),
                         (rect.left + self.PAD_X, y))
            y += 24
        else:
            # 告示牌：左上角钉一颗小钉子，说明"这是块牌子，不是人说的"
            pygame.draw.circle(surface, config.COLOR_MUTED,
                               (rect.left + self.PAD_X + 4, y + 8), 4)
            pygame.draw.circle(surface, config.COLOR_MUTED,
                               (rect.right - self.PAD_X - 4, y + 8), 4)
            y += 0

        for line in lines:
            surface.blit(body.render(line, True, config.COLOR_INK),
                         (rect.left + self.PAD_X, y))
            y += self.LINE_H

        hint_font, _ = _font(14)
        hint = (u"按 E 继续" if self.index + 1 < len(self.pages)
                else u"按 E 关闭")
        hw = hint_font.size(hint)[0]
        # 呼吸一下再出现，避免玩家还没看清就被提示催着按
        if self.age > 0.25:
            surface.blit(hint_font.render(hint, True, config.COLOR_CAMP),
                         (rect.right - self.PAD_X - hw, rect.bottom - 26))
        return rect


_FONT_CACHE = {}


def _font(size, bold=False):
    if (size, bold) not in _FONT_CACHE:
        import assets
        _FONT_CACHE[(size, bold)] = assets.font(size, bold)
    return _FONT_CACHE[(size, bold)]
