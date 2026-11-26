# -*- coding: utf-8 -*-
"""纸面风粒子：落地扬尘、金币碎光、死亡碎块、篝火火星。

为什么自己做而不是找粒子库：整项目只有四种粒子，一共不到两百行；
而且这游戏的粒子必须"像纸上的铅笔屑"——通用库的发光贴图、加法混合
放在 250,247,238 的纸底上会立刻变成另一套美术。

三个刻意的选择：

1. **粒子存成扁平 list，不建类。** 上限 240 个，每帧要遍历两遍（积分 +
   绘制）。对象化的写法读起来漂亮，但在海龟机的 Python 3.6 上，240 个
   小对象的属性访问比 list 下标慢一倍多。
2. **颜色向纸色淡出，而不是改 alpha。** 每个粒子每帧新建 SRCALPHA 表面
   再 set_alpha，是这个量级里最贵的一种画法（每帧几百次内存分配）。
   这里把颜色按剩余寿命插值到纸色，视觉上同样是"淡掉"，成本是三次乘法。
3. **重力按类型分开。** 尘埃要"飘一下就没"，碎块要"砸下去"，火星要
   往上。统一重力的话，四种粒子看起来是同一种东西换了颜色。
"""

import random

import pygame

import config

MAX_PARTICLES = 240

# n / 速度范围 / 向上初速 / 寿命 / 线长 / 颜色 / 阻力 / 重力
SPEC = {
    # 扬尘往两侧铺、只往上飘一点点：落地是"压下去"，不是"炸开"。
    # 起点抬离地面 6px —— 正好踩在地面线上时，3px 的短线会被地面的
    # 锯齿黑线吃掉，等于没画。
    "dust": dict(n=12, speed=(90, 240), up=(30, 95), life=(0.26, 0.46),
                 size=4, color=(172, 165, 152), drag=2.4, gravity=420.0,
                 jitter=14.0),
    "spark": dict(n=8, speed=(70, 200), up=(70, 190), life=(0.22, 0.42),
                  size=2, color=config.COLOR_COIN, drag=1.4, gravity=620.0),
    # 碎块要"看得见"：13 个、线长 3 的时候只有凑近才注意得到，
    # 而它承担的是"这一下很重"的全部视觉表达。
    "debris": dict(n=16, speed=(100, 290), up=(130, 350), life=(0.35, 0.70),
                   size=4, color=(40, 38, 34), drag=0.7, gravity=1500.0,
                   jitter=9.0),
    "ember": dict(n=5, speed=(8, 34), up=(55, 110), life=(0.35, 0.75),
                  size=2, color=config.COLOR_CAMP, drag=1.6, gravity=-90.0),
}


class Particles(object):
    """一个关卡内的粒子池。死亡重开不必清空——粒子几帧就没了。"""

    def __init__(self):
        # [x, y, vx, vy, life, life0, size, (r,g,b), drag, gravity]
        self.items = []
        self.dropped = 0          # 因上限被丢掉的粒子数，调试用

    def clear(self):
        self.items = []

    def burst(self, kind, x, y, spread=1.0):
        """在 (x, y) 炸开一簇粒子。未知类型直接忽略（不抛）。"""
        spec = SPEC.get(kind)
        if spec is None:
            return 0
        room = MAX_PARTICLES - len(self.items)
        n = spec["n"]
        if room <= 0:
            self.dropped += n
            return 0
        n = min(n, room)
        lo, hi = spec["speed"]
        ulo, uhi = spec["up"]
        llo, lhi = spec["life"]
        col = spec["color"]
        for _ in range(n):
            # 水平方向左右各一半：单向发射会看起来像"被风吹"，而落地扬尘
            # 和碎块都该是圆的。
            vx = random.uniform(lo, hi) * (1 if random.random() < 0.5 else -1)
            vy = -random.uniform(ulo, uhi)
            jitter = spec.get("jitter", 6.0) * spread
            self.items.append([
                float(x) + random.uniform(-jitter, jitter),
                float(y) + random.uniform(-jitter * 0.4, jitter * 0.4),
                vx * spread, vy * spread,
                random.uniform(llo, lhi), 0.0,
                spec["size"], col, spec["drag"], spec["gravity"],
            ])
            self.items[-1][5] = self.items[-1][4]     # life0 = life
        return n

    def update(self, dt):
        if not self.items:
            return
        alive = []
        for p in self.items:
            p[4] -= dt
            if p[4] <= 0.0:
                continue
            p[3] += p[9] * dt
            # 阻力用指数：帧率稳定时和"每帧乘系数"等价，但换帧率不会变味
            damp = max(0.0, 1.0 - p[8] * dt)
            p[2] *= damp
            p[3] *= damp
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            alive.append(p)
        self.items = alive

    def draw(self, surface, ox, oy):
        """ox/oy 是 camera.offset（世界 -> 屏幕）。"""
        if not self.items:
            return
        w, h = surface.get_size()
        paper = config.COLOR_PAPER
        for p in self.items:
            x = int(p[0]) + ox
            y = int(p[1]) + oy
            if x < -8 or x > w + 8 or y < -8 or y > h + 8:
                continue
            a = p[4] / p[5] if p[5] > 0.0 else 0.0
            r, g, b = p[7]
            # 向纸色插值 = 淡出。不做 alpha 表面：见文件头第 2 条。
            col = (int(r * a + paper[0] * (1.0 - a)),
                   int(g * a + paper[1] * (1.0 - a)),
                   int(b * a + paper[2] * (1.0 - a)))
            # 沿速度方向画一条短线，比圆点更像"被甩出去的碎屑"
            vx, vy = p[2], p[3]
            ln = p[6]
            mag = (vx * vx + vy * vy) ** 0.5
            if mag > 1.0:
                dx = vx / mag * ln
                dy = vy / mag * ln
            else:
                dx = 0.0
                dy = -ln
            pygame.draw.line(surface, col, (x, y),
                             (int(x + dx), int(y + dy)), 2)

    @property
    def count(self):
        return len(self.items)
