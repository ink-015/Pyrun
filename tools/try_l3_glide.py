# -*- coding: utf-8 -*-
"""试跑第 3 关的滑翔段：验证「有伞能过、没伞必死」。

这不是自检（自检在 selftest.py 里），而是一个单人调试脚本，
用来在改关卡数值后快速看一遍轨迹：每次死亡/落地的时间点、落点 x。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

import config
import scenes


class _App(object):
    level_path = os.path.join(config.LEVEL_DIR, "l3.txt")


def run(glider=True, label=""):
    scene = scenes.GameScene(_App())
    scene.on_enter()
    p = scene.player
    w = scene.world

    # 站到起跳台上（顶面 384），起点离边缘留一格助跑
    p.teleport(19 * config.TILE, 6 * config.TILE - p.HEIGHT)
    p.has_glider = glider
    scene.camera.snap_to(p.rect)
    for _ in range(3):
        scene.update(config.FIXED_DT)

    scene.override_axis = 1.0
    scene.input.jump_held = glider      # 有伞就按住空格：不按=不会滑翔
    peak = 9999.0
    land = None
    airborne = False
    for f in range(300):
        scene.update(config.FIXED_DT)
        peak = min(peak, p.y)
        if scene.deaths:
            land = ("死", f, p.x)
            break
        if not p.on_ground:
            airborne = True          # 已经离开起跳台，之后的落地才算"落地"
        elif airborne:
            land = ("落", f, p.x)
            break
    scene.override_axis = None
    if land is None:
        land = ("未完", 300, p.x)

    print("=== %s（伞=%s）===" % (label, glider))
    print("  结果 %s  帧 %d  落点 x=%.0f（对岸 29 列 = %d）"
          % (land[0], land[1], land[2], 29 * config.TILE))
    print("  死亡 %d  滑翔 %d 帧  vy=%.0f  vx=%.0f"
          % (scene.deaths, p.glide_frames, p.vy, p.vx))
    return scene, p, land


def main():
    if not pygame.get_init():
        pygame.init()
        pygame.display.set_mode((config.WIDTH, config.HEIGHT), 0, 32)
    s1, p1, r1 = run(True, "滑翔")
    s2, p2, r2 = run(False, "不按空格")
    ok = r1[0] == "落" and r1[2] > 29 * config.TILE and s1.deaths == 0
    bad = r2[0] == "死"
    print("")
    print(" 能过：%s   没伞会死：%s" % ("是" if ok else "否", "是" if bad else "否"))
    return 0 if (ok and bad) else 1


if __name__ == "__main__":
    sys.exit(main())
