# -*- coding: utf-8 -*-
"""敌人与落石（M6）。

三个对象：蝙蝠巡逻、UFO 投石、天花板落石。它们只提供三个能力：

    update(dt, player)      推进一帧；需要"生成新东西"时把对象 **返回**
    hitbox()                当前可致死的判定矩形，无威胁时返回 None
    draw(surface, ox, oy)   屏幕坐标绘制

为什么 update 用返回值而不是回调：World 里已经有 ``self.rocks`` 这个列表，
回调要传一个 spawn 函数下去，多一层闭包就多一处"谁负责回收"的歧义。
返回对象、由 World 收进列表，回收只有 World 一个地方做。

判定框比贴图小一圈是刻意的。蝙蝠 42px 的贴图里，两侧翅膀各占 8px 左右，
按贴图判定会出现"明明还差半个身位，却被翅膀尖刮死"，玩家只会觉得冤。

素材缺失时全部退回代码绘制。M1 定的底线是"没有素材也能玩"，敌人也一样。
"""

import math

import pygame

import assets
import compat
import config

# ---------------------------------------------------------------- 素材

_BAT_FRAMES = {}
_UFO_IMG = None


def bat_frames(facing=1):
    """按 bat0.png / bat1.png … 连续读取，缺号即停（与角色动画同一套规则）。

    两个朝向各缓存一份：翻转本身要新建 Surface，放在 draw 里就是每帧给
    每只蝙蝠分配一次内存。素材只加载一次，翻转也只需要做一次。
    """
    facing = 1 if facing >= 0 else -1
    if facing in _BAT_FRAMES:
        return _BAT_FRAMES[facing]
    out = []
    for i in range(16):
        try:
            raw = assets.image_scaled("images/enemies/bat%d.png" % i,
                                      config.BAT_SCALE)
        except assets.AssetMissing:
            break
        img = compat.tint(raw, config.COLOR_BAT)
        if facing < 0:
            img = pygame.transform.flip(img, True, False)
        out.append(img)
    _BAT_FRAMES[facing] = out
    return out


def ufo_image():
    global _UFO_IMG
    if _UFO_IMG is None:
        try:
            _UFO_IMG = assets.image_scaled("images/enemies/ufo.png",
                                           config.UFO_SCALE)
        except assets.AssetMissing:
            _UFO_IMG = False          # False = 已确认缺失，别每帧重试
            return None
        except pygame.error:
            _UFO_IMG = False
            return None
    return _UFO_IMG or None


# ---------------------------------------------------------------- 几何工具

def _rect_circle(rect, cx, cy, r):
    """矩形与圆是否相交。采样碰撞要用几十次，比自己拼 Rect 便宜也准。"""
    nx = min(max(cx, rect.left), rect.right)
    ny = min(max(cy, rect.top), rect.bottom)
    dx = cx - nx
    dy = cy - ny
    return dx * dx + dy * dy <= r * r


def _dashed_arc(surface, color, cx, cy, radius, a0, a1, steps=18, dash=2):
    """沿圆弧画一串短点，用作"这块地方会被扫到"的淡提示。

    不用 pygame.draw.arc：它只能描边，而且 1.9.6 上角度单位与粗细都很难对齐；
    点阵在纸面风格里反而更像用铅笔轻轻圈了一下。
    """
    if steps <= 0:
        return
    for i in range(steps + 1):
        if i % 2 == 0:
            continue
        a = a0 + (a1 - a0) * i / float(steps)
        x = int(cx + math.cos(a) * radius)
        y = int(cy + math.sin(a) * radius)
        pygame.draw.circle(surface, color, (x, y), dash)


# ---------------------------------------------------------------- 绘制工具

def _dashed_vline(surface, color, x, y0, y1, dash=8, gap=6, width=1):
    y = y0
    while y < y1:
        pygame.draw.line(surface, color, (x, y), (x, min(y + dash, y1)), width)
        y += dash + gap


def _shadow(surface, x, y, half_w, color, alpha=70, outline=None):
    """落点阴影：一个扁椭圆。

    不用 pygame.draw.ellipse 的平滑填充（1.9.6 上没有抗锯齿），但落点只需要
    "一坨会收拢的暗影"，椭圆够用。预警期的阴影额外描一圈边：它是玩家唯一
    的死亡预告，光靠一层 60/255 的半透明灰在浅色地面上实在不够显眼。
    """
    rect = pygame.Rect(int(x - half_w), int(y - 7), int(half_w * 2), 14)
    if rect.width < 2:
        return
    surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.ellipse(surf, color + (alpha,), surf.get_rect())
    surface.blit(surf, rect.topleft)
    if outline is not None:
        pygame.draw.ellipse(surface, outline, rect, 2)


# ---------------------------------------------------------------- 蝙蝠

class Bat(object):
    """在一条水平线上往返的蝙蝠，叠加正弦上下浮动。

    巡逻区间由地图里一段连续的 'B' 决定（起止格中心），所以改关卡只要
    在地图上多涂几格 'B'，不必改代码。
    """

    def __init__(self, left_px, right_px, cy):
        self.left = float(left_px)
        self.right = float(right_px)
        self.cx = (self.left + self.right) * 0.5
        self.cy = float(cy)
        self.dir = 1
        self.t = 0.0
        self.anim = 0.0
        self.frames = bat_frames(1)

    # ---- 运行期 ----
    def reset(self):
        self.cx = (self.left + self.right) * 0.5
        self.dir = 1
        self.t = 0.0
        self.anim = 0.0

    def update(self, dt, player=None):
        self.t += dt
        self.anim += dt * config.BAT_FPS
        self.cx += self.dir * config.BAT_SPEED * dt
        # 到端点直接钳住并反向：不钳的话单帧位移会把端点甩出几像素，
        # 巡逻范围随帧率漂移。
        if self.cx >= self.right:
            self.cx = self.right
            self.dir = -1
        elif self.cx <= self.left:
            self.cx = self.left
            self.dir = 1
        return None

    def bob(self):
        return math.sin(self.t * config.BAT_BOB_SPEED) * config.BAT_BOB_AMP

    def hitbox(self):
        w, h = config.BAT_HITBOX
        return pygame.Rect(int(self.cx - w * 0.5),
                           int(self.cy + self.bob() - h * 0.5), w, h)

    def draw(self, surface, ox, oy):
        cx = int(self.cx) + ox
        cy = int(self.cy + self.bob()) + oy
        frames = bat_frames(self.dir)
        if frames:
            img = frames[int(self.anim) % len(frames)]
            surface.blit(img, img.get_rect(center=(cx, cy)))
            return
        # 兜底：两片折线翅膀 + 一颗墨点，缩到 40px 也认得出是蝙蝠
        flap = math.sin(self.anim * 1.6) * 6.0
        pygame.draw.circle(surface, config.COLOR_INK, (cx, cy), 5)
        for side in (-1, 1):
            pygame.draw.lines(surface, config.COLOR_INK, False, [
                (cx + side * 5, cy),
                (cx + side * 14, cy - 6 + flap),
                (cx + side * 22, cy + 2),
            ], 2)


