# -*- coding: utf-8 -*-
"""试跑 l2 的移动平台段，找一组能过的输入节奏。

不是正式测试，只是确认"这段关卡在给定的手感参数下确实能过"，
顺便看清失败时到底卡在哪一步。做法模仿真实玩家：先跑到岸边，
再起跳，落到平台上后松手，等平台到远端再走上岸。
"""

import os
import sys

import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import player
import scenes


class App(object):
    def __init__(self, screen):
        self.screen = screen
        self.running = True

    def quit(self):
        self.running = False


def one_try(hold_frames, jump_x, start_delta):
    pygame.init()
    screen = pygame.display.set_mode((config.WIDTH, config.HEIGHT), 0, 32)
    app = App(screen)
    app.level_path = os.path.join(config.LEVEL_DIR, "l2.txt")
    scene = scenes.GameScene(app)
    scene.on_enter()

    plat = [p for p in scene.world.platforms if p.axis == "x"][0]
    p = scene.player
    p.teleport(36 * config.TILE - player.Player.WIDTH,
               10 * config.TILE - player.Player.HEIGHT)

    def step(n=1):
        for _ in range(n):
            scene.update(config.FIXED_DT)

    step(2)
    # 等到平台往回走到 offset ≈ start_delta 时开始助跑
    for _ in range(600):
        if plat.offset <= start_delta:
            break
        step()

    scene.override_axis = 1.0
    frames = 0
    while p.x < jump_x and frames < 90:
        step()
        frames += 1
    scene.input.jump_pressed = True
    scene.input.jump_held = True
    step(hold_frames)
    scene.input.jump_held = False
    scene.input.jump_released = True

    # 等落地
    for _ in range(60):
        step()
        if p.on_ground:
            break
    board = p.on_ground and abs(p.rect.bottom - plat.rect.top) <= 2
    if not board:
        return (False, u"没落到平台上（x=%.0f feet=%.0f 平台[%d,%d] deaths=%d）"
                % (p.x, p.rect.bottom, plat.rect.left, plat.rect.right,
                   scene.deaths))

    scene.override_axis = 0.0
    for _ in range(600):
        if plat.offset >= config.PLATFORM_TRAVEL - 1.0:
            break
        step()
    scene.override_axis = 1.0
    step(80)
    ok = p.x > 42 * config.TILE and p.on_ground
    return (ok, u"x=%.0f feet=%.0f deaths=%d ground=%s"
            % (p.x, p.rect.bottom, scene.deaths, p.on_ground))


def main():
    for hold in (2, 3, 6, 10):
        for start in (0.0, 20.0, 40.0):
            ok, msg = one_try(hold, 2360, start)
            print(u"hold=%-2d start=%-5.0f %s  %s"
                  % (hold, start, "PASS" if ok else "FAIL", msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
