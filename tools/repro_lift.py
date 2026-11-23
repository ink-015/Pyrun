# -*- coding: utf-8 -*-
"""复现：在升降台附近"一直挤右 + 一直跳"，看玩家会不会被瞬移到高台上。

模拟方式贴近真人：从右边地面跑过来，一路按住右并周期性起跳，
只要检测到单帧竖直位移超过物理上限（下落最快 18.3px、跳起最快 10.7px）
或者玩家矩形突然整块跨过高台顶面，就打印当时的完整状态。
"""
from __future__ import print_function

import os
import sys

import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import scenes

LDEGE_TOP = 448.0


def main():
    pygame.init()
    pygame.display.set_mode((960, 540), 0, 32)

    class _App(object):
        level_path = os.path.join(config.LEVEL_DIR, "l2.txt")

    scene = scenes.GameScene(_App())
    scene.on_enter()
    plat = [p for p in scene.world.platforms if p.axis == "y"][0]
    p = scene.player
    # 从平台左边 3 格的地面上出发
    p.teleport(plat.rect.left - 3 * config.TILE, 640 - p.HEIGHT)
    scene.camera.snap_to(p.rect)
    print("平台 origin=%s  行程 %.0f  高台顶 %.0f" % (plat.origin, plat.travel, LDEGE_TOP))

    period = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    prev = None
    bad = 0
    max_dy = 0.0

    for frame in range(2400):
        inp = scene.input
        if frame % period == 0:
            inp.jump_pressed = True
            inp.jump_held = True
            inp.jump_released = False
        elif frame % period == 7:
            inp.jump_held = False
            inp.jump_released = True
        scene.override_axis = 1.0
        scene.update(config.FIXED_DT)
        scene.override_axis = None

        dy = p.y - prev if prev is not None else 0.0
        max_dy = max(max_dy, abs(dy))
        if abs(dy) > 19.0:
            bad += 1
            if bad <= 12:
                print("!! f=%4d  y %.1f -> %.1f (dy %+.1f)  vy %+.0f  ground=%s"
                      "  平台顶 %3d  脚底 %.1f  x %.1f"
                      % (frame, prev, p.y, dy, p.vy, p.on_ground,
                         plat.rect.top, p.rect.bottom, p.x))
        prev = p.y

    print("---- 共 2400 帧：异常 %d 帧，最大单帧 |dy| = %.1f px" % (bad, max_dy))
    print("结束位置 x=%.1f 脚底=%.1f（高台顶 %.0f）" % (p.x, p.rect.bottom, LDEGE_TOP))


if __name__ == "__main__":
    main()