# ---------------------------------------------------------------- 落石

class FallingRock(object):
    """一块石头。三态：预警 → 下落 → 碎屑。

    预警期是这东西能成立的全部理由。没有预警的落石在跑酷里等于随机死亡，
    玩家学不到任何东西；有了地上那圈收缩的阴影，"什么时候跳"就变成
    可以看、可以记的东西。
    """

    def __init__(self, x, y, ground_y, warn=None):
        self.x = float(x)
        self.y = float(y)
        self.ground_y = float(ground_y)
        self.state = "warn"
        # 每块石头自己记总时长：M8 的二连石要让"远的那块影子先收拢"，
        # 两块石头的预警长度不一样。绘制阴影时用各自的总时长算比例，
        # 才不会出现"远的那块影子一下子缩没了"。
        self.warn_total = (config.ROCK_WARN_TIME if warn is None
                           else float(warn))
        self.warn = self.warn_total
        self.vy = 0.0
        self.shard = 0.0
        self.dead = False

    # ---- 运行期 ----
    def update(self, dt, player=None):
        if self.state == "warn":
            self.warn -= dt
            if self.warn <= 0.0:
                self.state = "fall"
                self.vy = config.ROCK_FALL_SPEED * 0.35
            return None
        if self.state == "fall":
            self.vy = min(self.vy + config.GRAVITY_DOWN * 0.35 * dt,
                          config.ROCK_FALL_SPEED)
            self.y += self.vy * dt
            if self.y >= self.ground_y:
                self.y = self.ground_y
                self.state = "shatter"
                self.shard = config.ROCK_SHARD_TIME
            return None
        self.shard -= dt
        if self.shard <= 0.0:
            self.dead = True
        return None

    def hitbox(self):
        # 预警期不判定：石头还在"酝酿"，画面上它也没离开天花板，
        # 这时候判死等于"看着预告就被砸中"。
        if self.state != "fall":
            return None
        half = config.ROCK_HITBOX * 0.5
        return pygame.Rect(int(self.x - half), int(self.y - half),
                           config.ROCK_HITBOX, config.ROCK_HITBOX)

    def draw(self, surface, ox, oy):
        cx = int(self.x) + ox
        gy = int(self.ground_y) + oy

        if self.state == "warn":
            # 阴影随倒计时收拢：收拢到最小的一瞬间石头落下。
            # "看着它缩到你脚下"比任何数字倒计时都直观。
            ratio = max(0.0, self.warn / max(1e-6, self.warn_total))
            half = 14 + 26 * ratio
            _shadow(surface, cx, gy, half, (60, 56, 52), alpha=70,
                    outline=config.COLOR_MUTED)
            _dashed_vline(surface, (206, 190, 178), cx, int(self.y) + oy + 8, gy)
            # 石头本体在预警期轻轻抖动，暗示"它要掉下来了"
            sx = cx + int(2.0 * math.sin(self.warn * 40.0))
            self._draw_rock(surface, sx, int(self.y) + oy, 0.55)
            return

        if self.state == "fall":
            _shadow(surface, cx, gy, 20, (60, 56, 52), alpha=52)
            # 拖影：三笔竖直短线，把 700px/s 的速度画出来
            for k in range(3):
                y0 = int(self.y) + oy - 14 - k * 12
                pygame.draw.line(surface, (198, 190, 180),
                                 (cx, y0), (cx, y0 - 8), 2)
            self._draw_rock(surface, cx, int(self.y) + oy, 1.0)
            return

        # 碎屑：四块小石头向外飞一点再消失
        t = 1.0 - max(0.0, self.shard) / max(1e-6, config.ROCK_SHARD_TIME)
        for i, (dx, dy) in enumerate(((-16, -6), (14, -9), (-8, -14), (10, -3))):
            k = t * (1.0 + i * 0.15)
            pygame.draw.circle(surface, (120, 114, 106),
                               (cx + int(dx * k), gy - 4 + int(dy * k)), 3)

    def _draw_rock(self, surface, cx, cy, scale):
        r = config.ROCK_SIZE * 0.5 * scale
        pts = [(cx - r, cy - r * 0.4), (cx - r * 0.6, cy - r),
               (cx + r * 0.5, cy - r * 0.8), (cx + r, cy + r * 0.1),
               (cx + r * 0.4, cy + r), (cx - r * 0.7, cy + r * 0.8)]
        # pygame 1.9.6 的 polygon 不接受浮点坐标，统一取整
        pts = [(int(x), int(y)) for x, y in pts]
        pygame.draw.polygon(surface, (146, 139, 130), pts)
        pygame.draw.polygon(surface, config.COLOR_INK, pts, 2)


# ---------------------------------------------------------------- UFO

