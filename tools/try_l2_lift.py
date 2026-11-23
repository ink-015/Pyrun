# -*- coding: utf-8 -*-
"""验证原本的通路没被修坏：站上升降台 -> 被送到顶 -> 走上高台。

顺带盯死全程没有超过物理上限的单帧位移。
"""
from __future__ import print_function

import os
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
    lift = [p for p in scene.world.platforms if p.axis == "y"][0]
    p = scene.player
    p.teleport(lift.rect.centerx - p.WIDTH // 2, lift.rect.top - p.HEIGHT)
    scene.camera.snap_to(p.rect)

    prev = p.y
    worst = 0.0
    # 1) 站住：让它落到台面上
    for _ in range(12):
        scene.update(config.FIXED_DT)
        worst = max(worst, abs(p.y - prev))
        prev = p.y
    print("站上台面：脚底 %.1f  台面 %d  ground=%s"
          % (p.rect.bottom, lift.rect.top, p.on_ground))

    # 2) 全程不按，跟着平台上升，盯到行程终点
    for _ in range(600):
        scene.update(config.FIXED_DT)
        worst = max(worst, abs(p.y - prev))
        prev = p.y
        if lift.offset >= lift.travel - 0.5:
            break
    top_feet = p.rect.bottom
    print("升到顶：脚底 %.1f（高台顶 448）  ground=%s  最大单帧 %.1f px"
          % (top_feet, p.on_ground, worst))

    # 3) 往右走上高台
    scene.override_axis = 1.0
    for _ in range(40):
        scene.update(config.FIXED_DT)
        worst = max(worst, abs(p.y - prev))
        prev = p.y
    scene.override_axis = None
    print("走上高台：x=%.1f 脚底 %.1f  ground=%s  最大单帧 %.1f px"
          % (p.x, p.rect.bottom, p.on_ground, worst))
    ok = abs(p.rect.bottom - 448) <= 2 and p.x > 46 * config.TILE
    print("结论：" + ("通过" if ok else "失败"))


if __name__ == "__main__":
    main()
