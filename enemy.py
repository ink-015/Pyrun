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