class Ufo(object):
    """悬停的 UFO，玩家进入射程就周期性投石。

    石头先从机腹下"长"出来并预警 0.9 秒才落——锁定、瞄准、发射三个状态
    会多出两条时序分支，而玩家真正需要的只有"地上那圈阴影什么时候收拢"。
    """

    def __init__(self, cx, cy):
        self.home = (float(cx), float(cy))
        self.cx = float(cx)
        self.cy = float(cy)
        self.t = 0.0
        # 相位错开：一排 UFO 同时投弹会把一段路变成弹幕
        self.cd = config.UFO_FIRE_INTERVAL * (0.45 + 0.1 * (int(cx) % 5))
        self.drop_count = 0
        self.img = ufo_image()

    # ---- 运行期 ----
    def reset(self):
        self.cx, self.cy = self.home
        self.t = 0.0
        self.cd = config.UFO_FIRE_INTERVAL * (0.45 + 0.1 * (int(self.cx) % 5))
        self.drop_count = 0

    def update(self, dt, player=None):
        self.t += dt
        # 上下 5px 的呼吸感：完全静止的 UFO 看着像背景贴图
        self.cy = self.home[1] + math.sin(self.t * 1.7) * 5.0
        if player is None:
            return None

        dx = player.rect.centerx - self.cx
        if abs(dx) > config.UFO_RANGE:
            # 玩家退出去就重新计时：避免"刚走到射程边缘，头上就掉石头"
            self.cd = max(self.cd, 0.8)
            return None

        self.cd -= dt
        if self.cd > 0.0:
            return None
        self.cd = config.UFO_FIRE_INTERVAL
        self.drop_count += 1
        aim = self.cx + max(-config.UFO_TARGET_SLACK,
                            min(config.UFO_TARGET_SLACK, dx))
        # 只报"在哪儿投"，不自己算地面：找地面要查地图格子，
        # 那是 World 的职责，敌人只管自己的位置。
        return ("drop", aim, self.cy + config.UFO_DROP_OFFSET)

    def hitbox(self):
        # UFO 只负责投石，撞上去不死。真要判死，从下面跳起来顶到它就该死，
        # 但"头顶上有个不能碰的东西"在跑酷里是纯粹的信息噪音。
        return None

    def draw(self, surface, ox, oy):
        cx = int(self.cx) + ox
        cy = int(self.cy) + oy
        if self.img is not None:
            surface.blit(self.img, self.img.get_rect(center=(cx, cy)))
            return
        # 兜底：椭圆碟身 + 半圆罩 + 三盏灯
        body = pygame.Rect(cx - 22, cy - 4, 44, 14)
        pygame.draw.ellipse(surface, (232, 214, 130), body)
        pygame.draw.ellipse(surface, config.COLOR_INK, body, 2)
        pygame.draw.polygon(surface, (206, 200, 236),
                            [(cx - 13, cy - 4), (cx - 8, cy - 16),
                             (cx + 8, cy - 16), (cx + 13, cy - 4)])
        pygame.draw.polygon(surface, config.COLOR_INK,
                            [(cx - 13, cy - 4), (cx - 8, cy - 16),
                             (cx + 8, cy - 16), (cx + 13, cy - 4)], 2)
        for i in (-1, 0, 1):
            pygame.draw.circle(surface, config.COLOR_CAMP, (cx + i * 11, cy + 3), 2)

    def lights(self):
        """投弹前灯闪的强度 0..1，绘制用。CD 进入最后 0.5 秒开始闪。"""
        if self.cd > 0.5:
            return 0.0
        return 0.5 + 0.5 * math.sin(self.t * 26.0)


# ---------------------------------------------------------------- 天花板裂缝

class RockSpawner(object):
    """天花板裂缝：周期性地掉石头，不需要玩家靠近。

    和 UFO 的区别是"一定会掉"——UFO 是遭遇战，裂缝是节拍器。
    一排裂缝用不同相位铺开，玩家跑过时会听到一串错开的落石。
    """

    def __init__(self, cx, top_y, ground_y, phase):
        self.cx = float(cx)
        self.top_y = float(top_y)
        self.ground_y = float(ground_y)
        self.cd = config.ROCK_SPAWN_INTERVAL * phase
        self.count = 0

    def reset(self):
        self.cd = config.ROCK_SPAWN_INTERVAL * 0.6
        self.count = 0

    def update(self, dt, player=None):
        self.cd -= dt
        if self.cd > 0.0:
            return None
        self.cd = config.ROCK_SPAWN_INTERVAL
        self.count += 1
        return ("drop", self.cx, self.top_y + config.ROCK_SIZE * 0.5)

    def hitbox(self):
        return None

    def draw(self, surface, ox, oy):
        """裂缝本身烘焙不了（裂缝在实心格里），只在头顶画三笔碎石纹。"""
        cx = int(self.cx) + ox
        y = int(self.top_y) + oy
        for i, dx in enumerate((-6, 0, 7)):
            pygame.draw.line(surface, (150, 144, 134),
                             (cx + dx, y + 1), (cx + dx + 2, y + 9 + i % 2 * 3), 2)


# ---------------------------------------------------------------- 走地怪

