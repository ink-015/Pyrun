# -*- coding: utf-8 -*-
"""随机输入压力测试：在升降台附近乱按，抓两类异常。

  1. 单帧竖直位移明显超过物理上限（说明有硬解算在"瞬移"）
  2. 玩家矩形陷进静态地形内部（穿模，下一帧必被弹出去）

后者是根因候选：一旦嵌进高台，下一次下落就会按"落到顶面"处理，
把人整块吸到台面上，看起来就是瞬移。
"""
from __future__ import print_function

import os
import random
import sys

import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import scenes


def main():
    pygame.init()
    pygame.display.set_mode((960, 540), 0, 32)

    class _App(object):
        level_path = os.path.join(config.LEVEL_DIR, "l2.txt")

    scene = scenes.GameScene(_App())
    scene.on_enter()
    plat = [p for p in scene.world.platforms if p.axis == "y"][0]
    p = scene.player
    p.teleport(plat.rect.left - 1 * config.TILE, 640 - p.HEIGHT)
    scene.camera.snap_to(p.rect)

    rnd = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
    prev_y = p.y
    snaps = 0
    embeds = 0
    worst = 0.0
    shown = 0
    hist = []

    for frame in range(20000):
        inp = scene.input
        inp.jump_held = False
        inp.jump_released = False
        scene.override_axis = float(rnd.choice((1, 1, 1, 0, -1)))
        if rnd.random() < 0.10:
            inp.jump_pressed = True
            inp.jump_held = True
        if rnd.random() < 0.10:
            inp.jump_released = True
        scene.update(config.FIXED_DT)
        scene.override_axis = None

        # 复活后位置会突变，那是正常的，重置基准
        if scene.death_timer > 0.0 or scene.invuln >= config.INVULN_TIME - 1e-6:
            prev_y = p.y
            hist = []
            continue

        r = p.rect
        embedded = any(r.colliderect(s) for s in scene.world.solids)
        dy = p.y - prev_y
        hist.append((frame, p.x, p.y, r.bottom, p.vy, p.on_ground,
                     plat.rect.top, scene.input.jump_pressed,
                     scene.input.jump_held))
        if len(hist) > 24:
            hist.pop(0)
        if embedded:
            embeds += 1
            if embeds <= 8:
                print("## 穿模 f=%4d  rect=%s  vy %+.0f  ground=%s  平台顶 %d"
                      % (frame, r, p.vy, p.on_ground, plat.rect.top))
        # 门限 22px：下落极限 18.3px/帧，落地那一下还要再贴 2px 左右，
        # 20 上下是正常落地；要抓的是几十上百像素的解算瞬移。
        if abs(dy) > 22.0:
            snaps += 1
            worst = max(worst, abs(dy))
            if snaps == 1:
                print("!! 首个瞬移 f=%4d  y %.1f -> %.1f (%+.1f)" % (frame, prev_y, p.y, dy))
                for h in hist:
                    print("     f%4d x=%8.1f y=%7.1f feet=%7.1f vy=%+7.1f g=%d"
                          " plat_top=%3d jp=%d jh=%d"
                          % (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], h[8]))
        prev_y = p.y

    print("---- 20000 帧：穿模 %d 帧，超限瞬移 %d 帧（最大 %.1f px）"
          % (embeds, snaps, worst))


if __name__ == "__main__":
    main()
