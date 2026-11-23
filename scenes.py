# -*- coding: utf-8 -*-
"""场景系统：Scene 基类、SceneManager、菜单场景与游戏场景。

M1 定下的边界（README §19 M1）：
  - 窗口只在 main.py 创建一次，场景**只接收 surface**，绝不调用 set_mode
  - 场景切换延迟到帧末执行，避免在事件循环中途替换自身导致状态错乱
  - 素材缺失时必须能退回纯代码绘制，不能因为少一张图就打不开

M2.5 起游戏场景接入角色贴图动画，但保留 draw_stick_figure 作为降级路径。

两个永不改变的接口：
  Scene.handle_event / update / draw
  SceneManager.register / start / goto
"""

import os

import pygame

import assets
import compat
import config
import player
import world

# ---------------------------------------------------------------- 字体


def get_font(size, bold=False):
    """按文件路径探测中文字体，带缓存。

    返回 (font, 字体文件名)，文件名用于启动日志。
    实际探测逻辑已迁到 assets.font，这里只做转发，避免两处各存一份缓存。
    """
    return assets.font(size, bold)


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
    """M3：关卡文件 + 相机跟随 + 基础 HUD。

    地形、出生点、终点、金币全部来自 levels/*.txt，代码里不再硬编码任何
    关卡数据。这样可以只改文本就调整关卡，也为 M6 多关卡铺好路。
    """

    name = "game"

    def __init__(self, app):
        Scene.__init__(self, app)
        self.player = None
        self.world = None
        self.camera = None
        self.input = player.InputState()
        self.show_debug = True
        self._focused = True
        self.sprites = None       # assets.HeroSprites；None 表示退回代码绘制
        self.sprite_error = ""
        self.load_error = ""
        self.goal_reached = False
        self.level_time = 0.0
        self.deaths = 0           # M4 接正式死亡流程前只在调试里显示
        self._hud_bg = None
        # 非 None 时屏蔽键盘、直接采用这个轴值。
        # 无头截图和以后的录像回放都依赖它——否则 update() 每帧都会用
        # key.get_pressed() 覆盖外部写入的输入，自动化根本驱动不了角色。
        self.override_axis = None

    # ---------------------------------------------------------------- 生命周期
    def on_enter(self):
        self.input = player.InputState()
        self.show_debug = True
        self._focused = True
        self.override_axis = None
        self.load_level(config.DEFAULT_LEVEL)
        self._load_sprites()
        self._build_hud()

    def load_level(self, path):
        """加载关卡。失败时把错误留在 self.load_error 里，画面显示出来。

        关卡写错不该直接崩掉整个程序——玩家（或我自己）改图改错一个字符，
        更希望看到「l1.txt:12:5 未知字符」而不是一个 traceback。
        """
        self.world = None
        self.player = None
        self.camera = None
        self.goal_reached = False
        self.level_time = 0.0
        self.load_error = ""
        try:
            self.world = world.World.load(path)
        except world.LevelError as exc:
            self.load_error = str(exc)
            print(u" 关卡加载失败：\n%s" % exc.describe())
            return False
        except Exception as exc:                      # 兜底，避免整程序退出
            self.load_error = u"%s: %s" % (os.path.basename(path), exc)
            print(u" 关卡加载失败：%s" % self.load_error)
            return False

        print(u" 关卡     : %s" % self.world.describe())
        self.player = player.Player(*self.world.spawn)
        self.camera = world.Camera((config.WIDTH, config.HEIGHT),
                                   self.world.bounds)
        self.camera.snap_to(self.player.rect)
        return True

    def _load_sprites(self):
        """加载角色贴图。失败不抛，退回代码绘制——M1 定下的底线不能破。"""
        if self.sprites is not None:
            return
        try:
            self.sprites = assets.load_hero()
            print(u" 角色贴图 : %s" % self.sprites.describe())
        except assets.AssetMissing as exc:
            self.sprites = None
            self.sprite_error = str(exc)
            print(u" 角色贴图 : 缺失，退回代码绘制（%s）" % exc)

    def _build_hud(self):
        """HUD 底板只画一次。

        compat.panel 内部是 2 倍超采样抗锯齿，实测 0.75ms/次，
        每帧画两个就是 1.5ms——比整个地形渲染还贵。所以固化到一张图上。
        """
        surf = pygame.Surface((config.WIDTH, config.HEIGHT), pygame.SRCALPHA)
        left = pygame.Rect(16, 14, 240, 62)
        compat.panel(surf, left, radius=14, fill=(255, 255, 255),
                     border=config.COLOR_INK, width=2)
        right = pygame.Rect(config.WIDTH - 156, 14, 140, 42)
        compat.panel(surf, right, radius=14, fill=(255, 255, 255),
                     border=config.COLOR_INK, width=2)
        self._hud_bg = surf

    def on_exit(self):
        pass

    # ---------------------------------------------------------------- 输入
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
            elif event.key == pygame.K_r:
                # 重开本关：M7 会挂到正式 UI 上，现在先给个快捷键方便调试
                self.on_enter()
            elif event.key == pygame.K_RETURN and self.goal_reached:
                self.on_enter()
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

    def _poll_axis(self):
        if self.override_axis is not None:
            self.input.axis = self.override_axis
            return
        if not self._focused:
            self.input.axis = 0.0
            return
        keys = pygame.key.get_pressed()
        axis = 0.0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            axis -= 1.0
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            axis += 1.0
        self.input.axis = axis

    # ---------------------------------------------------------------- 更新
    def update(self, dt):
        if self.world is None or self.player is None:
            return

        self._poll_axis()
        self.world.update(dt)

        if self.goal_reached:
            # 到终点后冻结角色，但仍让输入边沿自然衰减，避免重开时残留按键
            self.input.release_edges()
            return

        self.level_time += dt
        self.player.update(dt, self.input, self.world.solids)
        self.world.collect(self.player.rect)
        self.camera.update(dt, self.player.rect)

        # 掉出地图：M3 先做最简回出生点，保证坑里不会无限下坠。
        # M4 会换成统一的死亡流程（死亡计数、篝火重生、短暂无敌）。
        if self.player.y > self.world.bounds.bottom + 120:
            self.respawn()

        if self.player.rect.colliderect(self.world.goal_rect):
            self.goal_reached = True
            self.input.release_edges()
            print(u" 到达终点：%.1fs，金币 %d/%d" % (
                self.level_time, self.world.taken_coins, self.world.total_coins))

    def respawn(self):
        self.player.reset()
        if self.camera is not None:
            self.camera.snap_to(self.player.rect)

    # ---------------------------------------------------------------- 绘制
    def draw(self, surface):
        surface.fill(config.COLOR_PAPER)

        if self.world is None:
            self._draw_load_error(surface)
            return

        self.world.draw(surface, self.camera)
        self._draw_player(surface)
        self._draw_hud(surface)

        if self.show_debug:
            self._draw_debug(surface)

        f_hint, _ = get_font(16)
        hint = u"← → / A D 移动     空格 跳跃     R 重开     F1 调试     Esc 返回菜单"
        w = f_hint.size(hint)[0]
        surface.blit(f_hint.render(hint, True, config.COLOR_MUTED),
                     ((config.WIDTH - w) // 2, config.HEIGHT - 26))

        if self.goal_reached:
            self._draw_goal_panel(surface)

    def _draw_player(self, surface):
        """画角色：优先贴图动画，素材缺失时退回代码火柴人。

        锚点约定（见 assets.HeroSprites 文档）：
          水平 画布中心 -> 碰撞盒中心
          竖直 内容底边 -> 碰撞盒底边
        再叠加落地瞬间的整体下沉，做出"踩实"的反馈。
        世界坐标经 camera.offset 平移到屏幕坐标。
        """
        p = self.player
        ox, oy = self.camera.offset
        if self.sprites is None:
            draw_stick_figure(surface, p.rect.centerx + ox, p.rect.bottom + oy)
            return

        count = self.sprites.frame_count(p.anim_state, p.facing)
        idx = p.anim_frame % count
        img = self.sprites.frame(p.anim_state, p.facing, idx)
        x, y = self.sprites.blit_pos(p.rect.centerx,
                                     p.rect.bottom + int(round(p.land_sink)),
                                     p.anim_state, p.facing, idx)
        surface.blit(img, (x + ox, y + oy))

    def _level_title(self):
        name = self.world.name if self.world else ""
        if len(name) > 1 and name[0] == "l" and name[1:].isdigit():
            return u"第 %d 关" % int(name[1:])
        return name or u"关卡"

    def _draw_hud(self, surface):
        surface.blit(self._hud_bg, (0, 0))
        f, _ = get_font(19, bold=True)
        f_small, _ = get_font(15)
        surface.blit(f.render(self._level_title(), True, config.COLOR_INK), (30, 22))
        coins = u"金币 %d / %d" % (self.world.taken_coins, self.world.total_coins)
        surface.blit(f_small.render(coins, True, config.COLOR_MUTED), (30, 48))

        t = u"%05.1f s" % self.level_time
        tw = f_small.size(t)[0]
        surface.blit(f_small.render(t, True, config.COLOR_INK),
                     (config.WIDTH - 30 - tw, 27))

    def _draw_goal_panel(self, surface):
        box = pygame.Rect(0, 0, 420, 190)
        box.center = (config.WIDTH // 2, config.HEIGHT // 2 - 10)
        veil = pygame.Surface((config.WIDTH, config.HEIGHT), pygame.SRCALPHA)
        veil.fill((250, 247, 238, 190))
        surface.blit(veil, (0, 0))
        compat.panel(surface, box, radius=18, fill=(255, 255, 255),
                     border=config.COLOR_INK, width=3)

        f_big, _ = get_font(34, bold=True)
        f, _ = get_font(18)
        lines = [
            (u"到达终点", f_big, config.COLOR_INK),
            (u"用时 %.1f 秒    金币 %d / %d" % (self.level_time,
                                              self.world.taken_coins,
                                              self.world.total_coins),
             f, config.COLOR_MUTED),
            (u"Enter 重来    Esc 返回菜单", f, config.COLOR_MUTED),
        ]
        y = box.top + 26
        for text, font_obj, color in lines:
            img = font_obj.render(text, True, color)
            surface.blit(img, (box.centerx - img.get_width() // 2, y))
            y += img.get_height() + 16

    def _draw_load_error(self, surface):
        box = pygame.Rect(0, 0, 700, 260)
        box.center = (config.WIDTH // 2, config.HEIGHT // 2)
        compat.panel(surface, box, radius=18, fill=(255, 255, 255),
                     border=config.COLOR_INK, width=3)

        f_big, _ = get_font(26, bold=True)
        f, _ = get_font(16)
        surface.blit(f_big.render(u"关卡文件有问题", True, config.COLOR_INK),
                     (box.left + 26, box.top + 20))
        y = box.top + 66
        for line in self.load_error.splitlines():
            img = f.render(line, True, config.COLOR_MUTED)
            surface.blit(img, (box.left + 26, y))
            y += img.get_height() + 4
        tip = f.render(u"Esc 返回菜单", True, config.COLOR_MUTED)
        surface.blit(tip, (box.left + 26, box.bottom - 34))

    def _draw_debug(self, surface):
        f, _ = get_font(15)
        lines = self.player.debug_lines()
        cam = self.camera
        lines.append("cam  %.1f, %.1f  off %s"
                     % (cam.x, cam.y, cam.offset))
        box = pygame.Rect(16, 88, 380, 16 + 20 * len(lines))
        pygame.draw.rect(surface, (255, 255, 255), box)
        pygame.draw.rect(surface, config.COLOR_INK, box, 2)
        for i, line in enumerate(lines):
            surface.blit(f.render(line, True, config.COLOR_INK),
                         (box.left + 10, box.top + 8 + i * 20))
        # 碰撞盒线框：红色细线，用来核对视觉与判定是否一致
        pygame.draw.rect(surface, (200, 60, 60),
                         self.camera.apply(self.player.rect), 1)
        # 终点判定格：绿色细线，核对终点位置是否与旗子对齐
        pygame.draw.rect(surface, (60, 150, 90),
                         self.camera.apply(self.world.goal_rect), 1)