class Walker(object):
    """在地上左右走的小怪物，可以从头顶踩死。

    和蝙蝠的差别不是"能杀 / 不能杀"，而是**玩家有没有主动权**：
    蝙蝠在你头顶飞来飞去，你只能等；走地怪在路上来回走，你可以等它转身，
    也可以主动跳上去把它踩掉。两条路都成立，这一段才有得选。

    素材包里没有走地怪，它完全由代码画：一个墨色团子 + 两条腿 + 两只眼。
    纸面手绘风里"实心墨团"是最容易一眼认出的形状，比贴一张卡通图更统一。
    """

    def __init__(self, left_px, right_px, ground_y, phase=0.0):
        self.left = float(left_px)
        self.right = float(right_px)
        if self.right - self.left < 1.0:
            # 只有一个格子：给它 ±24px 的来回，否则玩家会以为它是块石头
            self.left = left_px - config.WALKER_SOLO_PATROL
            self.right = left_px + config.WALKER_SOLO_PATROL
        self.cx = (self.left + self.right) * 0.5
        self.ground_y = float(ground_y)
        self.dir = 1
        self.t = phase
        self.anim = 0.0
        self.state = "walk"        # walk / dying / gone
        self.die_t = 0.0

    # ---- 运行期 ----
    def reset(self):
        self.cx = (self.left + self.right) * 0.5
        self.dir = 1
        self.t = 0.0
        self.anim = 0.0
        self.state = "walk"
        self.die_t = 0.0

    @property
    def alive(self):
        return self.state == "walk"

    def update(self, dt, player=None):
        self.t += dt
        if self.state == "dying":
            self.die_t += dt
            if self.die_t >= config.WALKER_DIE_TIME:
                self.state = "gone"
            return None
        if self.state == "gone":
            return None
        self.anim += dt * config.WALKER_STEP_FPS
        self.cx += self.dir * config.WALKER_SPEED * dt
        if self.cx >= self.right:
            self.cx = self.right
            self.dir = -1
        elif self.cx <= self.left:
            self.cx = self.left
            self.dir = 1
        return None

    def hitbox(self):
        """活着才有判定。踩死之后立刻返回 None，同一帧不会再被算一次碰撞。"""
        if not self.alive:
            return None
        w, h = config.WALKER_HITBOX
        return pygame.Rect(int(self.cx - w * 0.5),
                           int(self.ground_y - 3 - h), w, h)

    def stomp_zone(self):
        """可被踩中的区域：判定框上半部分（见 config.STOMP_TOP_RATIO）。"""
        if not self.alive:
            return None
        box = self.hitbox()
        h = int(box.height * config.STOMP_TOP_RATIO)
        return pygame.Rect(box.x, box.y, box.width, h)

    def stomp(self):
        """被踩。返回是否真的踩到了（已经死了返回 False）。"""
        if not self.alive:
            return False
        self.state = "dying"
        self.die_t = 0.0
        return True

    def draw(self, surface, ox, oy):
        if self.state == "gone":
            return
        cx = int(self.cx) + ox
        feet = int(self.ground_y) + oy

        # 死亡：闪烁 + 整体缩一点。闪而不淡出，是因为纸底上的半透明墨团
        # 看起来像"糊了一块"，闪两下消失才读得出"它被打没了"。
        scale = 1.0
        if self.state == "dying":
            if int(self.die_t * config.WALKER_DIE_FLICKER) % 2 == 0:
                return
            scale = 1.0 - 0.45 * (self.die_t / max(1e-6, config.WALKER_DIE_TIME))

        bw = config.WALKER_BODY_W * scale
        bh = config.WALKER_BODY_H * scale
        gait = math.sin(self.anim * math.pi * 2.0) if self.alive else 0.0
        body_cy = feet - 9 - bh * 0.5 + abs(gait) * 1.5

        # 腿：两条短墨线，前后摆
        for side, off in ((-1, gait), (1, -gait)):
            hip_x = cx + side * 7 * scale
            pygame.draw.line(surface, config.COLOR_INK,
                             (hip_x, int(body_cy + bh * 0.4)),
                             (int(hip_x + off * 5.0), feet - 1), 3)

        # 身体：一个底部略扁的墨团 + 两根小角
        rect = pygame.Rect(0, 0, int(bw), int(bh))
        rect.center = (cx, int(body_cy))
        pygame.draw.ellipse(surface, (58, 55, 52), rect)
        pygame.draw.ellipse(surface, config.COLOR_INK, rect, 2)
        for side in (-1, 1):
            tipx = cx + side * int(bw * 0.28)
            tipy = rect.top - 6 * scale
            pygame.draw.line(surface, config.COLOR_INK,
                             (cx + side * int(bw * 0.16), rect.top + 2),
                             (tipx, tipy), 2)

        if self.state == "dying":
            # 消失前给一个"×"：踩死和"走到一半卡住了"必须区分得开
            pygame.draw.line(surface, (255, 255, 255),
                             (cx - 7, rect.centery - 7), (cx + 7, rect.centery + 7), 2)
            pygame.draw.line(surface, (255, 255, 255),
                             (cx + 7, rect.centery - 7), (cx - 7, rect.centery + 7), 2)
            return

        # 眼睛：两只白点，瞳孔朝行进方向。看得见朝向，才数得清它什么时候转身
        for side in (-1, 1):
            ex = cx + side * 6 + self.dir * 2
            pygame.draw.circle(surface, (255, 255, 255), (int(ex), int(body_cy - 4)), 4)
            pygame.draw.circle(surface, config.COLOR_INK,
                               (int(ex + self.dir * 1.5), int(body_cy - 4)), 2)


# ---------------------------------------------------------------- 旋转刺轮

