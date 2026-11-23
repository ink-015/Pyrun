# -*- coding: utf-8 -*-
"""场景系统：Scene 基类、SceneManager、菜单场景与游戏场景占位。

M1 的边界（README §19 M1）：
  - 窗口只在 main.py 创建一次，场景**只接收 surface**，绝不调用 set_mode
  - 不依赖任何外部图片或音频，全部用 compat 绘制 + 系统字体
  - 场景切换延迟到帧末执行，避免在事件循环中途替换自身导致状态错乱

M1 之后本文件继续长大（Pause / Result 等），但这两个接口不变：
  Scene.handle_event / update / draw
  SceneManager.register / start / goto
"""

import os

import pygame

import compat
import config
import player

# ---------------------------------------------------------------- 字体

_FONT_CACHE = {}


def get_font(size, bold=False):
    """按文件路径探测中文字体，带缓存。

    返回 (font, 字体文件名)，文件名用于启动日志。
    M5 做 assets.py 后这里会迁走，届时本函数只保留转发。
    """
    key = (size, bool(bold))
    hit = _FONT_CACHE.get(key)
    if hit is not None:
        return hit

    font = None
    name = "default"
    for folder in config.FONT_DIRS:
        for fn in config.FONT_CANDIDATES:
            path = os.path.join(folder, fn)
            if not os.path.isfile(path):
                continue
            try:
                font = pygame.font.Font(path, size)
                font.set_bold(bold)
                name = fn
                break
            except Exception:
                continue
        if font is not None:
            break

    if font is None:
        font = pygame.font.Font(None, size)
        font.set_bold(bold)

    _FONT_CACHE[key] = (font, name)
    return _FONT_CACHE[key]


# ---------------------------------------------------------------- 背景工具

def draw_paper(surface, step=64):
    """纸底 + 极淡方格，场景背景统一用它。横竖都要画，只画竖线会像条纹纸。"""
    surface.fill(config.COLOR_PAPER)
    for x in range(0, config.WIDTH, step):
        pygame.draw.line(surface, config.COLOR_PAPER_LINE, (x, 0), (x, config.HEIGHT))
    for y in range(0, config.HEIGHT, step):
        pygame.draw.line(surface, config.COLOR_PAPER_LINE, (0, y), (config.WIDTH, y))


