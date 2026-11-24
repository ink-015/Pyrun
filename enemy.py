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

    def __init__(self, x, y, ground_y):
        self.x = float(x)
        self.y = float(y)
        self.ground_y = float(ground_y)
        self.state = "warn"
        self.warn = config.ROCK_WARN_TIME
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
            ratio = max(0.0, self.warn / max(1e-6, config.ROCK_WARN_TIME))
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
