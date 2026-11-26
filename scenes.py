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
import fx
import levels_catalog
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


# ---------------------------------------------------------------- 通用小件

def draw_menu_list(surface, rects, labels, index, font_obj):
    """竖排菜单的统一画法：选中项描边框 + 左侧手绘箭头。

    主菜单和暂停面板共用它。两边各写一遍的话，"选中长什么样"会慢慢
    变成两种风格，玩家得学两次。
    """
    for i, label in enumerate(labels):
        rect = rects[i]
        selected = (i == index)
        if selected:
            compat.rounded_rect(surface, config.COLOR_INK, rect, radius=12, width=3)
            ax = rect.left - 34
            ay = rect.centery
            pygame.draw.lines(surface, config.COLOR_INK, False,
                              [(ax - 10, ay - 9), (ax, ay), (ax - 10, ay + 9)], 3)
        color = config.COLOR_INK if selected else config.COLOR_MUTED
        text = font_obj.render(label, True, color)
        surface.blit(text, (rect.centerx - text.get_width() // 2,
                            rect.centery - text.get_height() // 2))


def draw_check_mark(surface, cx, cy, size=9, color=(94, 148, 106)):
    """手绘对勾。不用 emoji：中文字体里不一定有 ✗ 的字形。"""
    pygame.draw.lines(surface, color, False,
                      [(cx - size, cy), (cx - size * 0.3, cy + size * 0.8),
                       (cx + size, cy - size * 0.9)], 3)


def draw_lock(surface, cx, cy, color):
    """一把小锁：拱形锁梁 + 方锁身。未解锁的关卡卡片靠它一眼认出来。"""
    pygame.draw.arc(surface, color, pygame.Rect(cx - 6, cy - 11, 12, 14),
                    0.0, math.pi, 2)
    body = pygame.Rect(cx - 7, cy - 2, 14, 12)
    compat.rounded_rect(surface, color, body, radius=3, width=2)


def enter_level(app, key):
    """从任意界面进入某一关。**只有这一个入口**，不要在别处直接改
    app.level_path 再 goto("game")——散着写的话，以后加"进关前重置什么"
    就得改七八个地方。
    """
    lv = levels_catalog.get(key)
    if lv is None:
        return False
    app.level_path = levels_catalog.path_of(lv)
    app.scenes.goto("game")
    return True


# ---------------------------------------------------------------- 菜单场景

class MenuScene(Scene):
    """主菜单。项目列表随存档变化：第一次玩是"开始游戏"，
    打了一半是"继续游戏 · 第 N 关"。
    """

    name = "menu"

    TITLE_SIZE = 64
    ITEM_SIZE = 28

    def __init__(self, app):
        Scene.__init__(self, app)
        self.index = 0
        self.items = []
        self._bg = None
        self._item_rects = []

    def on_enter(self):
        self.index = 0
        self.items = self._build_items()
        self._bg = self._build_background()
        self._item_rects = self._build_item_rects()

    def on_exit(self):
        self._bg = None

    def _build_items(self):
        """菜单项依赖存档：不能写成类常量，否则"继续游戏"永远指第一关。"""
        sv = self.app.save
        nxt = sv.first_uncleared()
        if sv.cleared_count() == 0:
            play = u"开始游戏"
        elif sv.all_cleared():
            play = u"再玩一次"
        else:
            play = u"继续游戏 · %s" % nxt["name"]
        return [(play, "play"), (u"选择关卡", "select"),
                (u"设置", "settings"), (u"退出游戏", "quit")]

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

        # 进度条：让"我打到哪了"在菜单上就能看见，不必点进选关界面
        f_p, _ = get_font(17)
        prog = self.app.save.summary()
        pw = f_p.size(prog)[0]
        bg.blit(f_p.render(prog, True, config.COLOR_MUTED),
                ((config.WIDTH - pw) // 2, 236))
        return bg

    def _build_item_rects(self):
        """计算每个菜单项的可点击区域，鼠标与键盘共用同一套坐标。"""
        rects = []
        f_name, _ = get_font(self.ITEM_SIZE)
        # 四项要算着放：256 + 3*58 + 48 = 478，底部提示条在 500。
        # 加"设置"这一项时踩过一次：照旧用 292/66 会让"退出游戏"压到
        # 提示文字上，键盘选中时还能看出来，不选中就是两层灰字叠着。
        top = 256
        gap = 58
        for i, (label, _) in enumerate(self.items):
            w = f_name.size(label)[0] + 120
            h = 48
            rects.append(pygame.Rect((config.WIDTH - w) // 2, top + i * gap, w, h))
        return rects

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            n = len(self.items)
            if event.key in (pygame.K_UP, pygame.K_w):
                self.index = (self.index - 1) % n
                self.app.audio.play("ui")
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.index = (self.index + 1) % n
                self.app.audio.play("ui")
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.app.audio.play("ui")
                self._activate()
            elif event.key == pygame.K_m:
                if not self.app.audio.toggle_mute():
                    self.app.audio.play("ui")
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
        _, action = self.items[self.index]
        if action == "quit":
            self.app.quit()
        elif action == "play":
            enter_level(self.app, self.app.save.first_uncleared()["key"])
        else:
            self.app.scenes.goto(action)

    def draw(self, surface):
        surface.blit(self._bg, (0, 0))
        f_item, _ = get_font(self.ITEM_SIZE)
        f_hint, _ = get_font(17)
        draw_menu_list(surface, self._item_rects,
                       [label for label, _ in self.items],
                       self.index, f_item)

        hint = u"↑↓ 选择    Enter 确定    M 静音    Esc 退出"
        hw = f_hint.size(hint)[0]
        surface.blit(f_hint.render(hint, True, config.COLOR_MUTED),
                     ((config.WIDTH - hw) // 2, config.HEIGHT - 40))


# ---------------------------------------------------------------- 选关场景

class LevelSelectScene(Scene):
    """关卡选择。卡片上带成绩与锁。

    布局是 3 列网格，方向键按网格走（上下跨一行 = ±3）。不做"跳过空位"
    的特殊处理：6 关刚好两整行，按网格走永远不会踩空；以后加到 7 关
    也只会多出一个空位，那时再改。
    """

    name = "select"

    COLS = 3
    CARD_W = 280
    CARD_H = 140
    GAP_X = 24
    GAP_Y = 20
    TOP = 148

    def __init__(self, app):
        Scene.__init__(self, app)
        self.index = 0
        self._bg = None
        self._cards = []
        self.notice = ""
        self.notice_timer = 0.0

    def on_enter(self):
        self._bg = self._build_background()
        self._cards = self._build_cards()
        self.notice = ""
        self.notice_timer = 0.0
        # Delete 清档要按两次。一次就清的话，手滑一下十年进度没了。
        self._confirm_clear = False
        self._card_imgs = []
        self.index = self._default_index()
        self._rebuild_cards()

    def on_exit(self):
        self._bg = None

    def _rebuild_cards(self):
        """把六张卡片各自渲染成一张小图缓存起来（普通 / 选中两版）。

        不缓存的话每帧要画 6 个抗锯齿面板（1.4ms/个）＋ 24 次文字渲染，
        实测 9.25ms/帧——离 16.7ms 预算只剩一半余量，海龟机上会掉帧。
        卡片只在存档变化时才会变，所以缓存是安全的；改存档之后记得调
        本函数重建（清档、F2 全解锁两处）。
        """
        self._card_imgs = []
        for i, rect in enumerate(self._cards):
            lv = levels_catalog.at(i)
            if lv is None:
                self._card_imgs.append(None)
                continue
            pair = []
            for selected in (False, True):
                # 留 4px 边距：panel 的描边与抗锯齿可能压到边界外一像素
                surf = pygame.Surface((rect.w + 8, rect.h + 8), pygame.SRCALPHA)
                self._draw_card(surf, pygame.Rect(4, 4, rect.w, rect.h),
                                lv, selected)
                pair.append(surf)
            self._card_imgs.append(pair)

    def _default_index(self):
        """光标落在第一个没通关的关上：刚打完第 N 关进来，下一步多半是 N+1。"""
        nxt = self.app.save.first_uncleared()
        i = levels_catalog.index_of(nxt["key"])
        return max(0, min(i, len(self._cards) - 1))

    def _build_background(self):
        bg = pygame.Surface((config.WIDTH, config.HEIGHT))
        draw_paper(bg)
        f_title, _ = get_font(38, bold=True)
        title = u"选择关卡"
        tw = f_title.size(title)[0]
        bg.blit(f_title.render(title, True, config.COLOR_INK),
                ((config.WIDTH - tw) // 2, 56))
        draw_sketch_underline(bg, (config.WIDTH - tw) // 2 + 8,
                              (config.WIDTH + tw) // 2 - 8, 108)
        f_sub, _ = get_font(17)
        sub = self.app.save.summary()
        sw = f_sub.size(sub)[0]
        bg.blit(f_sub.render(sub, True, config.COLOR_MUTED),
                ((config.WIDTH - sw) // 2, 116))
        return bg

    def _build_cards(self):
        total_w = self.COLS * self.CARD_W + (self.COLS - 1) * self.GAP_X
        x0 = (config.WIDTH - total_w) // 2
        cards = []
        for i in range(levels_catalog.count()):
            row, col = divmod(i, self.COLS)
            cards.append(pygame.Rect(
                x0 + col * (self.CARD_W + self.GAP_X),
                self.TOP + row * (self.CARD_H + self.GAP_Y),
                self.CARD_W, self.CARD_H))
        return cards

    # ---------------------------------------------------------------- 输入
    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_LEFT, pygame.K_a):
                self._move_lr(-1)
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                self._move_lr(1)
            elif event.key in (pygame.K_UP, pygame.K_w):
                self._move_ud(-self.COLS)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._move_ud(self.COLS)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._activate()
            elif event.key == pygame.K_ESCAPE:
                self.app.scenes.goto("menu")
            elif event.key == pygame.K_DELETE:
                self._press_clear()
            elif event.key == pygame.K_F2:
                # 调试：一键全解锁。写进存档，免得每次重启都要再按一遍。
                # 界面上没有按钮——这是给自己和答辩现场准备的，不是给玩家的。
                self.app.save.set_all_unlocked(True)
                self.notice = u"已解锁全部关卡（F2）"
                self.notice_timer = 2.0
                self._rebuild_cards()
        elif event.type == pygame.MOUSEMOTION:
            self._hover(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._hover(event.pos):
                self._activate()

    def _press_clear(self):
        """清空进度的二次确认：第一次只提示，第二次才真清。"""
        if not self._confirm_clear:
            self._confirm_clear = True
            self.notice = u"再按一次 Delete 清空全部进度"
            self.notice_timer = 3.0
            return
        self.app.save.clear()
        self._confirm_clear = False
        self.notice = u"进度已清空"
        self.notice_timer = 2.0
        self.index = 0
        self._rebuild_cards()

    def _move_lr(self, delta):
        col = self.index % self.COLS
        if 0 <= col + delta < self.COLS:
            self.index += delta
            self.app.audio.play("ui")

    def _move_ud(self, delta):
        n = len(self._cards)
        target = self.index + delta
        # 下一行可能不满（关数是 3 的倍数时不会），落到空位就原地不动
        if 0 <= target < n:
            self.index = target
            self.app.audio.play("ui")

    def _hover(self, pos):
        for i, rect in enumerate(self._cards):
            if rect.collidepoint(pos):
                self.index = i
                return True
        return False

    def _activate(self):
        lv = levels_catalog.at(self.index)
        if lv is None:
            return False
        if not self.app.save.unlocked(lv["key"]):
            prev = levels_catalog.at(self.index - 1)
            self.notice = (u"先通关「%s」" % prev["name"]) if prev else u"尚未解锁"
            self.notice_timer = 1.8
            # 用低沉的一声代替"滴"：被锁住是"这条路不通"，不是出错。
            self.app.audio.play("land")
            return False
        self.app.audio.play("ui")
        return enter_level(self.app, lv["key"])

    def update(self, dt):
        if self.notice_timer > 0.0:
            self.notice_timer = max(0.0, self.notice_timer - dt)
            if self.notice_timer <= 0.0:
                # 提示消失 = 确认窗口关闭。不能让它一直挂着，
                # 否则三分钟后再按一次 Delete 就把进度清了。
                self._confirm_clear = False

    # ---------------------------------------------------------------- 绘制
    def draw(self, surface):
        surface.blit(self._bg, (0, 0))
        for i, rect in enumerate(self._cards):
            pair = self._card_imgs[i] if i < len(self._card_imgs) else None
            if pair is None:
                continue
            surface.blit(pair[1 if i == self.index else 0],
                         (rect.x - 4, rect.y - 4))

        f_hint, _ = get_font(16)
        if self.notice_timer > 0.0 and self.notice:
            hint = self.notice
            danger = (u"先通关" in hint or u"Delete" in hint
                      or u"清空" in hint)
            color = config.COLOR_DANGER if danger else config.COLOR_MUTED
        else:
            hint = u"← → ↑ ↓ 选择    Enter 开始    Esc 返回"
            color = config.COLOR_MUTED
        hw = f_hint.size(hint)[0]
        surface.blit(f_hint.render(hint, True, color),
                     ((config.WIDTH - hw) // 2, config.HEIGHT - 40))

    def _draw_card(self, surface, rect, lv, selected):
        sv = self.app.save
        key = lv["key"]
        unlocked = sv.unlocked(key)
        cleared = sv.is_cleared(key)
        perfect = sv.perfect(key)

        if not unlocked:
            fill, border = (243, 240, 233), (200, 195, 184)
        elif selected:
            fill, border = (255, 253, 238), config.COLOR_INK
        else:
            fill, border = (255, 255, 255), (156, 150, 139)
        compat.panel(surface, rect, radius=14, fill=fill, border=border,
                     width=3 if selected else 2)

        f_idx, _ = get_font(15)
        f_name, _ = get_font(26, bold=True)
        f_desc, _ = get_font(14)
        f_stat, _ = get_font(15)

        # 角标：序号
        idx_text = u"%02d" % (levels_catalog.index_of(key) + 1)
        surface.blit(f_idx.render(idx_text, True, config.COLOR_MUTED),
                     (rect.left + 14, rect.top + 10))

        # 角标：右上角的状态（锁 / 对勾）
        sx = rect.right - 26
        sy = rect.top + 22
        if not unlocked:
            draw_lock(surface, sx, sy, (176, 170, 158))
        elif cleared:
            draw_check_mark(surface, sx, sy + 2, 9)

        # 关名
        name_color = config.COLOR_INK if unlocked else (176, 170, 158)
        img = f_name.render(lv["name"], True, name_color)
        surface.blit(img, (rect.centerx - img.get_width() // 2,
                           rect.top + 30))

        # 一句话说明 / 解锁条件
        if unlocked:
            desc = lv["blurb"]
        else:
            prev = levels_catalog.at(levels_catalog.index_of(key) - 1)
            desc = (u"通关「%s」后解锁" % prev["name"]) if prev else u"尚未解锁"
        img = f_desc.render(desc, True, config.COLOR_MUTED)
        surface.blit(img, (rect.centerx - img.get_width() // 2,
                           rect.top + 78))

        # 成绩行
        if not unlocked:
            stat, color = u"——", (176, 170, 158)
        elif not cleared:
            stat, color = u"未通关", config.COLOR_MUTED
        else:
            parts = []
            t = sv.best_time(key)
            if t is not None:
                parts.append(u"%.1fs" % t)
            c = sv.best_coins(key)
            tot = sv.entry(key).get("total", -1)
            if c is not None and c >= 0:
                parts.append(u"金币 %d/%d" % (c, tot) if tot > 0 else u"金币 %d" % c)
            stat = (u"★  " if perfect else u"") + u"  ·  ".join(parts)
            color = config.COLOR_CAMP if perfect else config.COLOR_INK
        img = f_stat.render(stat, True, color)
        surface.blit(img, (rect.centerx - img.get_width() // 2,
                           rect.top + 104))


# ---------------------------------------------------------------- 设置场景

class SettingsScene(Scene):
    """设置。目前只有两项真正能调，但排的是"以后加东西不用改版式"的布局。

    为什么设置页不放进暂停面板：暂停是"我现在要离开一下"，设置是"我要
    调这台机器"。混在一起，玩家每次想关音效都得先进一关再说。
    """

    name = "settings"

    TOP = 200
    GAP = 64
    ROW_H = 52
    LABEL_X = 250
    VALUE_X = 600

    # 可编辑项。音频设备状态那一行是只读的，单独画，不参与选择。
    ITEMS = [("sfx", u"音效音量"), ("show_debug", u"调试信息"),
             ("shake", u"画面震动")]

    def __init__(self, app):
        Scene.__init__(self, app)
        self.index = 0
        self._bg = None
        self._rects = []

    def on_enter(self):
        self.index = 0
        self._bg = self._build_background()
        self._rects = self._build_rects()

    def on_exit(self):
        self._bg = None

    # ------------------------------------------------------------ 版式
    def _build_background(self):
        bg = pygame.Surface((config.WIDTH, config.HEIGHT))
        draw_paper(bg)
        f_title, _ = get_font(38, bold=True)
        title = u"设置"
        tw = f_title.size(title)[0]
        bg.blit(f_title.render(title, True, config.COLOR_INK),
                ((config.WIDTH - tw) // 2, 84))
        draw_sketch_underline(bg, (config.WIDTH - tw) // 2 + 8,
                              (config.WIDTH + tw) // 2 - 8, 140)
        return bg

    def _build_rects(self):
        rects = []
        for i in range(len(self.ITEMS)):
            rects.append(pygame.Rect(self.LABEL_X - 24,
                                     self.TOP + i * self.GAP,
                                     self.VALUE_X + 220 - (self.LABEL_X - 24),
                                     self.ROW_H))
        return rects

    # ------------------------------------------------------------ 输入
    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self.index = (self.index - 1) % len(self.ITEMS)
                self.app.audio.play("ui")
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.index = (self.index + 1) % len(self.ITEMS)
                self.app.audio.play("ui")
            elif event.key in (pygame.K_LEFT, pygame.K_a):
                self._adjust(-1)
            elif event.key in (pygame.K_RIGHT, pygame.K_d):
                self._adjust(1)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                key = self.ITEMS[self.index][0]
                if key == "sfx":
                    self._adjust(1)
                else:
                    self._adjust(1)      # 开关项：任意方向都是翻转
            elif event.key == pygame.K_m:
                # 静音是临时开关（不写存档）：玩家按 M 只是"这一会儿别响"。
                if not self.app.audio.toggle_mute():
                    self.app.audio.play("ui")
            elif event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.app.scenes.goto("menu")
        elif event.type == pygame.MOUSEMOTION:
            self._hover(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._hover(event.pos):
                if event.pos[0] > self.VALUE_X:
                    self._adjust(1)
                else:
                    self.app.audio.play("ui")

    def _hover(self, pos):
        for i, rect in enumerate(self._rects):
            if rect.collidepoint(pos):
                self.index = i
                return True
        return False

    def _adjust(self, delta):
        key = self.ITEMS[self.index][0]
        if key == "sfx":
            v = int(self.app.save.get_setting("sfx")) + delta
            v = max(0, min(10, v))
            self.app.save.set_setting("sfx", v)
            # 音量立刻生效并试听：改音量却要等下一关才知道效果，
            # 是设置页最没道理的一种体验。
            self.app.audio.set_volume(v / 10.0)
            self.app.audio.play("coin")
        else:
            cur = bool(self.app.save.get_setting("show_debug"))
            self.app.save.set_setting("show_debug", not cur)
            self.app.audio.play("ui")

    # ------------------------------------------------------------ 绘制
    def draw(self, surface):
        surface.blit(self._bg, (0, 0))
        f_label, _ = get_font(24)
        f_val, _ = get_font(22)
        f_small, _ = get_font(15)
        f_hint, _ = get_font(16)

        sv = self.app.save
        for i, (key, label) in enumerate(self.ITEMS):
            r = self._rects[i]
            if i == self.index:
                pygame.draw.rect(surface, (255, 253, 238), r, 0)
                pygame.draw.rect(surface, config.COLOR_INK, r, 2)
            else:
                pygame.draw.rect(surface, (200, 195, 184), r, 1)
            surface.blit(f_label.render(label, True, config.COLOR_INK),
                         (r.left + 24, r.centery - 16))

            if key == "sfx":
                v = int(sv.get_setting("sfx"))
                # 十格音量条：数字（7/10）不能让人一眼判断"还剩多少"，
                # 方块可以。格子的空槽也要画出来，否则 3 档和 10 档看起来
                # 一样长。
                for k in range(10):
                    box = pygame.Rect(self.VALUE_X + k * 15,
                                      r.centery - 8, 12, 16)
                    fill = config.COLOR_INK if k < v else (226, 222, 212)
                    pygame.draw.rect(surface, fill, box, 0)
                    pygame.draw.rect(surface, (176, 170, 158), box, 1)
                # 数字去掉空格写成 "7/10"：带空格会顶到面板右边界外，
                # 截图里"10"整段悬在框外，看着像画错了。
                txt = u"%d/10" % v
            else:
                on = bool(sv.get_setting(key))
                txt = u"开" if on else u"关"
                color = config.COLOR_NPC if on else config.COLOR_MUTED
                # 和上一行的 "7/10" 对齐在同一个 x：两行的值都靠右，
                # 眼睛扫下来是一条竖线，不会一会在中间一会在右边。
                surface.blit(f_val.render(txt, True, color),
                             (self.VALUE_X + 160, r.centery - 15))
                txt = ""
            if txt:
                surface.blit(f_val.render(txt, True, config.COLOR_INK),
                             (self.VALUE_X + 160, r.centery - 15))

        # 音频设备状态：没有声音时，这一行就是唯一的线索。
        # 玩家（和我）第一反应都是"是不是没插耳机"，把设备状态写出来，
        # 能把"没声音"和"音效没接上"分开。
        y = self.TOP + len(self.ITEMS) * self.GAP + 6
        status = u"音频设备：%s" % (u"已静音（M）" if self.app.audio.muted
                                    else self.app.audio.status)
        surface.blit(f_small.render(status, True, config.COLOR_MUTED),
                     (self.LABEL_X, y))

        hint = u"↑↓ 选择    ←→ 调整    Enter 切换    Esc 返回"
        hw = f_hint.size(hint)[0]
        surface.blit(f_hint.render(hint, True, config.COLOR_MUTED),
                     ((config.WIDTH - hw) // 2, config.HEIGHT - 40))


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

        # ---- 粒子（M10）----
        # 粒子池跟场景走，不跟关卡走：重开一关时残留的碎屑几帧就没了，
        # 没必要为它写清理逻辑（clear 只在 _reset_stats 里顺手清一次）。
        self.fx = fx.Particles()

        # ---- 暂停与结算（M9）----
        # 暂停做成场景内的一个遮罩，而不是切一个新场景：切场景会把
        # world/player 全部丢掉，回来就得重新加载关卡（几十毫秒的烘焙），
        # 而且检查点、金币、机关状态全没了。按一下 Esc 就重置一关，
        # 这不是暂停，是同归于尽。
        self.paused = False
        self.pause_index = 0
        # 到达终点后由 _record_result() 填写：破了哪些纪录、下一关是哪关
        self.new_record = {}
        self.next_key = ""
        self.level_key = levels_catalog.path_to_key(self.level_path)

    # ---------------------------------------------------------------- 生命周期
    def on_enter(self):
        self.input = player.InputState()
        # 调试面板默认显示与否交给设置（F1 仍然随时临时切换）。
        # 以前硬编码 True：截图和给别人玩时满屏坐标，很劝退。
        self.show_debug = bool(self.app.save.get_setting("show_debug"))
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
        # 每次死亡的 (列, 原因)。通关时汇总打一行，比散落的单行更适合调难度：
        # "第 21 列死了 3 次" 和 "每处各死一次" 是完全不同的两种设计问题。
        self.death_log = []
        self.toast_text = ""
        self.toast_timer = 0.0
        self.dialog = None
        self.paused = False
        self.pause_index = 0
        self.new_record = {}
        self.next_key = ""
        # 换关/重开时把上一局残留的碎屑清掉：不清的话，重开后第一帧会
        # 在原地看到上一次死亡的黑点，像是"尸体没收拾"。
        if self.fx is not None:
            self.fx.clear()

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
        self.level_key = levels_catalog.path_to_key(path)
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
            # 三层优先级，从"最挡路的东西"往下排：
            #   对话 > 结算 > 暂停 > 正常操作
            # 顺序错了会出各种怪事，比如在暂停面板里按空格让角色跳了一下。

            # 对话打开时，除 E / Esc 之外的按键全部吞掉。不吞的话玩家会在
            # 读字时按空格把角色跳走，回来发现人已经在坑里了。
            if self.dialog is not None:
                if event.key in (pygame.K_e, pygame.K_RETURN, pygame.K_SPACE):
                    self._advance_dialog()
                elif event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                    self.dialog = None
                return

            # 到终点之后整局已冻结，只剩"下一关 / 重来 / 选关"三件事。
            # 不能再按 Esc 弹暂停——那时暂停什么？跑完了。
            if self.goal_reached:
                self._handle_goal_key(event.key)
                return

            if self.paused:
                self._handle_pause_key(event.key)
                return

            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self._open_pause()
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
        elif event.type == pygame.KEYUP:
            if event.key == pygame.K_SPACE:
                self.input.jump_released = True
                self.input.jump_held = False
        elif self.paused and event.type == pygame.MOUSEMOTION:
            self._pause_hover(event.pos)
        elif self.paused and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._pause_hover(event.pos):
                self._activate_pause()

        # 失焦必须清空输入，否则回来时角色会一直往一个方向跑
        if compat.focus_lost(event):
            self._focused = False
            self.input.release_edges()
            self.input.jump_held = False
            if self.player is not None:
                self.player.vx = 0.0
        elif compat.focus_gained(event):
            self._focused = True

    # ---- 暂停 ----
    PAUSE_ITEMS = [(u"继续游戏", "resume"), (u"重开本关", "restart"),
                   (u"选择关卡", "select"), (u"返回主菜单", "menu")]

    def _open_pause(self):
        self.paused = True
        self.pause_index = 0
        # 打开菜单的瞬间清掉按键边沿与水平速度：否则关掉暂停的那一帧，
        # 角色会带着"按着右键"和"待处理的跳跃"冲出去。
        self.input.release_edges()
        self.input.jump_held = False
        if self.player is not None:
            self.player.vx = 0.0

    def _handle_pause_key(self, key):
        n = len(self.PAUSE_ITEMS)
        if key in (pygame.K_UP, pygame.K_w):
            self.pause_index = (self.pause_index - 1) % n
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.pause_index = (self.pause_index + 1) % n
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self._activate_pause()
        elif key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            self.paused = False

    def _pause_item_rects(self):
        """暂停面板的按钮矩形。面板位置固定，矩形可以每次算——一共四项，
        算出来的代价远小于"缓存一份再忘了同步"的代价。"""
        rects = []
        box = self._pause_box()
        top = box.top + 96
        for i in range(len(self.PAUSE_ITEMS)):
            # 左边留 56 而不是 40：选中箭头画在 rect.left-34，留 40 的话
            # 箭头正好戳在面板边框上，看着像画坏了
            rects.append(pygame.Rect(box.left + 56, top + i * 56,
                                     box.w - 96, 44))
        return rects

    def _pause_box(self):
        box = pygame.Rect(0, 0, 340, 96 + len(self.PAUSE_ITEMS) * 56 + 18)
        box.center = (config.WIDTH // 2, config.HEIGHT // 2)
        return box

    def _pause_hover(self, pos):
        for i, rect in enumerate(self._pause_item_rects()):
            if rect.collidepoint(pos):
                self.pause_index = i
                return True
        return False

    def _activate_pause(self):
        _, action = self.PAUSE_ITEMS[self.pause_index]
        self.paused = False
        if action == "resume":
            return
        if action == "restart":
            self.restart()
        elif action == "select":
            self.app.scenes.goto("select")
        elif action == "menu":
            self.app.scenes.goto("menu")

    # ---- 结算 ----
    def _handle_goal_key(self, key):
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            if self.next_key:
                enter_level(self.app, self.next_key)
            else:
                self.app.scenes.goto("select")
        elif key == pygame.K_r:
            self.restart()
        elif key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            self.app.scenes.goto("select")

    def next_level(self):
        """N 键切到下一关。

        按 levels_catalog 的顺序走，而不是 os.listdir 排序：后者在
        l10 出现之后会把"下一关"指到第 2 关去。到最后一关就回第一关
        （N 是调试键，不是通关流程，不需要"没有下一关"的语义）。
        """
        nxt = levels_catalog.next_of(self.level_key) or levels_catalog.first()
        self.load_level(levels_catalog.path_of(nxt))
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

        # 暂停：连世界都不推进。这一句必须放在 world.update 之前——
        # 否则"暂停"期间荡锤还在摆、落刺还在掉、计时还在走，玩家回来
        # 发现自己死在暂停菜单里。
        if self.paused:
            self.input.release_edges()
            self.input.jump_held = False
            self.player.vx = 0.0
            return

        self._poll_axis()
        # 平台先动一步：玩家这一帧要撞的是平台的**新**位置，
        # 否则站在平台前沿时会被追尾，表现为每帧一次的小顿挫。
        self.world.update(dt, self.player)
        # 粒子在暂停/对话里不推进（上面已经 return），但死亡定格时要继续：
        # 碎块正在飞的那 0.45 秒里定住，看着像画面卡了。
        self.fx.update(dt)
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
        # 关卡左边界是看不见的墙。不夹住的话，站在起点按住左键会走出地图，
        # 脚下没有地形，直接判"掉出了地图"摔死——玩家只会觉得"我按了下
        # 左键就死了"。右边不夹：终点在关卡末段，跑过去先结算。
        if self.player.x < 0.0:
            self.player.x = 0.0
            if self.player.vx < 0.0:
                self.player.vx = 0.0
        self._post_physics()
        # 消费必须放在 _post_physics **之后**：踩怪是物理判定的一部分
        # （world.stomp 在 _post_physics 里才跑），它产生的事件如果在这一步
        # 之前就收走了，就会被下一帧 player.update 开头的 events=[] 抹掉——
        # 表现是"踩死怪完全没声音"，而且踩怪、被砸这类判定都在后半段，
        # 少一个音很难联想到是顺序问题。
        self._consume_player_events()
        self.camera.update(dt, self.player.rect)

    # 玩家事件 -> 音效。没列进来的事件不发声（宁可少一个音，不要放一个
    # 和动作对不上的音）。
    _EVENT_SFX = {
        "jump": "jump",
        "land": "land",
        "dash": "dash",
        "bounce": "bounce",
        "stomp": "stomp",
        "glide": "glide",
    }

    def _consume_player_events(self):
        """把 Player 这一帧报上来的一次性事件翻成音效。

        事件由物理层产生（它不知道有没有声卡），这里只做"表现"。顺序保持
        事件产生的顺序，同帧跳跃+落地不会互相盖掉——同名节流 40ms 已经
        能兜住真正会叠的情况。
        """
        events = self.player.events
        if not events:
            return
        p = self.player
        for name in events:
            # 落地与弹跳都在脚下扬一层灰。落地的阈值在 Player 里（落速
            # 不够不报 event），所以这里可以无条件画，不会走一步扬一次。
            if name == "land":
                self._dust(p.rect.centerx, p.rect.bottom - 6)
            elif name == "bounce":
                self._dust(p.rect.centerx, p.rect.bottom - 6, 1.3)
            snd = self._EVENT_SFX.get(name)
            if snd:
                self.app.audio.play(snd)

    def _dust(self, x, y, spread=1.0):
        """脚下扬尘。分左右两簇，而不是一簇居中。

        一簇居中时，角色身体（26px 宽）会把中间那部分整个盖住，剩下几条
        灰线横在黑色剪影的腰上，看着像"人物身上有划痕"，不像尘土。
        往两侧各偏 14px 之后，粒子落在身体轮廓外面，才读得出是"落地压起
        来的灰"。
        """
        self.fx.burst("dust", x - 14, y, spread * 0.8)
        self.fx.burst("dust", x + 14, y, spread * 0.8)

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
                # 之前只有一行终端日志，画面上除了篝火变色没有任何反馈。
                # 玩家跑到这里根本不知道自己刚刚"存档"了——而这是这关
                # 最需要知道的一件事。
                self.toast(u"篝火点燃：这里成了重生点", 1.8)
                self.app.audio.play("camp")
                cr = cp["rect"]
                self.fx.burst("ember", cr.centerx, cr.top + 6, spread=0.6)

        got = self.world.collect(rect)
        if got:
            # 一次吃几枚也只放一个音：节流只能防"同一帧叠五次"，
            # 但一枚和五枚给同一个音才是对的——玩家想要的反馈是"吃到了"。
            self.app.audio.play("coin")
            self.fx.burst("spark", rect.centerx, rect.centery)

        # 道具拾取：拿到伞只提示一次，重复踩同一格不会反复弹横幅。
        for item in self.world.collect_items(rect):
            if item == "glider" and p.pick_glider():
                self.toast(u"获得滑翔伞：空中按住空格可以滑翔", 2.6)
                print(u" 道具     : 获得滑翔伞（空中按住空格滑翔）")
                self.app.audio.play("ui")

        if rect.colliderect(self.world.goal_zone) and not self.goal_reached:
            self.goal_reached = True
            self.input.release_edges()
            self.app.audio.play("goal")
            gz = self.world.goal_zone
            self.fx.burst("spark", gz.centerx, gz.centery - 30)
            print(u" 到达终点：%.1fs，金币 %d/%d，死亡 %d 次" % (
                self.level_time, self.world.taken_coins,
                self.world.total_coins, self.deaths))
            # 漏拿的金币是哪几枚，必须打出来。试玩反馈"这关有金币拿不到"
            # 时，光看总数 10/12 没法判断是"没跳够"还是"画在拿不到的地方"——
            # 把列号列出来，一眼就能定位（列号从 1 开始，和死因那份一致）。
            missed = [c for c in self.world.coins if not c["taken"]]
            if missed:
                missed.sort(key=lambda c: c["rect"].centerx)
                print(u" 漏拿     : %s（共 %d 枚）" % (
                    u"、".join(u"第 %d 列" % (c["rect"].centerx // config.TILE + 1)
                              for c in missed), len(missed)))
            self._print_death_summary()
            self._record_result()

    def _record_result(self):
        """把这一局写进存档，并算好"下一关是哪一关"。

        只在**到达终点**时调用。中途退出、被打死几十次之后关窗口，都不算
        通关——跑酷的通关定义就是跑到终点，不是"来过"。
        """
        self.new_record = {}
        self.next_key = ""
        if not self.level_key:
            return {}
        rec = self.app.save.record(
            self.level_key, self.level_time,
            self.world.taken_coins, self.world.total_coins, self.deaths)
        self.new_record = rec
        nxt = levels_catalog.next_of(self.level_key)
        if nxt is not None:
            self.next_key = nxt["key"]
        if rec.get("first"):
            print(u" 存档     : %s 首次通关，下一关 %s"
                  % (self.level_key, self.next_key or u"（已到最后一关）"))
        return rec

    def _print_death_summary(self):
        """通关时把死因归一下类，一行打完。

        调难度时关心的不是"死了几次"，而是"是不是同一处反复死"：
        同一列死三次说明那里要么太难要么读不懂，散在各处各死一次
        则说明整体偏紧。两种情况的改法完全相反，所以要分开看。
        """
        if not config.LOG_EVENTS or not self.death_log:
            return
        counts = {}
        for col, cause in self.death_log:
            counts[(col, cause)] = counts.get((col, cause), 0) + 1
        items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0][0]))
        parts = [u"第 %d 列 %s×%d" % (col, cause, n)
                 for (col, cause), n in items[:6]]
        print(u" 死因   : " + u"、".join(parts))

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
        col = 0 if self.world is None else int(
            self.player.rect.centerx // config.TILE) + 1
        self.death_log.append((col, cause))
        if config.LOG_EVENTS and self.world is not None:
            print(u" 死亡 %d：%s（第 %d 列，用时 %.1fs）" % (
                self.deaths, cause, col, self.level_time))
        self.app.audio.play("death")
        self.fx.burst("debris", self.player.rect.centerx,
                      self.player.rect.centery)
        # 震屏是"这一下很重"的唯一视觉提示；关掉它的玩家（设置里）也
        # 不该觉得自己漏了什么——死亡提示面板已经足够醒目。
        if self.camera is not None and self.app.save.get_setting("shake"):
            self.camera.kick(7.0, 0.22)
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
        # 机关必须跟着复位：伪装砖塌了、突墙升着，玩家跑回去就卡在坑边。
        # 这一步放在 teleport 之后、camera 之前，重生点这一帧看到的就是
        # "干净的"机关状态。
        self.world.reset_traps()
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
        self.world.reset_traps()
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
        # 粒子画在角色**之后**：扬尘本来就该在脚前面，压在身后会被腿挡住
        # 大半（实测只剩几个像素混在角色的抗锯齿灰边里，等于没画）。
        # 碎块盖住角色也不难看——那时角色是灰色定格的，像刚从身上崩下来。
        ox, oy = self.camera.offset
        self.fx.draw(surface, ox, oy)
        self._draw_hud(surface)

        if (self.show_debug and self.death_timer <= 0.0
                and not self.paused and not self.goal_reached):
            self._draw_debug(surface)

        # 提示条放在调试面板之后：它只在捡到道具那 2 秒出现，
        # 被压在面板下面就等于没提示。
        if self.toast_timer > 0.0 and self.toast_text:
            self._draw_toast(surface)

        # 按键提示条只在没有对话、没有暂停、没到终点时画：那些面板就压在
        # 它上面，半截被盖住的灰字看着像渲染坏了。
        if self.dialog is None and not self.paused and not self.goal_reached:
            f_hint, _ = get_font(16)
            hint = (u"← → / A D 移动   空格 跳跃（空中按住 滑翔）   Shift 冲刺   "
                    u"E 看牌子 / 对话   T 回检查点   R 重开   N 切关   F1 调试   Esc 暂停")
            w = f_hint.size(hint)[0]
            surface.blit(f_hint.render(hint, True, config.COLOR_MUTED),
                         ((config.WIDTH - w) // 2, config.HEIGHT - 26))

        if self.death_timer > 0.0:
            self._draw_death_panel(surface)
        elif self.goal_reached:
            self._draw_goal_panel(surface)
        elif self.paused:
            self._draw_pause_panel(surface)

        # 对话框永远在最上层：它出现时整局已暂停，被 HUD 压住就等于没打开
        if self.dialog is not None:
            if self._dlg_font is None:
                self._dlg_font, _ = get_font(19, bold=True)
                self._dlg_body, _ = get_font(21)
            self.dialog.draw(surface, self._dlg_font, self._dlg_body,
                             self._dialog_tail())

    def _draw_pause_panel(self, surface):
        """暂停面板。半透明遮罩压暗世界，让"现在不动了"一眼可见。"""
        veil = pygame.Surface((config.WIDTH, config.HEIGHT), pygame.SRCALPHA)
        veil.fill((250, 247, 238, 205))
        surface.blit(veil, (0, 0))

        box = self._pause_box()
        compat.panel(surface, box, radius=20, fill=(255, 255, 255),
                     border=config.COLOR_INK, width=3)

        f_title, _ = get_font(30, bold=True)
        title = f_title.render(u"暂停", True, config.COLOR_INK)
        surface.blit(title, (box.centerx - title.get_width() // 2,
                             box.top + 22))

        # 关卡与进度：暂停时最常问的两件事就是"我在哪一关"和"打了多久"
        f_sub, _ = get_font(16)
        name = u""
        lv = levels_catalog.get(self.level_key)
        if lv is not None:
            name = lv["name"]
        sub = u"%s    %.1f 秒    金币 %d/%d" % (
            name or u"第 ? 关", self.level_time,
            self.world.taken_coins if self.world else 0,
            self.world.total_coins if self.world else 0)
        img = f_sub.render(sub, True, config.COLOR_MUTED)
        surface.blit(img, (box.centerx - img.get_width() // 2, box.top + 62))

        draw_menu_list(surface, self._pause_item_rects(),
                       [label for label, _ in self.PAUSE_ITEMS],
                       self.pause_index, f_sub)

        f_hint, _ = get_font(14)
        hint = f_hint.render(u"Esc 继续", True, config.COLOR_MUTED)
        surface.blit(hint, (box.centerx - hint.get_width() // 2,
                            box.bottom - 24))

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
        """结算面板。

        三件事按重要性从上到下排：我跑完了 → 这一局怎么样 → 接下来去哪。
        以前这里只有"Enter 重来"，等于每次通关都要手动退回菜单再选关，
        连续挑战的节奏全断了。
        """
        box = pygame.Rect(0, 0, 480, 240)
        box.center = (config.WIDTH // 2, config.HEIGHT // 2 - 10)
        veil = pygame.Surface((config.WIDTH, config.HEIGHT), pygame.SRCALPHA)
        veil.fill((250, 247, 238, 195))
        surface.blit(veil, (0, 0))
        compat.panel(surface, box, radius=18, fill=(255, 255, 255),
                     border=config.COLOR_INK, width=3)

        f_big, _ = get_font(34, bold=True)
        f, _ = get_font(18)
        f_small, _ = get_font(15)

        sv = self.app.save
        nxt = levels_catalog.get(self.next_key) if self.next_key else None
        all_done = sv.all_cleared()

        y = box.top + 22
        title = u"全部通关！" if all_done else u"到达终点"
        img = f_big.render(title, True, config.COLOR_INK)
        surface.blit(img, (box.centerx - img.get_width() // 2, y))
        y += img.get_height() + 12

        line = (u"用时 %.1f 秒     金币 %d / %d     死亡 %d 次"
                % (self.level_time, self.world.taken_coins,
                   self.world.total_coins, self.deaths))
        img = f.render(line, True, config.COLOR_MUTED)
        surface.blit(img, (box.centerx - img.get_width() // 2, y))
        y += img.get_height() + 12

        # 新纪录 / 最佳成绩：同一行，因为玩家只关心"这次比上次好还是差"
        rec = self.new_record or {}
        badges = []
        if rec.get("time"):
            badges.append(u"最快")
        if rec.get("coins"):
            badges.append(u"金币")
        if rec.get("deaths"):
            badges.append(u"最少死亡")
        if rec.get("first"):
            note = u"首次通关"
            color = config.COLOR_CAMP
        elif badges:
            note = u"新纪录：" + u" · ".join(badges)
            color = config.COLOR_CAMP
        else:
            best = sv.best_time(self.level_key)
            note = (u"本关最佳 %.1f 秒" % best) if best is not None else u""
            color = config.COLOR_MUTED
        if note:
            img = f_small.render(note, True, color)
            surface.blit(img, (box.centerx - img.get_width() // 2, y))
        y += 34

        # 分隔线：上面是成绩，下面是去向。画一条线比留白更清楚地分两段
        pygame.draw.line(surface, (222, 217, 206),
                         (box.left + 36, y - 12), (box.right - 36, y - 12), 2)

        if nxt is not None:
            first = u"Enter  下一关「%s」" % nxt["name"]
            second = u"R  重来本关          Esc  选择关卡"
        else:
            first = u"Enter  返回选关"
            second = u"R  重来本关          Esc  选择关卡"
        img = f.render(first, True, config.COLOR_INK)
        surface.blit(img, (box.centerx - img.get_width() // 2, y))
        y += img.get_height() + 14
        img = f_small.render(second, True, config.COLOR_MUTED)
        surface.blit(img, (box.centerx - img.get_width() // 2, y))

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