def draw_sketch_underline(surface, x1, x2, y, color=None, amp=1.6, width=3):
    """手绘感横线：用正弦扰动代替笔直直线，避免看起来像表格边框。"""
    color = color or config.COLOR_INK
    pts = []
    for x in range(int(x1), int(x2) + 1, 6):
        pts.append((x, int(y + amp * ((x // 6) % 2 * 2 - 1))))
    if len(pts) >= 2:
        pygame.draw.lines(surface, color, False, pts, width)


def draw_stick_figure(surface, x, ground_y, scale=1.0, color=None):
    """代码画一个站立的火柴人，M2 灰盒阶段的占位形象。

    不读任何素材，所以 M1 可以完全脱离图片运行。
    (x, ground_y) 为脚底中心点。
    """
    color = color or config.COLOR_INK
    s = scale
    # 总高必须等于 Player.HEIGHT（70），否则头顶会戳出红色判定框
    head_r = int(10 * s)
    head_cy = ground_y - int(60 * s)
    # 头
    pygame.draw.circle(surface, color, (int(x), head_cy), head_r, max(2, int(3 * s)))
    # 躯干
    neck_y = head_cy + head_r
    hip_y = ground_y - int(28 * s)
    pygame.draw.line(surface, color, (int(x), neck_y), (int(x), hip_y), max(2, int(3 * s)))
    # 手臂。跨度必须小于碰撞盒宽度（26），否则手臂会伸到红色判定框外面，
    # 看起来像"判定比人还窄"，容易误判手感。
    shoulder_y = neck_y + int(8 * s)
    pygame.draw.line(surface, color, (int(x - 11 * s), shoulder_y + int(9 * s)),
                     (int(x), shoulder_y), max(2, int(3 * s)))
    pygame.draw.line(surface, color, (int(x), shoulder_y),
                     (int(x + 11 * s), shoulder_y + int(9 * s)), max(2, int(3 * s)))
    # 腿
    pygame.draw.line(surface, color, (int(x), hip_y),
                     (int(x - 11 * s), ground_y), max(2, int(3 * s)))
    pygame.draw.line(surface, color, (int(x), hip_y),
                     (int(x + 11 * s), ground_y), max(2, int(3 * s)))


# ---------------------------------------------------------------- 场景基类

class Scene(object):
    """所有场景的基类。只声明接口，不做任何事。"""

    name = ""

    def __init__(self, app):
        self.app = app

    def on_enter(self):
        """进入场景时调用一次，适合在这里生成静态背景缓存。"""

    def on_exit(self):
        """离开场景时调用一次，适合释放缓存。"""

    def handle_event(self, event):
        """处理单个事件。"""

    def update(self, dt):
        """固定步长更新，dt 恒为 config.FIXED_DT。"""

    def draw(self, surface):
        """只负责画，不修改状态。"""


# ---------------------------------------------------------------- 场景管理

class SceneManager(object):
    """持有当前场景，负责注册与延迟切换。

    切换为什么延迟：场景在 handle_event 里调用 goto() 时，自己正在执行，
    立即替换会让这一帧后续代码作用在已销毁的对象上。
    """

    def __init__(self, app):
        self.app = app
        self._registry = {}
        self._current = None
        self._current_name = ""
        self._pending = None
        self.switch_count = 0

    def register(self, name, scene_cls):
        self._registry[name] = scene_cls

    def start(self, name):
        """立即进入某个场景，用于程序启动。"""
        self._pending = name
        self.apply_pending()

    def goto(self, name):
        """请求切换，在帧末生效。"""
        if name not in self._registry:
            raise KeyError("场景未注册：%s（已注册：%s）"
                           % (name, ", ".join(sorted(self._registry))))
        self._pending = name

    def apply_pending(self):
        if self._pending is None:
            return
        name = self._pending
        self._pending = None
        if self._current is not None:
            self._current.on_exit()
        self._current = self._registry[name](self.app)
        self._current_name = name
        self._current.on_enter()
        self.switch_count += 1

    @property
    def current(self):
        return self._current

    @property
    def current_name(self):
        return self._current_name

    # ---- 主循环调用的三个入口 ----
    def handle_events(self, events):
        for event in events:
            if event.type == pygame.QUIT:
                self.app.quit()
                return
            if self._current is not None:
                self._current.handle_event(event)
        self.apply_pending()

    def update(self, dt):
        if self._current is not None:
            self._current.update(dt)
        self.apply_pending()

    def draw(self, surface):
        if self._current is not None:
            self._current.draw(surface)


# ---------------------------------------------------------------- 菜单场景

class MenuScene(Scene):
    """主菜单。M1 只有"开始游戏"和"退出游戏"两项。"""

    name = "menu"
    ITEMS = [("开始游戏", "game"), ("退出游戏", "quit")]

    TITLE_SIZE = 64
    ITEM_SIZE = 28

    def __init__(self, app):
        Scene.__init__(self, app)
        self.index = 0
        self._bg = None
        self._item_rects = []

    def on_enter(self):
        self.index = 0
        self._bg = self._build_background()
        self._item_rects = self._build_item_rects()

    def on_exit(self):
        self._bg = None

    def _build_background(self):
        """标题与纸底是静态的，渲染一次缓存起来，每帧只 blit。"""
        bg = pygame.Surface((config.WIDTH, config.HEIGHT))
        draw_paper(bg)

        f_title, _ = get_font(self.TITLE_SIZE, bold=True)
        f_sub, _ = get_font(20)

        title = "火柴人跑酷"
        tw = f_title.size(title)[0]
        tx = (config.WIDTH - tw) // 2
        bg.blit(f_title.render(title, True, config.COLOR_INK), (tx, 108))
        draw_sketch_underline(bg, tx + 6, tx + tw - 6, 186)

        sub = "STICK FIGURE PARKOUR"
        sw = f_sub.size(sub)[0]
        bg.blit(f_sub.render(sub, True, config.COLOR_MUTED),
                ((config.WIDTH - sw) // 2, 200))
        return bg

    def _build_item_rects(self):
        """计算每个菜单项的可点击区域，鼠标与键盘共用同一套坐标。"""
        rects = []
        f_name, _ = get_font(self.ITEM_SIZE)
        top = 300
        gap = 74
        for i, (label, _) in enumerate(self.ITEMS):
            w = f_name.size(label)[0] + 120
            h = 54
            rects.append(pygame.Rect((config.WIDTH - w) // 2, top + i * gap, w, h))
        return rects

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self.index = (self.index - 1) % len(self.ITEMS)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.index = (self.index + 1) % len(self.ITEMS)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._activate()
            elif event.key == pygame.K_ESCAPE:
                self.app.quit()
        elif event.type == pygame.MOUSEMOTION:
            self._hover(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._hover(event.pos):
                self._activate()

    def _hover(self, pos):
        for i, rect in enumerate(self._item_rects):
            if rect.collidepoint(pos):
                self.index = i
                return True
        return False

    def _activate(self):
        label, action = self.ITEMS[self.index]
        if action == "quit":
            self.app.quit()
        else:
            self.app.scenes.goto(action)

    def draw(self, surface):
        surface.blit(self._bg, (0, 0))
        f_item, _ = get_font(self.ITEM_SIZE)
        f_hint, _ = get_font(17)

        for i, (label, _) in enumerate(self.ITEMS):
            rect = self._item_rects[i]
            selected = (i == self.index)
            if selected:
                # 选中项：虚线圆角框 + 左侧手绘箭头
                compat.rounded_rect(surface, config.COLOR_INK, rect, radius=12, width=3)
                ax = rect.left - 34
                ay = rect.centery
                pygame.draw.lines(surface, config.COLOR_INK, False,
                                  [(ax - 10, ay - 9), (ax, ay), (ax - 10, ay + 9)], 3)
            color = config.COLOR_INK if selected else config.COLOR_MUTED
            text = f_item.render(label, True, color)
            surface.blit(text, (rect.centerx - text.get_width() // 2,
                                rect.centery - text.get_height() // 2))

        hint = u"↑↓ 选择    Enter 确定    Esc 退出"
        hw = f_hint.size(hint)[0]
        surface.blit(f_hint.render(hint, True, config.COLOR_MUTED),
                     ((config.WIDTH - hw) // 2, config.HEIGHT - 56))


# ---------------------------------------------------------------- 游戏场景

class GameScene(Scene):
    """M2：灰盒地形 + 玩家物理 + 调试显示。

    M3 会把 _build_solids() 换成 levels/l1.txt 的解析结果；
    在那之前这里的地形是硬编码的，只为验收物理。
    """

    name = "game"
    GROUND_TOP = 460

    def __init__(self, app):
        Scene.__init__(self, app)
        self.player = None
        self.solids = []
        self.input = player.InputState()
        self.show_debug = True
        self._focused = True
        self._bg = None

    def on_enter(self):
        self.solids = self._build_solids()
        self.player = player.Player(80, self.GROUND_TOP - player.Player.HEIGHT)
        self.input = player.InputState()
        self.show_debug = True
        self._focused = True
        self._bg = pygame.Surface((config.WIDTH, config.HEIGHT))
        draw_paper(self._bg)

    def on_exit(self):
        self._bg = None

    def _build_solids(self):
        """M2 验收用地形：地面 + 三个可跳上的平台 + 一堵堵路矮墙 + 高台。

        矮墙高 80px，而跳跃高度约 126px，所以撞得到也跳得过——
        既能验收"不能穿墙"，又不会把玩家困死。
        """
        return [
            pygame.Rect(0, self.GROUND_TOP, config.WIDTH, config.HEIGHT - self.GROUND_TOP),
            pygame.Rect(170, 380, 140, 20),
            pygame.Rect(380, 330, 140, 20),
            pygame.Rect(600, 380, 140, 20),
            pygame.Rect(760, 380, 26, 80),
            pygame.Rect(850, 290, 100, 20),
        ]

    # ---- 输入 ----
    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.app.scenes.goto("menu")
                return
            if event.key == pygame.K_SPACE:
                self.input.jump_pressed = True
                self.input.jump_held = True
            elif event.key == pygame.K_F1:
                self.show_debug = not self.show_debug
        elif event.type == pygame.KEYUP:
            if event.key == pygame.K_SPACE:
                self.input.jump_released = True
                self.input.jump_held = False

        # 失焦必须清空输入，否则回来时角色会一直往一个方向跑
        if compat.focus_lost(event):
            self._focused = False
            self.input.release_edges()
            self.input.jump_held = False
            if self.player is not None:
                self.player.vx = 0.0
        elif compat.focus_gained(event):
            self._focused = True

    def update(self, dt):
        if self._focused:
            keys = pygame.key.get_pressed()
            axis = 0.0
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                axis -= 1.0
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                axis += 1.0
            self.input.axis = axis
        else:
            self.input.axis = 0.0

        self.player.update(dt, self.input, self.solids)

        # 掉出画面先做最简处理，M4 才接正式死亡流程
        if self.player.y > config.HEIGHT + 160:
            self.player.reset()

    def draw(self, surface):
        surface.blit(self._bg, (0, 0))
        self._draw_solids(surface)

        p = self.player
        draw_stick_figure(surface, p.rect.centerx, p.rect.bottom)

        if self.show_debug:
            self._draw_debug(surface)

        f_hint, _ = get_font(16)
        hint = u"← → / A D 移动     空格 跳跃     F1 调试     Esc 返回菜单"
        surface.blit(f_hint.render(hint, True, config.COLOR_MUTED),
                     (24, config.HEIGHT - 28))

    def _draw_solids(self, surface):
        for s in self.solids:
            pygame.draw.rect(surface, config.COLOR_GROUND, s)
            pygame.draw.rect(surface, config.COLOR_INK, s, 2)

    def _draw_debug(self, surface):
        f, _ = get_font(15)
        lines = self.player.debug_lines()
        box = pygame.Rect(16, 14, 340, 16 + 20 * len(lines))
        pygame.draw.rect(surface, (255, 255, 255), box)
        pygame.draw.rect(surface, config.COLOR_INK, box, 2)
        for i, line in enumerate(lines):
            surface.blit(f.render(line, True, config.COLOR_INK),
                         (box.left + 10, box.top + 8 + i * 20))
        # 碰撞盒线框：红色细线，用来核对视觉与判定是否一致
        pygame.draw.rect(surface, (200, 60, 60), self.player.rect, 1)
