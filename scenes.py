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

import math
import os

import pygame

import assets
import compat
import config
import dialog
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
    """M4：关卡文件 + 相机跟随 + HUD + 死亡流程 + 篝火 + 机关。

    地形、出生点、终点、金币、机关全部来自 levels/*.txt，代码里不再硬编码
    任何关卡数据。这样可以只改文本就调整关卡，也为 M6 多关卡铺好路。
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
        self.level_path = getattr(app, "level_path", None) or config.DEFAULT_LEVEL
        self.goal_reached = False
        self.level_time = 0.0
        self._hud_bg = None
        # 非 None 时屏蔽键盘、直接采用这个轴值。
        # 无头截图和以后的录像回放都依赖它——否则 update() 每帧都会用
        # key.get_pressed() 覆盖外部写入的输入，自动化根本驱动不了角色。
        self.override_axis = None

        # ---- 死亡与检查点（M4）----
        self.deaths = 0
        self.death_timer = 0.0        # >0 表示正在死亡定格
        self.invuln = 0.0             # 重生后的短暂无敌
        self.checkpoint = None        # 当前重生点 (x, y)；None 表示回出生点
        self.checkpoint_index = -1
        self.last_death_cause = ""
        self.respawn_count = 0        # 自检用：真正发生了几次重生

        # ---- 道具提示（M5）----
        # 捡到伞的时候只弹一次提示，2.6 秒后自己消失。做成一闪而过的横幅，
        # 而不是需要按键关掉的弹窗：捡道具不该打断跑动。
        self.toast_text = ""
        self.toast_timer = 0.0

        # ---- 对话（M6）----
        # 非 None 时整局暂停：物理、敌人、计时全部冻结，只留对话自己的
        # 呼吸动画。读字的时候还在被打、还在计时，是最容易被骂的设计。
        self.dialog = None
        self._dlg_font = None
        self._dlg_body = None

    # ---------------------------------------------------------------- 生命周期
    def on_enter(self):
        self.input = player.InputState()
        self.show_debug = True
        self._focused = True
        self.override_axis = None
        self._reset_stats()
        self.load_level(self.level_path)
        self._load_sprites()
        self._build_hud()

    def _reset_stats(self):
        self.deaths = 0
        self.death_timer = 0.0
        self.invuln = 0.0
        self.checkpoint = None
        self.checkpoint_index = -1
        self.last_death_cause = ""
        self.respawn_count = 0
        self.level_time = 0.0
        self.toast_text = ""
        self.toast_timer = 0.0
        self.dialog = None

    def load_level(self, path):
        """加载关卡。失败时把错误留在 self.load_error 里，画面显示出来。

        关卡写错不该直接崩掉整个程序——玩家（或我自己）改图改错一个字符，
        更希望看到「l1.txt:12:5 未知字符」而不是一个 traceback。
        """
        self.world = None
        self.player = None
        self.camera = None
        self.goal_reached = False
        self.load_error = ""
        self.level_path = path
        # 换关 = 从头开始：死亡定格、检查点、统计都得清掉。少了这一句，
        # 上一关死在一半时切关，新关会带着旧关的死亡定格（开头冻半秒）
        # 和旧关的检查点开跑——_respawn 甚至会把角色传回上一关的坐标。
        self._reset_stats()
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

    def restart(self):
        """重开本关：保留已烘焙的地形，只复位运行期状态。

        直接重新 load 一次也没错，但烘焙 2816x576 的地形要几十毫秒，
        按 R 会看到明显停顿。地形是不变的，没必要重画。
        """
        if self.world is None:
            return self.load_level(self.level_path)
        self._reset_stats()
        self.world.reset_runtime()
        self.goal_reached = False
        self.player = player.Player(*self.world.spawn)
        self.camera.snap_to(self.player.rect)
        self.input = player.InputState()
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
        # 左面板留出四行：关卡名 / 金币与死亡 / 冲刺冷却条 / 道具栏（M5 加的）
        left = pygame.Rect(16, 14, 240, 112)
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
            # 对话打开时，除 E / Esc 之外的按键全部吞掉。不吞的话玩家会在
            # 读字时按空格把角色跳走，回来发现人已经在坑里了。
            if self.dialog is not None:
                if event.key in (pygame.K_e, pygame.K_RETURN, pygame.K_SPACE):
                    self._advance_dialog()
                elif event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                    self.dialog = None
                return

            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.app.scenes.goto("menu")
                return
            if event.key == pygame.K_e:
                self._try_interact()
            elif event.key == pygame.K_SPACE:
                self.input.jump_pressed = True
                self.input.jump_held = True
            elif event.key in (pygame.K_LSHIFT, pygame.K_RSHIFT):
                self.input.dash_pressed = True
            elif event.key == pygame.K_F1:
                self.show_debug = not self.show_debug
            elif event.key == pygame.K_r:
                self.restart()
            elif event.key == pygame.K_t:
                self.go_to_checkpoint()
            elif event.key == pygame.K_n:
                self.next_level()
            elif event.key == pygame.K_RETURN and self.goal_reached:
                self.restart()
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

    def next_level(self):
        """N 键切到下一个关卡文件。

        M6 才做正式的选关界面；这里先给一个循环切换，是因为 M4 的机关
        （篝火/地刺/弹跳板/移动平台）全在 l2 里，没有它就只能改代码试玩。
        """
        try:
            names = sorted(n for n in os.listdir(config.LEVEL_DIR)
                           if n.endswith(".txt"))
        except OSError:
            return False
        if len(names) < 2:
            return False
        cur = os.path.basename(self.level_path)
        i = names.index(cur) if cur in names else -1
        self.level_path = os.path.join(config.LEVEL_DIR, names[(i + 1) % len(names)])
        self._reset_stats()
        self.load_level(self.level_path)
        return True

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

    # ---------------------------------------------------------------- 对话
    def _try_interact(self):
        """E 键：打开脚下那块牌子 / 旁边那个人的对话框。"""
        if self.world is None or self.player is None:
            return False
        info = self.world.interact()
        if info is None:
            return False
        name, pages, kind = info
        if self._dlg_font is None:
            self._dlg_font, _ = get_font(19, bold=True)
            self._dlg_body, _ = get_font(21)
        self.dialog = dialog.Dialog(name, pages, kind)
        # 打开对话瞬间清速度：关掉之后不该带着"进场时的惯性"继续跑
        self.player.vx = 0.0
        self.input.release_edges()
        self.input.jump_held = False
        return True

    def _advance_dialog(self):
        if self.dialog is None:
            return False
        if not self.dialog.advance():
            self.dialog = None
        return True

    def _dialog_tail(self):
        """气泡尾巴指向屏幕上的交互对象（对象头顶的屏幕坐标）。"""
        if self.world is None or self.world.focus is None:
            return None
        obj = self.world.focus
        ox, oy = self.camera.offset
        head = 6 if obj["kind"] == "npc" else 10   # NPC 有帽子，再高一点
        return (obj["cell"].centerx + ox, obj["cell"].top + oy + head)

    # ---------------------------------------------------------------- 更新
    def update(self, dt):
        if self.world is None or self.player is None:
            return

        # 对话中整局暂停：只推进对话框自己的动画。物理、敌人、落石、计时器
        # 全部冻结——"读字的时候被石头砸死"是最没道理的一种死法。
        if self.dialog is not None:
            self.dialog.update(dt)
            self.input.release_edges()
            self.input.jump_held = False
            self.player.vx = 0.0
            return

        self._poll_axis()
        # 平台先动一步：玩家这一帧要撞的是平台的**新**位置，
        # 否则站在平台前沿时会被追尾，表现为每帧一次的小顿挫。
        self.world.update(dt, self.player)
        if self.toast_timer > 0.0:
            self.toast_timer = max(0.0, self.toast_timer - dt)

        # 死亡定格：角色不再受物理控制，也不再计时。
        # 不在这里 return 掉 world.update 是故意的——平台继续走，
        # 画面不会僵住，玩家能看清"我是在哪个机关上死的"。
        if self.death_timer > 0.0:
            self.death_timer = max(0.0, self.death_timer - dt)
            self.input.release_edges()
            if self.death_timer <= 0.0:
                self._respawn()
            return

        if self.goal_reached:
            # 到终点后冻结角色，但仍让输入边沿自然衰减，避免重开时残留按键
            self.input.release_edges()
            return

        self.level_time += dt
        if self.invuln > 0.0:
            self.invuln = max(0.0, self.invuln - dt)

        self._apply_platform_carry()
        self.player.update(dt, self.input, self.world.collision_solids(),
                           oneways=self.world.oneways,
                           bouncers=self.world.bouncers)
        self._post_physics()
        self.camera.update(dt, self.player.rect)

    def _apply_platform_carry(self):
        """站着的平台动了，玩家跟着走。

        先水平后垂直，和 _move_horizontal/_move_vertical 里的顺序保持一致。
        用平台自己算出的整数 delta，而不是"速度 × dt"：这样平台和玩家的
        位置差永远不超过 1px，不会出现慢慢累积的半像素偏移。
        """
        p = self.player
        if not p.on_ground:
            return
        plat = self.world.carrying_platform(p)
        if plat is None:
            return
        dx, dy = plat.delta
        if dx or dy:
            p.carry(dx, dy, self.world.solids)

    def _post_physics(self):
        """物理之后的一次性判定：死亡、篝火、金币、终点。

        顺序有讲究：先判死亡再判篝火。玩家可能正好被弹进篝火旁的刺里，
        这时应该死，不该顺手点亮一盏离他很远的篝火。
        """
        p = self.player
        rect = p.rect

        # 掉出地图底部：坑没接住，等同于死亡
        if rect.top > self.world.bounds.bottom:
            self.die(u"掉出了地图")
            return

        if self.invuln <= 0.0:
            ch = self.world.hazard_at(rect)
            if ch is not None:
                self.die({"^": u"踩到地刺", "v": u"撞到天花板刺",
                          "~": u"落水"}.get(ch, u"碰到危险格"))
                return
            # 会动的机关在静态危险格之后、敌人之前：踩到刺上同时被刀片扫到，
            # 报"踩到地刺"更符合玩家看到的因果。
            mech = self.world.mechanism_hit(rect)
            if mech is not None:
                self.die(mech)
                return
            # 踩怪必须判在"被怪撞到"之前：踩中的那一帧脚底一定和判定框相交，
            # 先判死就永远踩不下去，玩家只会觉得"这怪根本踩不了"。
            stomped = self.world.stomp(p)
            if stomped is not None and stomped.stomp():
                p.stomp_bounce()
                self.toast(u"踩掉了走地怪", 1.2)
            # 敌人判定放在危险格之后：踩刺而死比"恰好和蝙蝠重叠"更该被报告，
            # 玩家也更认这个因果。
            hit = self.world.enemy_hit(rect)
            if hit is not None:
                self.die(hit)
                return

        idx = self.world.checkpoint_hit(rect)
        if idx >= 0:
            # 只允许往关卡后面点亮：回头看老篝火时不该把重生点往回挪
            if idx > self.checkpoint_index:
                cp = self.world.checkpoints[idx]
                cp["active"] = True
                self.checkpoint = cp["spawn"]
                self.checkpoint_index = idx
                print(u" 检查点   : 第 %d 个篝火点亮，重生点 (%.0f, %.0f)"
                      % (idx + 1, cp["spawn"][0], cp["spawn"][1]))

        self.world.collect(rect)

        # 道具拾取：拿到伞只提示一次，重复踩同一格不会反复弹横幅。
        for item in self.world.collect_items(rect):
            if item == "glider" and p.pick_glider():
                self.toast(u"获得滑翔伞：空中按住空格可以滑翔", 2.6)
                print(u" 道具     : 获得滑翔伞（空中按住空格滑翔）")

        if rect.colliderect(self.world.goal_zone) and not self.goal_reached:
            self.goal_reached = True
            self.input.release_edges()
            print(u" 到达终点：%.1fs，金币 %d/%d，死亡 %d 次" % (
                self.level_time, self.world.taken_coins,
                self.world.total_coins, self.deaths))

    # ---------------------------------------------------------------- 提示
    def toast(self, text, seconds=2.0):
        """画面顶部弹一条短提示，自己消失。捡道具这类事件不该打断跑动。"""
        self.toast_text = text
        self.toast_timer = seconds

    # ---------------------------------------------------------------- 死亡与重生
    def die(self, cause=u"死亡"):
        """进入死亡流程。重复调用被 death_timer 挡掉，死亡数只加一次。"""
        if self.death_timer > 0.0 or self.goal_reached:
            return
        self.deaths += 1
        self.last_death_cause = cause
        self.death_timer = config.DEATH_FREEZE
        self.player.vx = 0.0
        self.player.vy = 0.0
        self.player.dash_time = 0.0
        # 死亡定格期间 update 不再跑物理，gliding 不会自己归零，
        # 不清掉的话死亡画面里伞还撑在头顶上。
        self.player.gliding = False
        self.input.release_edges()

    def _respawn(self):
        """按当前重生点复活。检查点优先，没点过篝火就回出生点。"""
        if self.checkpoint is not None:
            x, y = self.checkpoint
        else:
            x, y = self.world.spawn
        self.player.teleport(x, y)
        self.invuln = config.INVULN_TIME
        self.respawn_count += 1
        self.camera.snap_to(self.player.rect)

    def go_to_checkpoint(self):
        """T 键：主动回检查点。刻意不算死亡——这是读档不是送死。"""
        if self.world is None or self.goal_reached:
            return False
        if self.checkpoint is None:
            # 还没点篝火。回出生点也算"回到上一个安全位置"，但不计死亡
            x, y = self.world.spawn
        else:
            x, y = self.checkpoint
        self.death_timer = 0.0
        self.player.teleport(x, y)
        self.invuln = config.INVULN_TIME
        self.camera.snap_to(self.player.rect)
        return True

    # ---------------------------------------------------------------- 绘制
    def draw(self, surface):
        surface.fill(config.COLOR_PAPER)

        if self.world is None:
            self._draw_load_error(surface)
            return

        self.world.draw(surface, self.camera, show_prompt=self.dialog is None)
        self._draw_player(surface)
        self._draw_hud(surface)

        if self.show_debug and self.death_timer <= 0.0:
            self._draw_debug(surface)

        # 提示条放在调试面板之后：它只在捡到道具那 2 秒出现，
        # 被压在面板下面就等于没提示。
        if self.toast_timer > 0.0 and self.toast_text:
            self._draw_toast(surface)

        # 按键提示条只在没有对话时画：对话面板就压在它上面，
        # 半截被盖住的灰字看着像渲染坏了。
        if self.dialog is None:
            f_hint, _ = get_font(16)
            hint = (u"← → / A D 移动   空格 跳跃（空中按住 滑翔）   Shift 冲刺   "
                    u"E 看牌子 / 对话   T 回检查点   R 重开   N 切关   F1 调试   Esc 菜单")
            w = f_hint.size(hint)[0]
            surface.blit(f_hint.render(hint, True, config.COLOR_MUTED),
                         ((config.WIDTH - w) // 2, config.HEIGHT - 26))

        if self.death_timer > 0.0:
            self._draw_death_panel(surface)
        elif self.goal_reached:
            self._draw_goal_panel(surface)

        # 对话框永远在最上层：它出现时整局已暂停，被 HUD 压住就等于没打开
        if self.dialog is not None:
            if self._dlg_font is None:
                self._dlg_font, _ = get_font(19, bold=True)
                self._dlg_body, _ = get_font(21)
            self.dialog.draw(surface, self._dlg_font, self._dlg_body,
                             self._dialog_tail())

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
        self._draw_dash_trail(surface, ox, oy)
        # 重生后的无敌时间用闪烁表达。不闪的话玩家会以为"我明明碰到刺了
        # 却没死"，闪起来才像"刚复活、还在缓冲期"。
        if self.invuln > 0.0 and int(self.invuln / 0.06) % 2 == 0:
            return
        if self.sprites is None:
            draw_stick_figure(surface, p.rect.centerx + ox, p.rect.bottom + oy)
            if p.gliding:
                self._draw_glider(surface, ox, oy)
            return

        count = self.sprites.frame_count(p.anim_state, p.facing)
        idx = p.anim_frame % count
        img = self.sprites.frame(p.anim_state, p.facing, idx)
        x, y = self.sprites.blit_pos(p.rect.centerx,
                                     p.rect.bottom + int(round(p.land_sink)),
                                     p.anim_state, p.facing, idx)
        surface.blit(img, (x + ox, y + oy))
        if p.gliding:
            self._draw_glider(surface, ox, oy)

    def _draw_glider(self, surface, ox, oy):
        """滑翔中在头顶画伞：伞面 + 两条缰绳 + 一点左右摆动。

        为什么挂在头顶而不是手里：火柴人没有"抓握"的姿势能让玩家看清，
        伞在头顶上方才能一眼看出"这东西正在兜住我"。

        伞面用 world.draw_canopy：和地上的道具图标共用同一段绘制，
        这样"地上捡的东西"和"身上撑开的伞"形状一致，不需要解释。
        """
        p = self.player
        cx = p.rect.centerx + ox
        top = p.rect.top + oy
        sway = 3.0 * math.sin(self.world.time * 3.4)
        pts = world.draw_canopy(surface, cx, top - config.GLIDE_CANOPY_LIFT,
                                half_w=31, height=20, sway=sway)
        base_y = pts[0][1]
        # 缰绳：从伞面两端收到肩膀外侧。画 2px 而不是 1px——1px 在纸底上
        # 几乎看不见，伞就成了"浮在头上的帽子"。
        for sx, ex in ((pts[0][0], cx - 10), (pts[-1][0], cx + 10)):
            pygame.draw.line(surface, config.COLOR_INK,
                             (sx, base_y), (ex, top + 18), 2)

    def _draw_dash_trail(self, surface, ox, oy):
        """冲刺残影：身后拖三条墨线。

        素材里没有冲刺姿态，也没有做多帧残影的预算（每次 alpha 混合都要
        多一次 blit）。三条长度随剩余冲刺时间收短的线就够看清"我在冲"。
        """
        p = self.player
        if not p.dashing:
            return
        ratio = p.dash_time / max(1e-6, config.DASH_TIME)
        base = 24.0 + 40.0 * ratio
        y0 = p.rect.centery + oy
        for i, dy in enumerate((-16, 0, 16)):
            length = base - i * 7.0
            if p.dash_dir > 0:
                x1 = p.rect.left + ox - 3
                x2 = int(x1 - length)
            else:
                x1 = p.rect.right + ox + 3
                x2 = int(x1 + length)
            pygame.draw.line(surface, config.COLOR_TRAIL,
                             (x1, y0 + dy), (x2, y0 + dy), 2)

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
        deaths = u"死亡 %d" % self.deaths
        surface.blit(f_small.render(deaths, True, config.COLOR_MUTED), (152, 48))

        t = u"%05.1f s" % self.level_time
        tw = f_small.size(t)[0]
        surface.blit(f_small.render(t, True, config.COLOR_INK),
                     (config.WIDTH - 30 - tw, 27))

        self._draw_dash_meter(surface)
        self._draw_item_slot(surface)

    def _draw_item_slot(self, surface):
        """HUD 第四行：道具栏。

        没拿到伞时画一个浅色空位，而不是干脆不画——"这里以后会放东西"
        本身就是引导，玩家会顺着去关卡里找。拿到后填成实心伞；滑翔中
        换成篝火橙，让"伞正在起作用"有个即时反馈。
        """
        p = self.player
        f, _ = get_font(14)
        cx, cy = 42, 100
        if p.has_glider:
            color = config.COLOR_CAMP if p.gliding else config.COLOR_GLIDE
            pts = world.draw_canopy(surface, cx, cy - 3, half_w=11, height=9,
                                    fill=color)
            pygame.draw.line(surface, config.COLOR_INK, pts[0], (cx, cy + 5), 1)
            pygame.draw.line(surface, config.COLOR_INK, pts[-1], (cx, cy + 5), 1)
        else:
            world.draw_canopy(surface, cx, cy - 3, half_w=11, height=9,
                              fill=(232, 229, 220), outline=(190, 186, 176))

        surface.blit(f.render(u"滑翔伞", True,
                              config.COLOR_INK if p.has_glider
                              else config.COLOR_MUTED), (60, 88))
        if p.gliding:
            tip, color = u"滑翔中", config.COLOR_CAMP
        elif p.has_glider:
            tip, color = u"空中按住空格", config.COLOR_MUTED
        else:
            tip, color = u"未获得", config.COLOR_MUTED
        surface.blit(f.render(tip, True, color), (112, 88))

    def _draw_dash_meter(self, surface):
        """HUD 第三行：冲刺冷却条。

        没有反馈的话，冷却中按 Shift 会让人以为按键坏了。放在面板里而不是
        屏幕右下角，是因为那里离底部操作提示太近，两者会挤在一起。
        """
        p = self.player
        f, _ = get_font(14)
        surface.blit(f.render(u"冲刺", True, config.COLOR_MUTED), (30, 66))

        bar = pygame.Rect(72, 69, 140, 9)
        pygame.draw.rect(surface, (255, 255, 255), bar)
        ratio = p.dash_ready_ratio
        fill = int((bar.width - 2) * ratio)
        if fill > 0:
            color = config.COLOR_DASH if ratio >= 1.0 else (206, 210, 216)
            pygame.draw.rect(surface, color,
                             pygame.Rect(bar.left + 1, bar.top + 1,
                                         fill, bar.height - 2))
        pygame.draw.rect(surface, config.COLOR_INK, bar, 1)

    def _draw_toast(self, surface):
        """页面顶部的短提示条。

        不做淡出：文字透明要先 render 到带 alpha 的面上再 blit，多一次
        全屏混合；改成"最后 0.6 秒变成一条细线"，视觉上同样是"要消失了"。
        """
        f, _ = get_font(17, bold=True)
        img = f.render(self.toast_text, True, config.COLOR_INK)
        box = pygame.Rect(0, 0, img.get_width() + 44, 36)
        box.centerx = config.WIDTH // 2
        box.top = 132
        if self.toast_timer < 0.6:
            box = pygame.Rect(box.left, box.centery - 2, box.width, 4)
        else:
            compat.rounded_rect(surface, (255, 255, 255), box, radius=10)
            compat.rounded_rect(surface, config.COLOR_GLIDE, box, radius=10, width=2)
            surface.blit(img, (box.centerx - img.get_width() // 2,
                               box.centery - img.get_height() // 2))
            return
        pygame.draw.rect(surface, config.COLOR_GLIDE, box)

    def _draw_death_panel(self, surface):
        """死亡定格画面。

        刻意不做满屏红或大爆炸：整个游戏是纸面手绘风，死一次就闪红光
        会很突兀。用一层很淡的纸色纱 + 手写感的"×"更统一，也让玩家
        在被定格这 0.45 秒里仍能看清自己是怎么死的。
        """
        veil = pygame.Surface((config.WIDTH, config.HEIGHT), pygame.SRCALPHA)
        veil.fill((250, 247, 238, 150))
        surface.blit(veil, (0, 0))

        box = pygame.Rect(0, 0, 380, 148)
        box.center = (config.WIDTH // 2, config.HEIGHT // 2 - 20)
        compat.panel(surface, box, radius=18, fill=(255, 255, 255),
                     border=config.COLOR_INK, width=3)

        f_big, _ = get_font(40, bold=True)
        f, _ = get_font(17)
        mark = f_big.render(u"×", True, config.COLOR_INK)
        surface.blit(mark, (box.centerx - mark.get_width() // 2, box.top + 8))

        cause = f.render(self.last_death_cause or u"死亡", True, config.COLOR_INK)
        surface.blit(cause, (box.centerx - cause.get_width() // 2, box.top + 62))

        where = (u"回到第 %d 个篝火" % (self.checkpoint_index + 1)
                 if self.checkpoint is not None else u"回到出生点")
        tip = f.render(where, True, config.COLOR_MUTED)
        surface.blit(tip, (box.centerx - tip.get_width() // 2, box.top + 88))

        # 定格剩余时间条：让"还要等一下"变成可见的东西，避免玩家按了一遍键
        bar = pygame.Rect(box.left + 30, box.bottom - 26, box.width - 60, 6)
        pygame.draw.rect(surface, (232, 228, 218), bar)
        ratio = self.death_timer / max(1e-6, config.DEATH_FREEZE)
        pygame.draw.rect(surface, config.COLOR_INK,
                         pygame.Rect(bar.left, bar.top,
                                     int(bar.width * (1.0 - ratio)), bar.height))

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
            (u"用时 %.1f 秒    金币 %d / %d    死亡 %d 次"
             % (self.level_time, self.world.taken_coins,
                self.world.total_coins, self.deaths),
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
        lines.append("deaths %d  invuln %.2f  cp %s"
                     % (self.deaths, self.invuln,
                        "-" if self.checkpoint is None
                        else "%d" % (self.checkpoint_index + 1)))
        box = pygame.Rect(16, 176, 380, 16 + 20 * len(lines))
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
