# -*- coding: utf-8 -*-
"""分阶段自检。入口：python main.py --selftest

M1 场景部分需要真实 Display（要渲染一帧）；
M2 物理部分是纯逻辑，只操作 Player + Rect，不读键盘、不画图，
所以土狼时间、跳跃缓冲这类"靠帧数才测得准"的东西可以精确断言。

每条断言都对应 README §19 的某一项验收，不许靠手感。
"""

import pygame

import config
import player
import scenes

DT = config.FIXED_DT
RESULTS = []


def _check(name, cond, detail=""):
    RESULTS.append((bool(cond), name, detail))
    print(u"  [%s] %-26s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


def _section(title):
    print("")
    print(u"--- %s ---" % title)


# ---------------------------------------------------------------- 世界构造

def _flat():
    """只有地面，用于纯粹的移动/跳跃测试，避免被其他平台挡住。"""
    return [pygame.Rect(0, 460, config.WIDTH, 80)]


def _box_world():
    """M2 验收地形，与 GameScene 保持一致。"""
    return [
        pygame.Rect(0, 460, config.WIDTH, 80),
        pygame.Rect(170, 380, 140, 20),
        pygame.Rect(380, 330, 140, 20),
        pygame.Rect(600, 380, 140, 20),
        pygame.Rect(760, 380, 26, 80),
        pygame.Rect(850, 290, 100, 20),
    ]


def _idle():
    return player.InputState()


def _land(p, solids, frames=8):
    idle = _idle()
    for _ in range(frames):
        p.update(DT, idle, solids)
    return p.on_ground


# ---------------------------------------------------------------- M1 场景

def _key(key):
    return pygame.event.Event(pygame.KEYDOWN, {"key": key, "mod": 0})


def test_scenes(app):
    _section(u"M1 场景系统")

    _check(u"启动进入菜单", app.scenes.current_name == "menu",
           u"当前=%s" % app.scenes.current_name)

    app.scenes.draw(app.screen)
    pygame.display.flip()
    _check(u"菜单可渲染", True, u"已绘制一帧")

    app.scenes.handle_events([_key(pygame.K_RETURN)])
    _check(u"Enter 进入游戏", app.scenes.current_name == "game",
           u"当前=%s" % app.scenes.current_name)

    for _ in range(30):
        app.scenes.update(DT)
    p = app.scenes.current.player
    _check(u"场景内玩家已落地", p is not None and p.on_ground,
           u"on_ground=%s y=%.1f" % (p.on_ground if p else None, p.y if p else -1))

    app.scenes.draw(app.screen)
    pygame.display.flip()
    _check(u"游戏场景可渲染", True, u"已绘制一帧")

    app.scenes.handle_events([_key(pygame.K_ESCAPE)])
    _check(u"Esc 返回菜单", app.scenes.current_name == "menu",
           u"当前=%s" % app.scenes.current_name)

    menu = app.scenes.current
    app.scenes.handle_events([_key(pygame.K_DOWN)])
    _check(u"方向键切换选项", menu.index == 1, u"index=%d" % menu.index)

    app.scenes.handle_events([_key(pygame.K_UP)])
    _check(u"方向键可回退", menu.index == 0, u"index=%d" % menu.index)

    _check(u"窗口唯一且 32 位", app.screen.get_bitsize() == 32,
           u"%dx%d / %d 位" % (app.screen.get_width(), app.screen.get_height(),
                               app.screen.get_bitsize()))


# ---------------------------------------------------------------- M2 物理

def test_move():
    _section(u"M2 水平移动")

    w = _flat()
    p = player.Player(100, 390)
    _land(p, w)

    inp = _idle()
    inp.axis = 1.0
    for _ in range(40):
        p.update(DT, inp, w)
    v_top = p.vx
    _check(u"加速到速度上限", v_top >= config.RUN_SPEED * 0.98,
           u"vx=%.1f / 上限 %.0f" % (v_top, config.RUN_SPEED))

    inp.axis = 0.0
    p.update(DT, inp, w)
    v_one = p.vx
    _check(u"松开后渐进减速", 0.0 < v_one < v_top,
           u"1 帧后 vx=%.1f（原 %.1f）" % (v_one, v_top))

    for _ in range(40):
        p.update(DT, inp, w)
    _check(u"最终完全停住", abs(p.vx) < 1e-9, u"vx=%.4f" % p.vx)

    # 左方向
    p2 = player.Player(500, 390)
    _land(p2, w)
    inp2 = _idle()
    inp2.axis = -1.0
    for _ in range(30):
        p2.update(DT, inp2, w)
    _check(u"反向（左）可移动", p2.vx < -config.RUN_SPEED * 0.98 and p2.facing == -1,
           u"vx=%.1f facing=%+d" % (p2.vx, p2.facing))


def test_jump_basic():
    _section(u"M2 跳跃基础")

    w = _flat()
    p = player.Player(100, 390)
    _land(p, w)
    y0 = p.y

    inp = _idle()
    inp.jump_pressed = True
    inp.jump_held = True
    p.update(DT, inp, w)
    _check(u"空格起跳", p.vy < -100.0 and p.y < y0,
           u"vy=%.1f  dy=%.2f" % (p.vy, p.y - y0))

    # 空中再按不应二段跳
    j1 = p.jump_count
    for _ in range(3):
        p.update(DT, inp, w)
    again = _idle()
    again.jump_pressed = True
    again.jump_held = True
    p.update(DT, again, w)
    _check(u"空中不可二段跳", p.jump_count == j1,
           u"jumps %d -> %d" % (j1, p.jump_count))

    # 松手切跳
    p2 = player.Player(100, 390)
    _land(p2, w)
    i2 = _idle()
    i2.jump_pressed = True
    i2.jump_held = True
    p2.update(DT, i2, w)
    vy_before = p2.vy
    i2.jump_held = False
    i2.jump_released = True
    p2.update(DT, i2, w)
    _check(u"松开立即削弱上升", p2.vy > vy_before,
           u"vy %.1f -> %.1f" % (vy_before, p2.vy))


def _jump_height(hold_frames):
    """按住 hold_frames 帧后松手，返回本次跳跃达到的最大高度。"""
    w = _flat()
    p = player.Player(100, 390)
    _land(p, w)
    start_y = p.y
    inp = _idle()
    inp.jump_pressed = True
    inp.jump_held = True
    p.update(DT, inp, w)
    top = p.y
    released = False
    for i in range(1, 160):
        if not released and i >= hold_frames:
            inp.jump_held = False
            inp.jump_released = True
            released = True
        p.update(DT, inp, w)
        if p.y < top:
            top = p.y
    return start_y - top


def test_variable_jump():
    _section(u"M2 可变跳高")
    h_short = _jump_height(2)
    h_mid = _jump_height(12)
    h_long = _jump_height(60)

    _check(u"轻点跳得低", 20.0 < h_short < 70.0, u"高 %.1f px" % h_short)
    _check(u"按住跳得高", h_long > 110.0, u"高 %.1f px" % h_long)
    _check(u"三档高度递增", h_short < h_mid < h_long,
           u"%.1f < %.1f < %.1f" % (h_short, h_mid, h_long))
    _check(u"跳高足以越过 80px 矮墙", h_long > 80.0, u"高 %.1f px" % h_long)


def test_coyote():
    _section(u"M2 土狼时间（离地后仍可起跳）")

    def trial(wait_frames):
        solids = [pygame.Rect(100, 372, 200, 22)]
        p = player.Player(200, 372 - player.Player.HEIGHT)
        if not _land(p, solids):
            return None
        walk = _idle()
        walk.axis = 1.0
        guard = 0
        while p.on_ground and guard < 240:
            p.update(DT, walk, solids)
            guard += 1
        # 此刻刚离开平台边缘
        for _ in range(wait_frames):
            p.update(DT, walk, solids)
        jump = _idle()
        jump.jump_pressed = True
        jump.jump_held = True
        p.update(DT, jump, solids)
        return p.vy < -100.0

    window = config.COYOTE_TIME / DT

    near = trial(2)     # 0.033s，窗口内
    edge = trial(4)     # 0.067s，窗口内
    far = trial(int(window) + 4)   # 超出窗口

    _check(u"离地 0.03s 内可跳", near is True, u"wait=2 帧")
    _check(u"离地 0.07s 内可跳", edge is True, u"wait=4 帧")
    _check(u"离开 %.2fs 后不可跳" % config.COYOTE_TIME, far is False,
           u"wait=%d 帧（窗口 %.1f 帧）" % (int(window) + 4, window))


def test_jump_buffer():
    _section(u"M2 跳跃缓冲（落地前按也能起跳）")

    w = _flat()
    p = player.Player(100, 300)
    idle = _idle()
    frames = 0
    while not p.on_ground and frames < 400:
        p.update(DT, idle, w)
        frames += 1
    land_frames = frames

    def trial(press_before):
        if press_before >= land_frames:
            return None
        q = player.Player(100, 300)
        for _ in range(land_frames - press_before):
            q.update(DT, idle, w)
        jump = _idle()
        jump.jump_pressed = True
        jump.jump_held = True
        q.update(DT, jump, w)
        for _ in range(10):
            if q.vy < -100.0:
                return True
            q.update(DT, idle, w)
        return False

    window = config.JUMP_BUFFER_TIME / DT

    near = trial(2)
    far = trial(int(window) + 6)

    _check(u"落地前 0.03s 按可触发", near is True, u"press_before=2 帧")
    _check(u"落地前过早按不触发", far is False,
           u"press_before=%d 帧（窗口 %.1f 帧）" % (int(window) + 6, window))
    _check(u"落地总帧数合理", 8 < land_frames < 60, u"%d 帧" % land_frames)


def test_collision():
    _section(u"M2 碰撞")

    # 不穿地
    w = _flat()
    p = player.Player(100, -300)
    idle = _idle()
    for _ in range(400):
        p.update(DT, idle, w)
    _check(u"高速下落不穿地", abs(p.y - 390.0) < 1.0,
           u"y=%.2f（应为 390）" % p.y)

    # 不穿墙
    wall = pygame.Rect(760, 380, 26, 80)
    w2 = [pygame.Rect(0, 460, config.WIDTH, 80), wall]
    p2 = player.Player(600, 390)
    _land(p2, w2)
    walk = _idle()
    walk.axis = 1.0
    for _ in range(150):
        p2.update(DT, walk, w2)
    _check(u"撞墙不穿透", p2.rect.right <= wall.left + 1,
           u"right=%d 墙left=%d" % (p2.rect.right, wall.left))

    # 边缘站立不抖
    w3 = [pygame.Rect(100, 372, 200, 22)]
    p3 = player.Player(285, 372 - player.Player.HEIGHT)
    if _land(p3, w3):
        ys = []
        stays = True
        for _ in range(90):
            p3.update(DT, idle, w3)
            ys.append(p3.y)
            if not p3.on_ground:
                stays = False
        span = max(ys) - min(ys)
        _check(u"平台边缘站立不抖", stays and span < 0.5,
               u"y 波动 %.3f px" % span)
    else:
        _check(u"平台边缘站立不抖", False, u"初始没站住")

    # 落脚点必须精确贴合，不能浮空或陷入
    w4 = _flat()
    p4 = player.Player(100, 200)
    for _ in range(200):
        p4.update(DT, idle, w4)
    _check(u"落地精确贴合地面", abs((p4.y + player.Player.HEIGHT) - 460.0) < 0.5,
           u"bottom=%.2f（应 460）" % (p4.y + player.Player.HEIGHT))


def test_jump_20():
    _section(u"M2 连续跳跃稳定性")

    w = _flat()
    p = player.Player(100, 390)
    _land(p, w)
    idle = _idle()
    ok = True
    detail = ""

    for i in range(20):
        guard = 0
        while not p.on_ground and guard < 240:
            p.update(DT, idle, w)
            guard += 1
        if not p.on_ground:
            ok = False
            detail = u"第 %d 次落地超时" % (i + 1)
            break
        inp = _idle()
        inp.jump_pressed = True
        inp.jump_held = True
        p.update(DT, inp, w)
        if p.vy >= -100.0:
            ok = False
            detail = u"第 %d 次没起跳" % (i + 1)
            break
        for _ in range(12):
            p.update(DT, inp, w)
            if p.on_ground:
                break

    _check(u"连跳 20 次无卡死", ok and p.jump_count == 20,
           detail or u"jumps=%d" % p.jump_count)


def test_physics():
    test_move()
    test_jump_basic()
    test_variable_jump()
    test_coyote()
    test_jump_buffer()
    test_collision()
    test_jump_20()


# ---------------------------------------------------------------- 入口

def run(app):
    print("=" * 60)
    print(u" 火柴人跑酷 · 分阶段自检")
    print("=" * 60)

    test_scenes(app)
    test_physics()

    fails = len([r for r in RESULTS if not r[0]])
    print("")
    print("-" * 60)
    if fails:
        print(u" 结果：%d 项失败 / 共 %d 项" % (fails, len(RESULTS)))
    else:
        print(u" 结果：全部通过，共 %d 项" % len(RESULTS))
    print("-" * 60)
    return 1 if fails else 0