class Rotor(object):
    """吊在横梁下、绕轴逆时针转的十字刀片。

    这是本作第一个"靠碰撞检测本身构成难度"的机关，但它**不是**让你等窗口
    硬穿的路障——那种设计在 300px/s 的角色速度下不成立（见 config 注释：
    轴心贴近头顶时，人横穿一次等于绕轴心转 144°，怎么排相位都过不去）。

    它做的是**禁跳区**：臂短到扫不到站立的角色（臂端 622+8 < 头顶 634），
    贴着地面横跑一定安全；只要起跳，脚一离开地面就进刀口。
    所以它惩罚的是"想抄近道"和"贪图头顶那枚金币"，而不是运气。

    判定用"沿臂采样小圆"而不是一个大圆：外接圆会把四条臂之间的空隙
    变成隐形墙，玩家从缝里钻过去还被判死，那是最没道理的一种冤。
    """

    def __init__(self, cx, cy, phase=0.0):
        self.cx = float(cx)
        self.cy = float(cy)
        self.phase = phase
        self.t = 0.0
        self.angle = phase
        self._sweep = None

    # ---- 运行期 ----
    def reset(self):
        self.t = 0.0
        self.angle = self.phase

    def _sweep_surface(self):
        """扫掠范围底图：一层极淡的红 + 一圈虚线。

        缓存成一张小图。每帧新建一个 SRCALPHA Surface 再画圆，四臂机关
        一多就会在帧预算里占出可见的一块；底图是不动的，画一次就够。
        """
        if self._sweep is not None:
            return self._sweep
        r = int(config.ROTOR_ARM_LEN) + 5
        surf = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
        c = (r + 1, r + 1)
        pygame.draw.circle(surf, (247, 201, 190, 30), c, r - 3)
        for i in range(0, 360, 10):
            a = math.radians(i)
            x = int(c[0] + math.cos(a) * (r - 2))
            y = int(c[1] + math.sin(a) * (r - 2))
            pygame.draw.circle(surf, (214, 168, 160, 210), (x, y), 2)
        self._sweep = surf
        return surf

    def update(self, dt, player=None):
        self.t += dt
        # 屏幕 y 轴向下，角度递减 = 视觉逆时针。逆时针时臂在底部与玩家
        # 前进方向同向（相对速度 300-74），顺时针时是迎面（300+74）。
        self.angle = self.phase + config.ROTOR_SPIN * self.t * config.ROTOR_SPEED
        return None

    def hitbox(self):
        # 没有单一判定框：形状是四条会转的线
        return None

    def arms(self):
        """四条臂的末端坐标，绘制与判定共用同一份角度。"""
        out = []
        for i in range(config.ROTOR_ARMS):
            a = self.angle + i * 2.0 * math.pi / config.ROTOR_ARMS
            out.append((a, self.cx + math.cos(a) * config.ROTOR_ARM_LEN,
                        self.cy + math.sin(a) * config.ROTOR_ARM_LEN))
        return out

    def hits(self, rect):
        r = config.ROTOR_ARM_THICK * 0.5
        step = config.ROTOR_SAMPLE_STEP
        for a, ex, ey in self.arms():
            # 从轴心往外采样。起点跳过轴心附近：那里是轮毂，给一点容错，
            # 也让"贴着轴心站着"不会因为一次采样就被判死。
            s = float(config.ROTOR_HUB_R + 4)
            while s < config.ROTOR_ARM_LEN - 2.0:
                if _rect_circle(rect, self.cx + math.cos(a) * s,
                                self.cy + math.sin(a) * s, r):
                    return True
                s += step
            if _rect_circle(rect, ex, ey, config.ROTOR_TIP_R):
                return True
        return False

    def draw(self, surface, ox, oy):
        cx = int(self.cx) + ox
        cy = int(self.cy) + oy

        # 扫掠范围：淡红圆 + 虚线圈。第一次见的人靠它才知道"这东西会转到
        # 我站的地方"，否则只能站在原地等它转一圈才敢动。
        sweep = self._sweep_surface()
        surface.blit(sweep, (cx - sweep.get_width() // 2,
                             cy - sweep.get_height() // 2))

        for a, ex, ey in self.arms():
            dx, dy = math.cos(a), math.sin(a)
            px, py = -dy, dx
            # 刀片：从轴心往外收窄的多边形，比一条等宽直线更像"刃"
            r0 = config.ROTOR_HUB_R - 1
            w0 = config.ROTOR_ARM_THICK * 0.5
            w1 = 2.0
            pts = [
                (cx + dx * r0 + px * w0, cy + dy * r0 + py * w0),
                (cx + dx * config.ROTOR_ARM_LEN + px * w1,
                 cy + dy * config.ROTOR_ARM_LEN + py * w1),
                (cx + dx * config.ROTOR_ARM_LEN - px * w1,
                 cy + dy * config.ROTOR_ARM_LEN - py * w1),
                (cx + dx * r0 - px * w0, cy + dy * r0 - py * w0),
            ]
            pts = [(int(x), int(y)) for x, y in pts]
            pygame.draw.polygon(surface, (92, 88, 82), pts)
            pygame.draw.polygon(surface, config.COLOR_INK, pts, 2)

            # 尖端三角刺：比刀身宽一圈，远远看过去是四个"尖"
            tipx = cx + dx * config.ROTOR_ARM_LEN
            tipy = cy + dy * config.ROTOR_ARM_LEN
            tri = [
                (int(tipx + px * 5), int(tipy + py * 5)),
                (int(tipx + dx * 11), int(tipy + dy * 11)),
                (int(tipx - px * 5), int(tipy - py * 5)),
            ]
            pygame.draw.polygon(surface, config.COLOR_DANGER, tri)
            pygame.draw.polygon(surface, config.COLOR_INK, tri, 2)

        pygame.draw.circle(surface, (120, 116, 110), (cx, cy), config.ROTOR_HUB_R)
        pygame.draw.circle(surface, config.COLOR_INK, (cx, cy), config.ROTOR_HUB_R, 2)
        pygame.draw.circle(surface, config.COLOR_INK, (cx, cy), 2)


# ---------------------------------------------------------------- 荡锤

class Pendulum(object):
    """吊在支架上来回摆的带刺铁球。

    和刺轮互补：刺轮考"读转速"，荡锤考"读相位"——锤子走到最高点开始回摆
    的那一瞬间是唯一的空档，站在下面等的人必须等到摆回去。

    摆角用正弦而不是真实单摆方程：真实单摆在大摆幅下周期会随幅度变化，
    玩家背下来的节奏会漂；正弦摆的周期是常数，背一次就永远对。
    """

    def __init__(self, px, py, phase=0.0):
        self.px = float(px)
        self.py = float(py)
        self.phase = phase
        self.t = 0.0
        self.angle = 0.0

    # ---- 运行期 ----
    def reset(self):
        self.t = 0.0
        self.angle = config.PENDULUM_AMP * math.sin(self.phase)

    def update(self, dt, player=None):
        self.t += dt
        self.angle = config.PENDULUM_AMP * math.sin(
            self.t * config.PENDULUM_SPEED + self.phase)
        return None

    def bob(self):
        arm = config.PENDULUM_ARM
        return (self.px + math.sin(self.angle) * arm,
                self.py + math.cos(self.angle) * arm)

    def hitbox(self):
        bx, by = self.bob()
        r = config.PENDULUM_BOB_R
        return pygame.Rect(int(bx - r), int(by - r), r * 2, r * 2)

    def hits(self, rect):
        bx, by = self.bob()
        return _rect_circle(rect, bx, by, config.PENDULUM_BOB_R)

    def draw(self, surface, ox, oy):
        # 吊点：一块小铁板 + 一颗螺栓。H 格本身就在半空，所以要有个"焊在
        # 什么上面"的交代，否则锤子像是凭空吊着的。
        px = int(self.px) + ox
        py = int(self.py) + oy
        plate = pygame.Rect(px - 20, py - 9, 40, 9)
        pygame.draw.rect(surface, (140, 134, 124), plate)
        pygame.draw.rect(surface, config.COLOR_INK, plate, 2)
        pygame.draw.circle(surface, config.COLOR_INK, (px, py), 3)

        # 摆动轨迹：一串淡点，把"锤子会扫到哪儿"提前画出来。
        # 玩家真正需要读的就是这个圆弧的下沿——它决定了哪一段路是禁区。
        a0 = -config.PENDULUM_AMP
        a1 = config.PENDULUM_AMP
        _dashed_arc(surface, (206, 190, 184), px, py,
                    config.PENDULUM_ARM, math.pi * 0.5 + a0,
                    math.pi * 0.5 + a1, steps=26, dash=2)

        bx, by = self.bob()
        bx, by = int(bx) + ox, int(by) + oy
        # 链条：一串小点，比直线更像"锁链"，也不用画绳子的抖动
        for i in range(1, config.PENDULUM_CHAIN_DOTS):
            k = i / float(config.PENDULUM_CHAIN_DOTS)
            dx = px + (bx - px) * k
            dy = py + (by - py) * k
            pygame.draw.circle(surface, (110, 106, 100), (int(dx), int(dy)), 2)

        r = config.PENDULUM_BOB_R
        pygame.draw.circle(surface, (120, 116, 110), (bx, by), r)
        pygame.draw.circle(surface, config.COLOR_INK, (bx, by), r, 2)
        # 六颗尖刺
        for i in range(6):
            a = i * math.pi / 3.0
            x0 = bx + math.cos(a) * r
            y0 = by + math.sin(a) * r
            x1 = bx + math.cos(a) * (r + 6)
            y1 = by + math.sin(a) * (r + 6)
            pygame.draw.line(surface, config.COLOR_INK,
                             (int(x0), int(y0)), (int(x1), int(y1)), 2)


# ---------------------------------------------------------------- M8 隐形机关
#
# 这一组和前面所有敌人的区别是：**它们不追你，只在原地等你犯错**。
# 共同点因此不是"移动方式"，而是"线索"——每种机关都有一样东西，
# 在触发之前就已经摆在画面上（薄板、黑线、地槽、两道影子）。
# 没有线索的陷阱在跑酷里等于随机死亡，玩家学不到任何东西。


def _hash01(a, b):
    """确定性伪随机（0..1）。手绘抖动必须每帧一样，否则画面会沸腾。

    目前只在伪装砖的板面纹理上用得上（每一格纹理略有不同，才不像
    流水线产品）；塌陷时的抖动是**时间**函数，不能用这个。
    """
    h = (a * 73856093) ^ (b * 19349663)
    return (h & 0xFFFF) / 65535.0


class CrumbleBrick(object):
    """伪装砖：看着像地板，其实只有薄薄一层壳，踩上 0.3 秒就塌。

    它考的不是反应速度，而是**别在这条路上停**：跑速 300px/s 时 0.3 秒
    能走 1.4 格，塌陷永远追不上人；一旦停下看风景，脚下就没了。

    公平性靠"它和真地面长得不一样"：
      - 真地面是整块土，只有顶线，砖缝里还有竖纹；
      - 伪装砖是一块四面描边的薄板，下面能直接看到坑（画面里是纸底）。
    所以不需要背板——第一次见到也能看出"这块板是浮着的"。

    塌掉 3 秒后自己长回来。没有这条，玩家掉进坑里重生后可能面对一条
    已经塌空的桥，那就成了"死一次就再也过不去"。
    """

    def __init__(self, col, row):
        self.col = col
        self.row = row
        tile = config.TILE
        self.rect = pygame.Rect(col * tile, row * tile,
                                tile, config.BRICK_THICK)
        self.state = "idle"      # idle → crack → gone → idle
        self.timer = 0.0
        self.t = 0.0

    # ---- 运行期 ----
    def reset(self):
        self.state = "idle"
        self.timer = 0.0
        self.t = 0.0

    def solid(self):
        """给碰撞用的矩形；塌掉之后返回 None。"""
        if self.state == "gone":
            return None
        return self.rect

    def update(self, dt, player=None):
        self.t += dt
        if self.state == "gone":
            self.timer -= dt
            if self.timer <= 0.0:
                self.state = "idle"
                self.timer = 0.0
            return None
        if self.state == "crack":
            self.timer -= dt
            if self.timer <= 0.0:
                self.state = "gone"
                self.timer = config.BRICK_RESTORE
            return None
        # idle：踩上就开始裂。容差 3px：落地那一帧脚底可能还差一两像素。
        if player is not None and player.stands_on(self.rect, 3.0):
            self.state = "crack"
            self.timer = config.BRICK_CRACK_TIME
        return None

    # ---- 绘制 ----
    def draw(self, surface, ox, oy):
        rect = self.rect
        x = rect.x + ox
        y = rect.y + oy
        w, h = rect.w, rect.h

        if self.state == "gone":
            # 只留一圈虚线：告诉玩家"这里本来是块砖，会再长回来"，
            # 而不是一个看不出所以然的大洞。
            for i in range(0, w, 12):
                pygame.draw.line(surface, (208, 202, 190),
                                 (x + i, y + h), (x + min(i + 6, w), y + h), 1)
            return

        if self.state == "crack":
            # 抖：抖动幅度随剩余时间变大，快塌的时候最明显
            k = 1.0 - max(0.0, self.timer) / max(1e-6, config.BRICK_CRACK_TIME)
            dx = int(round(math.sin(self.t * 46.0) * config.BRICK_SHAKE * k))
        else:
            dx = 0
        surf_x = x + dx

        pygame.draw.rect(surface, config.COLOR_GROUND, (surf_x, y, w, h))
        # 四面描边：这是它和真地面唯一的区别。真地面只在临空侧画线。
        pygame.draw.line(surface, config.COLOR_INK, (surf_x, y + 1),
                         (surf_x + w, y + 1), 3)
        pygame.draw.line(surface, config.COLOR_INK, (surf_x, y + h - 1),
                         (surf_x + w, y + h - 1), 3)
        pygame.draw.line(surface, config.COLOR_INK, (surf_x + 1, y + 1),
                         (surf_x + 1, y + h - 1), 2)
        pygame.draw.line(surface, config.COLOR_INK, (surf_x + w - 2, y + 1),
                         (surf_x + w - 2, y + h - 1), 2)

        # 板面上的两道浅纹：不管塌没塌，都在暗示"这是拼上去的"。
        # 位置按格子做一点确定性偏移，免得一整排砖看起来像盖章盖出来的。
        k = _hash01(self.col, self.row)
        for base in (0.26, 0.58):
            cx = surf_x + int(w * (base + 0.14 * k))
            pygame.draw.line(surface, (214, 209, 198),
                             (cx, y + 4), (cx + 5, y + h - 4), 1)
        if self.state == "crack":
            # 裂纹：从左上往右下劈开，比颤抖更直接
            cx = surf_x + w // 2
            pygame.draw.line(surface, config.COLOR_INK, (cx - 7, y + 2),
                             (cx + 2, y + h - 3), 2)
            pygame.draw.line(surface, config.COLOR_INK, (cx + 2, y + h - 3),
                             (cx + 9, y - 1), 2)


class DropSpike(object):
    """天花板落刺：收在顶上，人一走近就扎下来。

    规则一句话：**别停在这根刺下面**。
    从触发到扎到地上约 0.55 秒，而全速跑过去只需要 0.52 秒——刚好擦着
    它的边过去。停下、慢走、回头，都会挨这一下。

    线索三层，一层比一层明显：平时只有顶上一道 1px 黑线；进入触发距离
    开始抖并掉灰；落下时带一道竖直的拖影。
    """

    def __init__(self, cx, top_y, ground_y):
        self.cx = float(cx)
        self.top_y = float(top_y)
        self.ground_y = float(ground_y)
        self.state = "idle"      # idle → warn → fall → hold → retract
        self.timer = 0.0
        self.tip = self.top_y
        self.armed = True
        self.t = 0.0

    # ---- 运行期 ----
    def reset(self):
        self.state = "idle"
        self.timer = 0.0
        self.tip = self.top_y
        self.armed = True
        self.t = 0.0

    def update(self, dt, player=None):
        self.t += dt
        if self.state == "idle":
            if player is None:
                return None
            d = abs(player.rect.centerx - self.cx)
            if not self.armed:
                # 走远了才重新上膛：否则站在刺旁边会被反复砸，像卡住了
                if d > config.SPIKE_TRIGGER + config.TILE:
                    self.armed = True
                return None
            if d <= config.SPIKE_TRIGGER:
                self.state = "warn"
                self.timer = config.SPIKE_WARN
                self.armed = False
            return None

        self.timer -= dt
        if self.state == "warn":
            if self.timer <= 0.0:
                self.state = "fall"
        elif self.state == "fall":
            self.tip += config.SPIKE_FALL_SPEED * dt
            if self.tip >= self.ground_y:
                self.tip = self.ground_y
                self.state = "hold"
                self.timer = config.SPIKE_HOLD
        elif self.state == "hold":
            if self.timer <= 0.0:
                self.state = "retract"
        elif self.state == "retract":
            self.tip -= (self.ground_y - self.top_y) / config.SPIKE_RETRACT * dt
            if self.tip <= self.top_y:
                self.tip = self.top_y
                self.state = "idle"
                self.timer = config.SPIKE_COOLDOWN
        return None

    def hitbox(self):
        # 只有"扎下来"和"钉在地上"这两段有判定。收回去的过程不判，
        # 免得玩家明明在往上跑却被一把正在收起的刺判死。
        if self.state not in ("fall", "hold"):
            return None
        h = config.SPIKE_HEAD_H
        return pygame.Rect(int(self.cx - config.SPIKE_HALF_W),
                           int(self.tip - h),
                           config.SPIKE_HALF_W * 2, h)

    def hits(self, rect):
        box = self.hitbox()
        return box is not None and rect.colliderect(box)

    # ---- 绘制 ----
    def draw(self, surface, ox, oy):
        cx = int(self.cx) + ox
        top = int(self.top_y) + oy
        tip = int(self.tip) + oy

        if self.state == "idle":
            # 收在天花板里：一道黑线 + 三颗小齿。看得见，但不碍眼。
            pygame.draw.line(surface, config.COLOR_INK, (cx - 15, top + 1),
                             (cx + 15, top + 1), 2)
            for dx in (-11, 0, 11):
                pygame.draw.line(surface, config.COLOR_INK,
                                 (cx + dx, top + 1), (cx + dx, top + 5), 2)
            return

        if self.state == "warn":
            # 抖 + 掉灰：抖是"要来了"，掉灰是"它已经在动了"
            shake = int(round(math.sin(self.t * 62.0) * 2.0))
            sx = cx + shake
            pygame.draw.line(surface, config.COLOR_INK, (sx - 15, top + 1),
                             (sx + 15, top + 1), 2)
            for dx in (-11, 0, 11):
                pygame.draw.line(surface, config.COLOR_INK,
                                 (sx + dx, top + 1), (sx + dx, top + 5), 2)
            for i in range(3):
                k = ((self.t * 60.0 + i * 9.0) % 26.0)
                pygame.draw.circle(surface, (198, 190, 178),
                                   (cx + (i - 1) * 7, top + 6 + int(k)), 1)
            return

        head_h = config.SPIKE_HEAD_H
        # 杆：两根细线夹一条浅色，比一根粗线更像"铁杆"
        if tip - head_h > top:
            pygame.draw.line(surface, (150, 144, 134), (cx - 3, top),
                             (cx - 3, tip - head_h + 4), 2)
            pygame.draw.line(surface, (150, 144, 134), (cx + 3, top),
                             (cx + 3, tip - head_h + 4), 2)
        if self.state == "fall":
            for k in range(3):
                y0 = tip - head_h - 6 - k * 9
                pygame.draw.line(surface, (206, 198, 186),
                                 (cx, y0), (cx, y0 - 6), 2)
        # 刺头：倒三角，尖端朝下
        pts = [(cx - config.SPIKE_HALF_W, tip - head_h),
               (cx + config.SPIKE_HALF_W, tip - head_h),
               (cx, tip)]
        pygame.draw.polygon(surface, (150, 144, 134), pts)
        pygame.draw.polygon(surface, config.COLOR_INK, pts, 2)


class RisingWall(object):
    """突墙：地上一道槽，人走近就"长"出一堵墙，挡住去路。

    140px 高，比跳高（127px）高一截，**跳不过去**——这是它存在的理由。
    能跳过去的话它只是个"多按一下跳"的台阶。

    它不杀人，只拦路：升起 0.12 秒、停 0.75 秒、缩回 0.22 秒。
    所以它考的是"别抢"：看见地上那道槽就知道该收脚，等一下它自己就下去了。
    和落刺（不许停）刚好相反——两种规则交替出现，玩家才需要读路。

    防夹人：升起过程中一旦发现玩家在墙的位置，立刻转成缩回。
    宁可让它"没能升起来"，也不能把人卡进墙里——那是唯一会让人卡死的错。
    """

    def __init__(self, cx, floor_y):
        self.cx = float(cx)
        self.floor_y = float(floor_y)
        self.h = 0.0
        self.state = "idle"      # idle → rise → hold → retract → wait
        self.timer = 0.0
        self.armed = True
        self.t = 0.0

    # ---- 运行期 ----
    def reset(self):
        self.h = 0.0
        self.state = "idle"
        self.timer = 0.0
        self.armed = True
        self.t = 0.0

    def rect(self):
        h = int(max(0.0, self.h))
        return pygame.Rect(int(self.cx - config.WALL_THICK * 0.5),
                           int(self.floor_y - h),
                           config.WALL_THICK, h)

    def column(self):
        """墙**完全升起时**占的那一块。用来判断"人是不是正站在槽上"。

        不能拿 rect() 判断：还没升起来时它高度是 0，`rect.h <= 0` 一律不算
        重叠，于是人会站在槽上被墙顶起来。这里直接按满高算。
        """
        return pygame.Rect(int(self.cx - config.WALL_THICK * 0.5),
                           int(self.floor_y - config.WALL_H),
                           config.WALL_THICK, config.WALL_H)

    def solid(self):
        if self.state == "rise":
            # 刚冒头的那几帧不挡人：26px 都不到，挡了也只是把人绊一下，
            # 反而容易出现"人被卡在刚长出来的墙里"。真夹住时下面还有一道
            # abort 兜底。
            return self.rect() if self.h >= config.WALL_READY_H else None
        if self.state in ("hold", "retract"):
            # 缩回去的过程中一直是实心的，直到真的没了为止。
            # 半截墙还能穿过去的话，画面上会像"人从石头里走过去"。
            return self.rect() if self.h >= 4 else None
        return None

    def update(self, dt, player=None):
        self.t += dt
        if self.state == "idle":
            if player is None:
                return None
            d = abs(player.rect.centerx - self.cx)
            if not self.armed:
                if d > config.WALL_TRIGGER + config.TILE:
                    self.armed = True
                return None
            if d > config.WALL_TRIGGER:
                return None
            if self.column().colliderect(player.rect):
                # 人就站在槽上：先不打搅，等他走开。用"满高"的柱子判断，
                # 这样一开始就不会升，而不是升到一半再缩回去（那会抽搐）。
                return None
            self.state = "rise"
            self.armed = False
            return None

        if self.state == "rise":
            self.h += config.WALL_H / config.WALL_RISE * dt
            if self.h >= config.WALL_H:
                self.h = config.WALL_H
                self.state = "hold"
                self.timer = config.WALL_HOLD
            elif self._overlaps_player(player, 2.0):
                # 夹人预警：立刻放弃
                self.state = "retract"
            return None

        if self.state == "hold":
            self.timer -= dt
            if self.timer <= 0.0:
                self.state = "retract"
            return None

        if self.state == "retract":
            self.h -= config.WALL_H / config.WALL_RETRACT * dt
            if self.h <= 0.0:
                self.h = 0.0
                self.state = "wait"
                self.timer = config.WALL_COOLDOWN
            return None

        # wait：缩回去之后歇一下，避免"刚落下又升起"的抽搐
        self.timer -= dt
        if self.timer <= 0.0:
            self.state = "idle"
        return None

    def _overlaps_player(self, player, slack):
        if player is None:
            return False
        r = self.rect()
        if r.h <= 0:
            return False
        if slack:
            r = r.inflate(int(slack * 2), int(slack * 2))
        return r.colliderect(player.rect)

    # ---- 绘制 ----
    def draw(self, surface, ox, oy):
        cx = int(self.cx) + ox
        fy = int(self.floor_y) + oy
        half = config.WALL_THICK // 2

        # 槽：地板上挖出来的一道缺口（用纸色盖掉地面线再勾边）。
        # 这是"这里有机关"唯一的预告，必须一眼能找到——画成一条压在墨线上的
        # 深色条会糊成"地面线加粗了"，那等于没有线索。
        slot = pygame.Rect(cx - half, fy - 6, half * 2, 7)
        pygame.draw.rect(surface, config.COLOR_PAPER, slot)
        pygame.draw.rect(surface, (156, 149, 138), slot, 1)
        for dx in (-half + 4, half - 4):
            pygame.draw.line(surface, (156, 149, 138),
                             (slot.x + dx, slot.y + 1),
                             (slot.x + dx, slot.bottom - 1), 1)

        if self.h <= 0.5:
            return
        r = self.rect()
        x, y = r.x + ox, r.y + oy
        # 墙面比地面白一点点（线索），边线是实墨
        pygame.draw.rect(surface, (255, 254, 250), (x, y, r.w, r.h))
        pygame.draw.rect(surface, config.COLOR_INK, (x, y, r.w, r.h), 2)
        # 横纹：石砌墙的感觉，也让"它在动"更容易看出来
        step = 18
        yy = y + step
        while yy < y + r.h - 4:
            pygame.draw.line(surface, (222, 217, 206), (x + 3, yy),
                             (x + r.w - 4, yy), 1)
            yy += step
        # 顶面加一道压顶线：墙是从地里顶出来的，顶上该有个"帽"
        pygame.draw.line(surface, config.COLOR_INK, (x, y + 3),
                         (x + r.w, y + 3), 2)


class TwinRock(object):
    """二连落石：一近一远，远的那块影子**先**收拢。

    这是四种机关里唯一"不靠手速、靠观察"的那一个：两道影子同时出现，
    近的那道慢、远的那道快，于是唯一安全的位置是两块之间那一格。
    玩家要么读出来站进去，要么一口气冲过去（0.9 秒内穿过 2 格）。

    影子先出现这件事本身是设计的一部分，README §6.3 里写了
    "第二块的影子先出现"——它把"这是连招"这件事提前告诉你。
    """

    def __init__(self, cx, top_y, gap):
        self.cx = float(cx)
        self.top_y = float(top_y)
        self.gap = float(gap)
        self.armed = True
        self.timer = 0.0
        self.t = 0.0

    # ---- 运行期 ----
    def reset(self):
        self.armed = True
        self.timer = 0.0
        self.t = 0.0

    def update(self, dt, player=None):
        self.t += dt
        if self.timer > 0.0:
            self.timer -= dt
            return None
        if player is None:
            return None
        d = abs(player.rect.centerx - self.cx)
        if not self.armed:
            if d > config.TWIN_TRIGGER + config.TILE:
                self.armed = True
            return None
        if d > config.TWIN_TRIGGER:
            return None
        self.armed = False
        self.timer = config.TWIN_COOLDOWN
        y = self.top_y + config.ROCK_SIZE * 0.5
        return ("twin", (self.cx, y), (self.cx + self.gap, y))

    # ---- 绘制 ----
    def draw(self, surface, ox, oy):
        # 两道裂缝。就算石头的影子还没出现，玩家也能先看见"这条路上
        # 有两个裂缝"——这是它比单块落石更值得读的地方。
        for i, dx in enumerate((0.0, self.gap)):
            cx = int(self.cx + dx) + ox
            y = int(self.top_y) + oy
            for k, ox2 in enumerate((-6, 0, 7)):
                pygame.draw.line(surface, (150, 144, 134),
                                 (cx + ox2, y + 1),
                                 (cx + ox2 + 2, y + 9 + k % 2 * 3), 2)
