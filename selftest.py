# -*- coding: utf-8 -*-
"""分阶段自检。入口：python main.py --selftest

M1 场景部分需要真实 Display（要渲染一帧）；
M2 物理部分是纯逻辑，只操作 Player + Rect，不读键盘、不画图，
所以土狼时间、跳跃缓冲这类"靠帧数才测得准"的东西可以精确断言。

每条断言都对应 README §19 的某一项验收，不许靠手感。
"""

import math
import os
import tempfile

import pygame

import assets
import audio as audio_mod
import config
import dialog
import enemy
import fx as fx_mod
import io_utils
import levels_catalog
import player
import save as save_mod
import scenes
import world

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

    # M9 起 Esc 不再直接退菜单，而是打开暂停面板——直接退会把这一局的
    # 检查点、金币、机关状态全丢掉，按一下 Esc 就白跑十分钟。
    app.scenes.handle_events([_key(pygame.K_ESCAPE)])
    paused = app.scenes.current_name == "game" and app.scenes.current.paused
    _check(u"Esc 打开暂停面板", paused,
           u"当前=%s paused=%s" % (app.scenes.current_name,
                                   getattr(app.scenes.current, "paused", None)))
    app.scenes.draw(app.screen)
    pygame.display.flip()
    _check(u"暂停面板可渲染", True, u"已绘制一帧")

    # 从暂停面板回主菜单
    game = app.scenes.current
    game.pause_index = len(game.PAUSE_ITEMS) - 1
    app.scenes.handle_events([_key(pygame.K_RETURN)])
    _check(u"暂停面板可回菜单", app.scenes.current_name == "menu",
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


# ---------------------------------------------------------------- M4 机关
L2 = os.path.join(config.LEVEL_DIR, "l2.txt")


def _run(scene, frames):
    for _ in range(frames):
        scene.update(DT)


def test_oneway():
    _section(u"M4 单向平台")

    solids = _flat()                      # 地面顶面 y=460
    oneway = [pygame.Rect(200, 380, 140, config.ONEWAY_THICK)]
    p = player.Player(240, 460 - player.Player.HEIGHT)
    _land(p, solids, 4)

    inp = player.InputState()
    inp.jump_pressed = True
    inp.jump_held = True
    min_bottom = 9999.0
    frames = 0
    while frames < 90:
        p.update(DT, inp, solids, oneways=oneway)
        frames += 1
        min_bottom = min(min_bottom, p.rect.bottom)
        if frames > 5 and p.on_ground:
            break

    _check(u"可以从下方穿过单向平台", min_bottom < oneway[0].top - 2,
           u"最高脚底 %.1f / 平台顶 %d" % (min_bottom, oneway[0].top))
    _check(u"落下后站在单向平台上",
           p.on_ground and abs(p.rect.bottom - oneway[0].top) <= 1,
           u"脚底 %.1f（平台顶 %d）" % (p.rect.bottom, oneway[0].top))

    # 走出板子右缘应掉落，不是粘在边上
    inp2 = player.InputState()
    inp2.axis = 1.0
    for _ in range(40):
        p.update(DT, inp2, solids, oneways=oneway)
    _check(u"走出板缘会掉下去", p.rect.bottom > oneway[0].top + 2,
           u"脚底 %.1f" % p.rect.bottom)


def test_bouncer():
    _section(u"M4 弹跳板")

    solids = _flat()
    pad = pygame.Rect(200, 452, 56, 8)     # 顶面 452，比地面高 8px
    p = player.Player(210, 200)
    idle = player.InputState()

    start = None
    min_feet = 9999.0
    for i in range(60):
        p.update(DT, idle, solids, bouncers=[pad])
        if p.bounce_count:
            if start is None:
                start = i
            min_feet = min(min_feet, p.y + player.Player.HEIGHT)
        if start is not None and i > start + 3 and p.on_ground:
            break

    _check(u"踩到弹跳板会被弹起", p.bounce_count == 1,
           u"触发 %d 次" % p.bounce_count)
    rise = (460.0 - min_feet) if start is not None else 0.0
    jump_h = _jump_height(999)
    _check(u"弹起高度大于普通跳跃", rise > jump_h + 40,
           u"弹起 %.0fpx vs 跳高 %.0fpx" % (rise, jump_h))
    _check(u"一次下落只触发一次", p.bounce_count == 1,
           u"bounce_count=%d" % p.bounce_count)

    # 弹起不是跳跃：jump_count 不该被算进去，空中按跳跃也不该变成二段跳
    p3 = player.Player(210, 200)
    for _ in range(40):
        p3.update(DT, idle, solids, bouncers=[pad])
        if p3.bounce_count:
            break
    _check(u"弹起不计入跳跃次数", p3.jump_count == 0,
           u"jump=%d bounce=%d" % (p3.jump_count, p3.bounce_count))
    air = player.InputState()
    air.jump_pressed = True
    air.jump_held = True
    p3.update(DT, air, solids, bouncers=[pad])
    _check(u"弹起后按跳跃不会二段跳", p3.jump_count == 0,
           u"jump=%d vy=%.0f" % (p3.jump_count, p3.vy))


def test_platform():
    _section(u"M4 移动平台")

    w = world.World.load(L2)
    xs = [p for p in w.platforms if p.axis == "x"]
    ys = [p for p in w.platforms if p.axis == "y"]
    _check(u"l2 有一个水平平台与一个升降平台",
           len(xs) == 1 and len(ys) == 1,
           u"水平 %d / 垂直 %d" % (len(xs), len(ys)))

    plat = xs[0]
    start = plat.rect.x
    seen = []
    for _ in range(360):
        plat.update(DT)
        seen.append(plat.rect.x - start)
    _check(u"行程恰好 2 格", abs(max(seen) - config.PLATFORM_TRAVEL) < 1.0,
           u"最远 %.1f px（期望 %.0f）" % (max(seen), config.PLATFORM_TRAVEL))
    _check(u"会往返回到起点", min(seen[100:]) <= 1.0,
           u"第二轮最左 %.1f px，末帧 %.1f" % (min(seen[100:]), seen[-1]))
    step = max(abs(seen[i + 1] - seen[i]) for i in range(len(seen) - 1))
    _check(u"单帧位移不超过 3px", step <= 3.0,
           u"最大 %.1f px/帧（%.0f px/s）" % (step, config.PLATFORM_SPEED))

    plat2 = ys[0]
    y0 = plat2.rect.y
    for _ in range(60):
        plat2.update(DT)
    _check(u"升降平台向上走", plat2.rect.y < y0,
           u"y %.0f -> %.0f" % (y0, plat2.rect.y))


def test_platform_squeeze():
    _section(u"M4 平台挤压（瞬移回归）")

    # 站着不动，升降台从 500 一路降下来扫过玩家的头。老实现只要发生 1px
    # 重叠就按"从上面落下来"处理，把人从台底整块吸到台面（实测 101px）。
    ground = pygame.Rect(0, 640, 800, 128)
    lift = pygame.Rect(300, 500, 64, 32)
    p = player.Player(310, 640 - player.Player.HEIGHT)
    inp = player.InputState()
    start_x = p.x
    prev = p.y
    worst = 0.0
    deepest = 0.0
    for i in range(220):
        lift.y += 1                       # 比实际平台（1.5px/帧）更狠
        inp.jump_pressed = (i % 25 == 0)
        inp.jump_held = (i % 25 < 8)
        inp.jump_released = (i % 25 == 8)
        p.update(DT, inp, [ground, lift])
        worst = max(worst, abs(p.y - prev))
        deepest = max(deepest, p.rect.bottom - ground.top)
        prev = p.y

    _check(u"升降台压到头顶不会把人吸到台面上", worst <= 12.0,
           u"最大单帧竖直位移 %.1f px" % worst)
    _check(u"被压时不会陷进地面", deepest <= player.Player.SKIM_PX + 1.0,
           u"最深 %.1f px（容差 %.0f）" % (deepest, player.Player.SKIM_PX))
    _check(u"被压时会把人挤到旁边", abs(p.x - start_x) > 1.0,
           u"x %.1f -> %.1f" % (start_x, p.x))
    _check(u"挤出去之后没有掉进地面", p.rect.bottom <= ground.top + 1.0,
           u"脚底 %.1f 地面 %d" % (p.rect.bottom, ground.top))

    # 反过来：玩家自己往上跳，头顶撞到平台下沿，只能被挡住，不能穿上去
    p2 = player.Player(310, 640 - player.Player.HEIGHT)
    ceiling = pygame.Rect(280, 450, 120, 48)          # 底边 498，头顶在 570
    inp2 = player.InputState()
    top_seen = 9999.0
    for i in range(40):
        inp2.jump_pressed = (i == 0)
        inp2.jump_held = True
        p2.update(DT, inp2, [ground, ceiling])
        top_seen = min(top_seen, p2.y)
    _check(u"跳起来撞到天花板会被挡住", top_seen >= ceiling.bottom - 1.0,
           u"最高头顶 %.1f（天花板底 %d）" % (top_seen, ceiling.bottom))


def test_m4_scene(app):
    _section(u"M4 死亡 / 检查点 / 平台带动")

    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(L2)
    w = scene.world
    if w is None:
        _check(u"l2 可加载", False, scene.load_error)
        return

    _check(u"l2 尺寸 56x12", (w.width_tiles, w.height_tiles) == (56, 12),
           u"%d x %d" % (w.width_tiles, w.height_tiles))
    _check(u"篝火 2 个", len(w.checkpoints) == 2, u"%d 个" % len(w.checkpoints))
    _check(u"弹跳板 1 个", len(w.bouncers) == 1, u"%d 个" % len(w.bouncers))
    _check(u"危险格已解析", len(w.hazard_boxes) >= 5,
           u"%d 个判定框" % len(w.hazard_boxes))

    # 篝火脚下必须有地面，否则重生会直接掉进坑里
    bad = [cp for cp in w.checkpoints
           if not w.is_solid_px(cp["spawn"][0] + 5, cp["spawn"][1] + 72)]
    _check(u"篝火都踩在实地上", not bad, u"%d 个悬空" % len(bad))

    # ---- 平台带动 ----
    plat = [p for p in w.platforms if p.axis == "x"][0]
    scene.player.teleport(plat.rect.centerx - player.Player.WIDTH // 2,
                          plat.rect.top - player.Player.HEIGHT)
    _run(scene, 6)
    _check(u"玩家站到了移动平台上", scene.player.on_ground,
           u"on_ground=%s 脚底 %.1f" % (scene.player.on_ground,
                                       scene.player.rect.bottom))
    x0, px0 = scene.player.x, plat.rect.x
    _run(scene, 36)
    dx, dpx = scene.player.x - x0, plat.rect.x - px0
    _check(u"平台把玩家一起带走", abs(dx - dpx) < 2.5,
           u"玩家 %+.1f px，平台 %+.1f px" % (dx, dpx))
    _check(u"全程贴在平台顶面",
           abs(scene.player.rect.bottom - plat.rect.top) <= 2,
           u"脚底 %.1f / 平台顶 %d" % (scene.player.rect.bottom, plat.rect.top))
    _check(u"带人时没有被挤死", scene.deaths == 0, u"死亡 %d 次" % scene.deaths)

    # ---- 死亡：掉进水里 ----
    water = w.hazard_boxes[1][0]            # 第一个水格判定框
    scene.player.teleport(water.centerx, water.top)
    _run(scene, 1)
    _check(u"碰到水会死", scene.deaths == 1, u"死亡 %d 次" % scene.deaths)
    _check(u"死亡后进入定格", scene.death_timer > 0.0,
           u"定格剩余 %.2fs" % scene.death_timer)

    _run(scene, 4)
    _check(u"定格期间不重复计数", scene.deaths == 1,
           u"死亡 %d 次" % scene.deaths)

    _run(scene, int(config.DEATH_FREEZE / DT) + 3)
    _check(u"定格结束会重生", scene.respawn_count == 1,
           u"重生 %d 次" % scene.respawn_count)
    _check(u"没点篝火时回出生点",
           abs(scene.player.x - w.spawn[0]) < 1.0
           and abs(scene.player.y - w.spawn[1]) < 1.0,
           u"位置 (%.0f, %.0f)，出生点 %s"
           % (scene.player.x, scene.player.y, w.spawn))
    _check(u"重生后有短暂无敌", scene.invuln > 0.0, u"invuln=%.2f" % scene.invuln)

    # ---- 篝火 ----
    cp = w.checkpoints[0]
    scene.player.teleport(cp["spawn"][0], cp["spawn"][1])
    _run(scene, 2)
    _check(u"碰到篝火会点亮", cp["active"], u"active=%s" % cp["active"])
    _check(u"重生点改为该篝火",
           scene.checkpoint == cp["spawn"], u"cp=%s" % (scene.checkpoint,))

    # 等无敌时间过去，再死一次，看是否回到篝火
    _run(scene, int(config.INVULN_TIME / DT) + 4)
    deaths_before = scene.deaths
    scene.player.teleport(water.centerx, water.top)
    _run(scene, 1)
    _check(u"点亮后再死仍会计数", scene.deaths == deaths_before + 1,
           u"死亡 %d -> %d" % (deaths_before, scene.deaths))
    _run(scene, int(config.DEATH_FREEZE / DT) + 3)
    _check(u"重生在最近点亮的篝火",
           abs(scene.player.x - cp["spawn"][0]) < 1.0
           and abs(scene.player.y - cp["spawn"][1]) < 1.0,
           u"位置 (%.0f, %.0f)，篝火 %s"
           % (scene.player.x, scene.player.y, cp["spawn"]))

    # ---- T 回检查点不算死亡 ----
    deaths_before = scene.deaths
    scene.player.teleport(600, 500)
    ok = scene.go_to_checkpoint()
    _check(u"T 能回检查点", ok, u"返回 %s" % ok)
    _check(u"T 不增加死亡数", scene.deaths == deaths_before,
           u"死亡 %d -> %d" % (deaths_before, scene.deaths))
    _check(u"T 后位置在篝火",
           abs(scene.player.x - cp["spawn"][0]) < 1.0,
           u"x=%.0f" % scene.player.x)

    # ---- 重开本关 ----
    scene.restart()
    _check(u"R 重开清空死亡数", scene.deaths == 0 and scene.respawn_count == 0,
           u"deaths=%d" % scene.deaths)
    _check(u"R 重开熄灭篝火",
           not any(c["active"] for c in scene.world.checkpoints),
           u"点亮 %d 个" % len([c for c in scene.world.checkpoints if c["active"]]))
    _check(u"R 重开回到出生点",
           abs(scene.player.x - scene.world.spawn[0]) < 1.0,
           u"x=%.0f" % scene.player.x)
    _check(u"R 重开把平台复位",
           scene.world.platforms[0].offset == 0.0
           and scene.world.platforms[1].offset == 0.0,
           u"offset=%.1f" % scene.world.platforms[0].offset)

    # ---- 真的坐平台过一次 5 格坑：证明这段不是"看着能过"----
    # 输入节奏取自 tools/try_l2_cross.py 的实测：助跑到岸边 → 跳 6 帧 →
    # 落到平台上 → 松手让平台带 → 到远端走上岸。轻点跳（2~3 帧）够不到
    # 平台左缘，这是关卡要求的操作精度，不是 bug。
    scene.restart()
    plat = [p for p in scene.world.platforms if p.axis == "x"][0]
    p = scene.player
    p.teleport(36 * config.TILE - player.Player.WIDTH,
               10 * config.TILE - player.Player.HEIGHT)
    _run(scene, 2)
    for _ in range(600):
        if plat.offset <= 1.0:          # 等平台回到近端再起跑
            break
        _run(scene, 1)
    scene.override_axis = 1.0
    frames = 0
    while p.x < 36 * config.TILE + 56 and frames < 90:
        _run(scene, 1)
        frames += 1
    scene.input.jump_pressed = True
    scene.input.jump_held = True
    _run(scene, 6)
    scene.input.jump_held = False
    scene.input.jump_released = True
    for _ in range(60):
        _run(scene, 1)
        if p.on_ground:
            break
    on_board = p.on_ground and abs(p.rect.bottom - plat.rect.top) <= 2
    for _ in range(600):
        if plat.offset >= config.PLATFORM_TRAVEL - 1.0:
            break
        _run(scene, 1)
    _run(scene, 80)
    scene.override_axis = None
    _check(u"l2 的 5 格坑能坐平台过去",
           on_board and p.x > 42 * config.TILE and p.on_ground,
           u"上板=%s 最终 x=%.0f（对岸 %d）脚底 %.0f"
           % (on_board, p.x, 42 * config.TILE, p.rect.bottom))
    _check(u"过坑全程没死", scene.deaths == 0, u"死亡 %d 次" % scene.deaths)



def test_physics():
    test_move()
    test_jump_basic()
    test_variable_jump()
    test_coyote()
    test_jump_buffer()
    test_collision()
    test_jump_20()


# ---------------------------------------------------------------- M2.5 角色动画

def test_sprites():
    _section(u"角色贴图（素材接入）")

    hero = assets.load_hero()
    _check(u"三类动作齐全",
           sorted(hero.frames.keys()) == ["idle", "jump", "run"],
           u"、".join(sorted(hero.frames.keys())))
    _check(u"跑步 8 帧", hero.frame_count("run", -1) == 8,
           u"%d 帧" % hero.frame_count("run", -1))
    _check(u"左右朝向都有",
           all(len(hero.frames[a]) == 2 for a in hero.frames),
           u"每个动作 2 个朝向")

    # 缩放定标：站立帧缩放到目标高度，误差应在 2px 内
    stand = hero.frame("idle", -1, 0)
    real_h = stand.get_bounding_rect().height
    _check(u"站立帧缩放到位",
           abs(real_h - assets.HERO_TARGET_HEIGHT) <= 2.0,
           u"目标 %.0f 实测 %d" % (assets.HERO_TARGET_HEIGHT, real_h))
    _check(u"与碰撞盒同高",
           abs(real_h - player.Player.HEIGHT) <= 3.0,
           u"贴图 %d / 碰撞盒 %d" % (real_h, player.Player.HEIGHT))

    # land.png 实测是地砖，绝不能混进角色帧
    all_rel = []
    for sides in assets.hero_anim_specs().values():
        for rels in sides.values():
            all_rel.extend(rels)
    _check(u"land.png 未被当角色帧",
           not any("land.png" in r for r in all_rel),
           u"共 %d 个角色帧文件" % len(all_rel))

    # 像素级验证「脚底真的贴地」：锚点算出的脚底位置必须等于不透明像素
    # 的底边。差 1px 是 smoothscale 把半透明边缘扩了一格，可接受。
    worst = 0
    worst_name = ""
    for action in ("idle", "run", "jump"):
        n = hero.frame_count(action, -1)
        for i in range(n):
            img = hero.frame(action, -1, i)
            box = img.get_bounding_rect()
            diff = abs(hero.foot_offset(action, -1, i) - box.bottom)
            if diff > worst:
                worst, worst_name = diff, "%s#%d" % (action, i)
    _check(u"每帧脚底贴地", worst <= 1,
           u"最大偏差 %dpx（%s）" % (worst, worst_name or u"无"))

    # 缺素材必须抛 AssetMissing（降级路径的触发条件）
    thrown = False
    try:
        assets.image("images/hero/__not_here__.png")
    except assets.AssetMissing:
        thrown = True
    _check(u"缺素材抛 AssetMissing", thrown, u"GameScene 据此退回代码绘制")


def test_anim_state():
    _section(u"动画状态机")

    hero = assets.load_hero()
    solids = _flat()
    p = player.Player(200, 460 - player.Player.HEIGHT)
    _land(p, solids, 4)
    _check(u"静止播 idle", p.anim_state == "idle", p.anim_state)

    # 按住右跑：状态切 run，相位随位移累加
    inp = player.InputState()
    inp.axis = 1.0
    p.update(DT, inp, solids)
    p.update(DT, inp, solids)          # 前两帧用来切状态，相位归零
    expected = p.anim_phase
    for _ in range(28):
        p.update(DT, inp, solids)
        expected += abs(p.vx) * DT / config.RUN_STRIDE_PX
    _check(u"跑动播 run", p.anim_state == "run", p.anim_state)
    _check(u"相位与位移同步",
           abs(p.anim_phase - expected) < 0.5,
           u"实测 %.2f 期望 %.2f" % (p.anim_phase, expected))
    _check(u"跑满一轮有换帧",
           p.anim_frame >= 8,
           u"帧号 %d（8 帧一轮，已跨轮）" % p.anim_frame)

    # 帧号取模后必须落在合法区间
    count = hero.frame_count("run", p.facing)
    idx = p.anim_frame % count
    _check(u"帧索引不越界", 0 <= idx < count, u"index=%d / %d" % (idx, count))

    # 朝向：往左跑用左向贴图
    inp2 = player.InputState()
    inp2.axis = -1.0
    for _ in range(10):
        p.update(DT, inp2, solids)
    _check(u"朝左用左向帧", p.facing == -1, u"facing=%d" % p.facing)
    left_img = hero.frame(p.anim_state, p.facing,
                          p.anim_frame % hero.frame_count(p.anim_state, p.facing))
    _check(u"左向帧可取到", left_img is not None,
           u"%dx%d" % left_img.get_size())

    # 起跳切 jump，空中保持
    inp3 = player.InputState()
    inp3.jump_pressed = True
    inp3.jump_held = True
    p.update(DT, inp3, solids)
    _check(u"起跳播 jump", p.anim_state == "jump", p.anim_state)
    for _ in range(10):
        p.update(DT, inp3, solids)
    _check(u"空中保持 jump", p.anim_state == "jump" and not p.on_ground,
           u"on_ground=%s" % p.on_ground)

    # 落回地面后必须脱离 jump，回到 idle/run
    for _ in range(80):
        p.update(DT, inp3, solids)
    _check(u"落地退出 jump", p.on_ground and p.anim_state != "jump",
           u"state=%s" % p.anim_state)


def test_dash():
    _section(u"冲刺")

    solids = _flat()
    p = player.Player(200, 460 - player.Player.HEIGHT)
    _land(p, solids, 4)

    inp = player.InputState()
    inp.axis = 1.0
    inp.dash_pressed = True
    x0 = p.x
    p.update(DT, inp, solids)
    _check(u"冲刺起手达到冲刺速", abs(p.vx - config.DASH_SPEED) < 1.0,
           u"vx=%.1f（目标 %.0f）" % (p.vx, config.DASH_SPEED))
    _check(u"冲刺中仍算在地面", p.on_ground, u"on_ground=%s" % p.on_ground)
    _check(u"冷却从起手开始计", abs(p.dash_cd - config.DASH_COOLDOWN) < 1e-6,
           u"cd=%.3f" % p.dash_cd)

    # 冲完一整个 DASH_TIME，量总位移
    frames = 1
    while p.dashing and frames < 60:
        p.update(DT, inp, solids)
        frames += 1
    travel = p.x - x0
    want = config.DASH_SPEED * config.DASH_TIME
    _check(u"冲刺距离符合设定", abs(travel - want) < 0.12 * want,
           u"%.1f px（理论 %.1f，%d 帧）" % (travel, want, frames))

    # 收招那一帧的速度还是冲刺速（本帧位移已经用掉了），下一帧才开始衰减。
    # 8 帧内必须落回跑速，否则就是"冲刺结束后还在偷偷加速"。
    decayed = None
    for i in range(1, 9):
        p.update(DT, inp, solids)
        if p.vx <= config.RUN_SPEED + 1.0:
            decayed = i
            break
    _check(u"冲刺后回落到跑速", decayed is not None,
           u"%d 帧后 vx=%.1f" % (decayed or -1, p.vx))

    # 冷却期内再按无效
    before = p.dash_count
    inp.dash_pressed = True
    p.update(DT, inp, solids)
    _check(u"冷却中不能连按", p.dash_count == before,
           u"次数仍为 %d，cd=%.2f" % (p.dash_count, p.dash_cd))

    # 冷却结束后恢复
    idle = _idle()
    idle.axis = 1.0
    for _ in range(int(config.DASH_COOLDOWN / DT) + 3):
        p.update(DT, idle, solids)
    _check(u"冷却结束恢复可用", p.can_dash(), u"cd=%.3f" % p.dash_cd)
    idle.dash_pressed = True
    p.update(DT, idle, solids)
    _check(u"可以再次冲刺", p.dash_count == before + 1,
           u"次数 %d" % p.dash_count)

    # ---- 空中冲刺：竖直速度被冻结，走直线不往下沉 ----
    p2 = player.Player(200, 460 - player.Player.HEIGHT)
    _land(p2, solids, 4)
    jump = _idle()
    jump.jump_pressed = True
    jump.jump_held = True
    p2.update(DT, jump, solids)
    for _ in range(4):
        p2.update(DT, jump, solids)
    vy_before = p2.vy
    air = _idle()
    air.axis = 1.0
    air.dash_pressed = True
    y0 = p2.y
    p2.update(DT, air, solids)
    _check(u"空中冲刺前正在上升", vy_before < 0, u"vy=%.1f" % vy_before)
    _check(u"空中冲刺冻结下落", p2.vy == 0.0, u"vy=%.1f" % p2.vy)
    _check(u"空中冲刺走直线", abs(p2.y - y0) < 0.01, u"dy=%.2f" % (p2.y - y0))
    for _ in range(12):
        p2.update(DT, air, solids)
    _check(u"冲完恢复重力", p2.vy > 0.0, u"vy=%.1f" % p2.vy)

    # ---- 撞墙立刻收招 ----
    wall = [pygame.Rect(0, 460, config.WIDTH, 80), pygame.Rect(200, 300, 40, 160)]
    p3 = player.Player(100, 460 - player.Player.HEIGHT)
    _land(p3, wall, 4)
    into = _idle()
    into.axis = 1.0
    into.dash_pressed = True
    p3.update(DT, into, wall)          # 先起手，否则循环条件一开始就为假
    hits = 1
    while p3.dash_time > 0.0 and hits < 20:
        p3.update(DT, into, wall)
        hits += 1
    _check(u"冲刺中撞墙立刻收招", p3.dash_time == 0.0 and hits < 10,
           u"%d 帧后撞上，dash_time=%.3f" % (hits, p3.dash_time))
    _check(u"撞墙后不嵌进墙里", p3.rect.right <= 201, u"right=%d" % p3.rect.right)

    # ---- 无方向输入时按朝向冲 ----
    p4 = player.Player(300, 460 - player.Player.HEIGHT)
    _land(p4, solids, 4)
    p4.facing = -1
    none_dir = _idle()
    none_dir.dash_pressed = True
    p4.update(DT, none_dir, solids)
    _check(u"无输入时按朝向冲", p4.dash_dir == -1, u"dir=%+d" % p4.dash_dir)
    _check(u"冲刺中不接受起跳", p4.jump_count == 0, u"jumps=%d" % p4.jump_count)


def test_land_feel():
    _section(u"落地反馈")

    solids = _flat()
    p = player.Player(200, 460 - player.Player.HEIGHT)
    _land(p, solids, 4)

    inp = player.InputState()
    inp.jump_pressed = True
    inp.jump_held = True
    p.update(DT, inp, solids)
    flew = 0
    while not p.on_ground and flew < 120:
        p.update(DT, inp, solids)
        flew += 1
    _check(u"跳起后能落回", p.on_ground and flew < 120, u"滞空 %d 帧" % flew)

    sink = p.land_sink
    _check(u"落地有下沉反馈", sink > 0.5, u"下沉 %.2f px" % sink)
    for _ in range(8):
        p.update(DT, player.InputState(), solids)
    _check(u"下沉自动回弹", p.land_sink < 0.01, u"%.3f px" % p.land_sink)


# ---------------------------------------------------------------- 关卡数据体检

def test_level_audit():
    """全关卡"能不能吃到 / 站得住"的体检。

    这类问题**是数据错，不是操作差**，而肉眼看地图看不出来：
      - 金币画在终点旗右边：一脚踩进终点判定区就结算定格，永远吃不到
        （试玩两次都报"这关有金币拿不到"，就是这一条）；
      - 金币埋在实心里：画都画在墙里；
      - 篝火底下是空的或者泡在水里：重生直接在死亡格上。
    全都用世界坐标和判定区比一遍，比再看十遍地图靠谱。
    """
    _section(u"全关卡结算体检（金币 / 篝火）")
    for i in range(levels_catalog.count()):
        lv = levels_catalog.at(i)
        path = levels_catalog.path_of(lv["key"])
        w = world.World.load(path)
        name = lv["name"]

        past = [c for c in w.coins if c["rect"].right > w.goal_zone.left]
        _check(u"%s 没有金币落在终点之后" % name, not past,
               u"%d/%d 枚越过终点（x>%d）"
               % (len(past), len(w.coins), w.goal_zone.left))

        buried = [c for c in w.coins
                  if any(r.colliderect(c["rect"]) for r in w.solids)]
        _check(u"%s 没有金币埋在实心里" % name, not buried,
               u"%d 枚" % len(buried))

        in_hazard = [c for c in w.coins if w.hazard_at(c["rect"]) is not None]
        _check(u"%s 没有金币压在危险格上" % name, not in_hazard,
               u"%d 枚" % len(in_hazard))

        bad = []
        for cp in w.checkpoints:
            r = cp["rect"]
            if not w.is_solid_px(r.centerx, r.bottom + 2):
                bad.append(u"悬空")
            elif w.hazard_at(r) is not None:
                bad.append(u"泡在危险格里")
        _check(u"%s 篝火重生点都站在实地上" % name, not bad,
               u"、".join(bad) or u"%d 个全好" % len(w.checkpoints))


# ---------------------------------------------------------------- M3 地图与相机

def _temp_level(name, text):
    """把地图写到临时目录，用于构造各种错误样本。"""
    folder = tempfile.mkdtemp(prefix="pyrun_lv_")
    path = os.path.join(folder, name)
    io_utils.write_text(path, text)
    return path


def test_level_parse():
    _section(u"M3 关卡解析")

    w = world.World.load(config.DEFAULT_LEVEL)
    _check(u"地图尺寸 44x9", (w.width_tiles, w.height_tiles) == (44, 9),
           u"%d x %d 格" % (w.width_tiles, w.height_tiles))

    # 出生点：第 3 列第 6 行，脚底正好压在第 7 行上沿
    want = (3 * config.TILE + (config.TILE - player.Player.WIDTH) // 2,
            7 * config.TILE - player.Player.HEIGHT)
    _check(u"出生点位置正确", w.spawn == want,
           u"spawn=%s 期望=%s" % (w.spawn, want))

    gy = 7 * config.TILE + 10
    _check(u"起始地面为实心", w.is_solid_px(64, gy), u"col 1 / row 7")
    _check(u"第 12 列是坑",
           not w.is_solid_px(12 * config.TILE + 10, gy), u"col 12 应为空气")
    _check(u"坑通到地图底部",
           not w.is_solid_px(12 * config.TILE + 10, 8 * config.TILE + 10),
           u"row 8 也是空气，掉下去才会出界")
    _check(u"第 22-23 列是 2 格宽坑",
           not w.is_solid_px(22 * config.TILE + 10, gy)
           and not w.is_solid_px(23 * config.TILE + 10, gy), u"宽度 128px")

    # 坑宽必须小于角色水平跨越能力，否则关卡不可通
    airtime = 2.0 * abs(config.JUMP_SPEED) / config.GRAVITY_UP
    reach = config.RUN_SPEED * airtime
    _check(u"坑宽小于跨越能力", 2 * config.TILE < reach,
           u"最宽坑 128px < 跨越 %.0fpx" % reach)

    gc, gr = w.goal_cells[0]
    _check(u"终点在第 41 列第 6 行", (gc, gr) == (41, 6),
           u"cell=(%d,%d)" % (gc, gr))
    _check(u"终点判定格与格子对齐",
           w.goal_rect == pygame.Rect(41 * config.TILE, 6 * config.TILE,
                                      config.TILE, config.TILE),
           u"rect=%s" % (w.goal_rect,))
    _check(u"终点踩在地面上",
           w.is_solid_px(w.goal_rect.centerx, w.goal_rect.bottom + 8),
           u"旗子下方是实心地面")

    _check(u"金币 9 枚", w.total_coins == 9, u"%d 枚" % w.total_coins)

    area = sum(r.width * r.height for r in w.solids)
    _check(u"碰撞矩形已合并", len(w.solids) <= 8,
           u"%d 格 -> %d 个矩形" % (len(w.solid_cells), len(w.solids)))
    _check(u"合并未丢失面积", area == len(w.solid_cells) * config.TILE ** 2,
           u"面积 %d px^2" % area)


def test_level_errors():
    _section(u"M3 解析报错")

    bad_char = "\n".join([
        "....",
        "..P.",
        "..x.",      # 第 3 行第 3 列是未知字符
        "####",
    ])
    path = _temp_level("bad_char.txt", bad_char)
    try:
        world.World.load(path)
        msg = u"（没有报错）"
    except world.LevelError as exc:
        msg = exc.describe()
    _check(u"未知字符报文件名+行号", "bad_char.txt:3" in msg and ":3" in msg,
           msg.splitlines()[0] if msg else u"")

    bad_width = "\n".join(["....", "..P.", "..F.", "####", "###"])
    path = _temp_level("bad_width.txt", bad_width)
    try:
        world.World.load(path)
        msg = u"（没有报错）"
    except world.LevelError as exc:
        msg = exc.describe()
    _check(u"行宽不一致报行号", "bad_width.txt:5" in msg,
           msg.splitlines()[0] if msg else u"")

    no_spawn = "\n".join(["....", "...F", "####"])
    path = _temp_level("no_spawn.txt", no_spawn)
    try:
        world.World.load(path)
        msg = u"（没有报错）"
    except world.LevelError as exc:
        msg = exc.describe()
    _check(u"缺出生点会报错", u"出生点" in msg, msg.splitlines()[0] if msg else u"")

    two_spawn = "\n".join([".P.P", "...F", "####"])
    path = _temp_level("two_spawn.txt", two_spawn)
    try:
        world.World.load(path)
        msg = u"（没有报错）"
    except world.LevelError as exc:
        msg = exc.describe()
    _check(u"多个出生点会报错", u"只能有一个" in msg,
           msg.splitlines()[0] if msg else u"")

    no_goal = "\n".join(["....", "..P.", "####"])
    path = _temp_level("no_goal.txt", no_goal)
    try:
        world.World.load(path)
        msg = u"（没有报错）"
    except world.LevelError as exc:
        msg = exc.describe()
    _check(u"缺终点会报错", u"终点" in msg, msg.splitlines()[0] if msg else u"")

    path = _temp_level("absent.txt", "")
    try:
        world.World.load(os.path.join(os.path.dirname(path), "nope.txt"))
        msg = u"（没有报错）"
    except world.LevelError as exc:
        msg = exc.describe()
    _check(u"文件不存在会报错", u"不存在" in msg, msg.splitlines()[0] if msg else u"")


def test_camera():
    _section(u"M3 相机")

    w = world.World.load(config.DEFAULT_LEVEL)
    cam = world.Camera((config.WIDTH, config.HEIGHT), w.bounds)

    # 出生点在关卡最左侧，相机必须被钳在左边界，不能露出地图外
    cam.snap_to(pygame.Rect(w.spawn[0], w.spawn[1],
                            player.Player.WIDTH, player.Player.HEIGHT))
    _check(u"开局贴左边界", abs(cam.x) < 0.01, u"cam.x=%.2f" % cam.x)

    # 跑到最右端：上限恰好是 地图宽 - 视口宽
    far = pygame.Rect(w.bounds.right - 10, 378, player.Player.WIDTH,
                      player.Player.HEIGHT)
    cam.snap_to(far)
    limit = w.bounds.width - config.WIDTH
    _check(u"右侧贴右边界", abs(cam.x - limit) < 0.01,
           u"cam.x=%.2f 上限 %d" % (cam.x, limit))

    # 全程扫一遍，任何时候视口都不能越界
    worst = 0.0
    for col in range(w.width_tiles):
        cam.snap_to(pygame.Rect(col * config.TILE, 378,
                                player.Player.WIDTH, player.Player.HEIGHT))
        v = cam.view_rect
        worst = max(worst, -v.left, v.right - w.bounds.width,
                    -v.top, v.bottom - w.bounds.height)
    _check(u"视口全程不越界", worst <= 0.0, u"最大越界 %.2f px" % worst)

    # 平滑跟随：一帧只走一部分，最终收敛到目标
    # 位置选在关卡中段——贴边时相机被钳制，测不出平滑量
    cam.snap_to(pygame.Rect(1400, 378, 26, 70))
    start = cam.x
    target = pygame.Rect(1600, 378, 26, 70)
    cam.update(DT, target)
    step = cam.x - start
    # 指数平滑一帧约收敛 11%，200px 的距离一帧只该走 20px 上下
    _check(u"单帧不是瞬移", 8.0 < step < 40.0,
           u"目标距 200px，一帧前进 %.2f px" % step)

    far_target = pygame.Rect(w.bounds.width - 40, 378, 26, 70)
    for _ in range(240):
        cam.update(DT, far_target)
    want = min(far_target.centerx - config.WIDTH / 2.0, limit)
    _check(u"最终收敛到目标", abs(cam.x - want) < 1.5,
           u"cam.x=%.2f 目标 %.2f" % (cam.x, want))

    # 地图比视口小时居中留白（README 允许的例外）
    small = world.Camera((config.WIDTH, config.HEIGHT), pygame.Rect(0, 0, 400, 300))
    _check(u"小地图水平居中", abs(small.x - (400 - config.WIDTH) / 2.0) < 0.01,
           u"cam.x=%.1f" % small.x)
    _check(u"小地图垂直居中", abs(small.y - (300 - config.HEIGHT) / 2.0) < 0.01,
           u"cam.y=%.1f" % small.y)


def test_level_playable():
    _section(u"M3 第一关可通关")

    w = world.World.load(config.DEFAULT_LEVEL)
    p = player.Player(*w.spawn)
    inp = player.InputState()
    inp.axis = 1.0
    inp.jump_held = True          # 一直按住，跳满高度才够跨 2 格坑

    frames = 0
    fell_out = False
    # 往下方最多探 1.5 格：掉下 64px 的台阶是允许的，只有真正的坑（通到
    # 地图底部）才算"没有地面"。一开始只探 8px，结果电脑人把台阶边缘也
    # 当成悬崖，从台阶上起跳正好飞进下一个坑里。
    LEDGE = int(config.TILE * 1.5)

    while frames < 1800:
        # 简单自动驾驶：前方是墙、或前方地面断掉，就起跳
        ahead_x = p.x + player.Player.WIDTH + 10
        feet = p.y + player.Player.HEIGHT
        on_wall = w.is_solid_px(ahead_x, feet - 12)
        no_ground = w.ground_y_below(ahead_x, feet + 4,
                                     limit=feet + LEDGE) is None
        if p.on_ground and (on_wall or no_ground):
            inp.jump_pressed = True
        p.update(DT, inp, w.solids)
        w.update(DT)
        frames += 1
        if p.y > w.bounds.bottom + 120:
            fell_out = True
            break
        if p.rect.colliderect(w.goal_zone):
            break

    reached = p.rect.colliderect(w.goal_zone)
    _check(u"从出生点走到终点", reached,
           u"%d 帧（%.1f 秒）" % (frames, frames * DT))
    _check(u"全程没有掉出地图", not fell_out,
           u"最低 y=%.1f / 地图底 %d" % (p.y, w.bounds.bottom))
    _check(u"时间在合理范围", 60 < frames < 1800,
           u"%.1f 秒" % (frames * DT))


# ---------------------------------------------------------------- M5 道具
L3 = os.path.join(config.LEVEL_DIR, "l3.txt")


def test_glide():
    _section(u"M5 滑翔伞")

    solids = _flat()                       # 地面顶面 460

    # 1) 没拿到伞：空中按住空格也只是普通下落
    p = player.Player(100, 200)
    inp = player.InputState()
    inp.jump_held = True
    for _ in range(10):
        p.update(DT, inp, solids)
    _check(u"没伞不会滑翔",
           (not p.gliding) and p.glide_frames == 0
           and p.vy > config.GLIDE_FALL_SPEED,
           u"gliding=%s vy=%.0f" % (p.gliding, p.vy))

    # 2) 有伞：按住空格，下落被压到 120，水平给到 330
    p2 = player.Player(100, 200)
    p2.pick_glider()
    held = player.InputState()
    held.jump_held = True
    held.axis = 1.0
    for _ in range(30):
        p2.update(DT, held, solids)
    # 第 1 帧 vy 还是 0，不满足"正在下落"，所以实到 29 帧才开始滑翔
    _check(u"有伞按住空格进入滑翔", p2.gliding and p2.glide_frames >= 29,
           u"滑翔 %d 帧" % p2.glide_frames)
    _check(u"下落速度被压到 120", abs(p2.vy - config.GLIDE_FALL_SPEED) < 0.5,
           u"vy=%.1f" % p2.vy)
    _check(u"水平速度给到 330", abs(p2.vx - config.GLIDE_RUN_SPEED) < 0.5,
           u"vx=%.1f" % p2.vx)

    # 同样 30 帧，不滑翔要掉 130px 以上
    ref = player.Player(100, 200)
    ref_inp = player.InputState()
    for _ in range(30):
        ref.update(DT, ref_inp, solids)
    _check(u"滑翔比自由落体慢得多", (p2.y - 200.0) < (ref.y - 200.0) * 0.5,
           u"滑翔 %.1f px / 自由落体 %.1f px" % (p2.y - 200.0, ref.y - 200.0))

    # 3) 松开按键立刻退出滑翔
    held.jump_held = False
    p2.update(DT, held, solids)
    vy_after = p2.vy
    for _ in range(6):
        p2.update(DT, held, solids)
    _check(u"松开空格退出滑翔", (not p2.gliding) and p2.vy > vy_after,
           u"vy %.0f -> %.0f" % (vy_after, p2.vy))

    # 4) 上升阶段不滑翔：起跳瞬间就按住也不行
    p3 = player.Player(100, 460 - player.Player.HEIGHT)
    p3.pick_glider()
    up = player.InputState()
    up.jump_pressed = True
    up.jump_held = True
    climbed = False
    for _ in range(20):
        p3.update(DT, up, solids)
        if p3.vy < 0.0:
            climbed = True
            if p3.gliding:
                climbed = False
                break
    _check(u"上升阶段不进入滑翔", climbed and (not p3.gliding),
           u"vy=%.0f gliding=%s" % (p3.vy, p3.gliding))

    # 5) 滑翔不能穿过墙
    wall = pygame.Rect(300, 120, 40, 400)
    p4 = player.Player(100, 200)
    p4.pick_glider()
    glide_in = player.InputState()
    glide_in.jump_held = True
    glide_in.axis = 1.0
    for _ in range(120):
        p4.update(DT, glide_in, solids + [wall])
    _check(u"滑翔撞墙会停住", p4.x + player.Player.WIDTH <= wall.left + 0.5,
           u"x=%.1f（墙左沿 %d）" % (p4.x, wall.left))


def test_m5_scene(app):
    _section(u"M5 关卡：拾取 / 重生保留 / 滑翔过坑")

    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(L3)
    w = scene.world
    if w is None:
        _check(u"l3 可加载", False, scene.load_error)
        return

    _check(u"l3 尺寸 54x13", (w.width_tiles, w.height_tiles) == (54, 13),
           u"%d x %d" % (w.width_tiles, w.height_tiles))
    _check(u"l3 有 1 把滑翔伞", len(w.gliders) == 1, u"%d 把" % len(w.gliders))

    # ---- 拾取 ----
    it = w.gliders[0]
    scene.player.teleport(it["pos"][0] - player.Player.WIDTH // 2,
                          it["pos"][1] - player.Player.HEIGHT // 2)
    _run(scene, 1)
    _check(u"碰到道具拿到滑翔伞",
           scene.player.has_glider and w.glider_taken == 1,
           u"has_glider=%s taken=%d" % (scene.player.has_glider, w.glider_taken))
    _check(u"拾取后弹出提示", scene.toast_timer > 0.0, scene.toast_text)

    # 重复踩同一格不该再提示
    scene.toast_text = ""
    scene.player.has_glider = False          # 强行让拾取判定再走一遍
    _run(scene, 1)
    _check(u"道具不会重复提示", scene.toast_text == "",
           u"提示「%s」" % scene.toast_text)
    scene.player.has_glider = True

    # ---- 从道具上方跳过去也要算捡到 ----
    # 判定区是 3 格高的竖条就是为了防这个：滑翔伞是通关必需道具，
    # 不能因为"跑的时候顺手跳了一下"就漏掉，然后在坑边才发现过不去。
    scene.restart()
    p0 = scene.player
    p0.teleport(it["pos"][0] - 60, 640 - player.Player.HEIGHT)
    _run(scene, 2)
    scene.input.jump_pressed = True
    scene.input.jump_held = True
    scene.override_axis = 1.0
    _run(scene, 20)
    scene.override_axis = None
    jumped = not p0.on_ground
    scene.input.jump_held = False
    scene.input.jump_pressed = False
    _check(u"跳着经过也能捡到伞",
           jumped and scene.player.has_glider,
           u"空中=%s has_glider=%s y=%.0f"
           % (jumped, scene.player.has_glider, scene.player.y))

    # ---- 死亡重生保留道具 ----
    # 这里显式给一次伞，让这条断言只依赖"重生是否保留"，
    # 不依赖上面那条跳着捡伞的用例是否通过
    scene.player.has_glider = True
    water = [b for b, ch in w.hazard_boxes if ch == "~"][0]
    scene.player.teleport(water.centerx, water.top)
    _run(scene, 1)
    _check(u"落水会死", scene.deaths == 1, u"死亡 %d 次" % scene.deaths)
    _run(scene, int(config.DEATH_FREEZE / DT) + 2)
    _check(u"重生后仍然带着伞", scene.player.has_glider,
           u"has_glider=%s" % scene.player.has_glider)

    # ---- R 重开：道具回到"没捡"状态 ----
    scene.restart()
    _check(u"重开清空道具", (not scene.player.has_glider)
           and w.glider_taken == 0 and (not w.gliders[0]["taken"]),
           u"has_glider=%s taken=%d" % (scene.player.has_glider, w.glider_taken))

    # ---- 大坑：有伞过得去 ----
    def cross(with_glider):
        scene.restart()
        p = scene.player
        p.has_glider = with_glider
        p.teleport(19 * config.TILE, 6 * config.TILE - p.HEIGHT)
        scene.camera.snap_to(p.rect)
        scene.override_axis = 1.0
        scene.input.jump_held = with_glider
        airborne = False
        for f in range(300):
            scene.update(DT)
            if scene.deaths:
                break
            if not p.on_ground:
                airborne = True
            elif airborne:
                break
        scene.override_axis = None
        scene.input.jump_held = False
        return p, f

    p, frames = cross(True)
    _check(u"l3 大坑靠滑翔能过",
           scene.deaths == 0 and p.on_ground and p.x > 29 * config.TILE,
           u"落点 x=%.0f（对岸 1856），%d 帧，死亡 %d"
           % (p.x, frames, scene.deaths))

    p, frames = cross(False)
    _check(u"不按空格过不去这个坑", scene.deaths >= 1,
           u"x=%.0f 死亡 %d" % (p.x, scene.deaths))

    # ---- 整关可通关 ----
    # 用"一路蹦着跑"这种最粗糙的跑法收尾：它最容易从旗子头顶飞过去，
    # 也最容易在平台上跳歪。能用它通关，说明关卡没有藏死的判定。
    scene.restart()
    scene.override_axis = 1.0
    frames = 0
    for f in range(2400):
        if scene.player.on_ground:
            scene.input.jump_pressed = True
        scene.input.jump_held = True
        scene.update(DT)
        frames = f
        if scene.goal_reached:
            break
    scene.override_axis = None
    scene.input.jump_held = False
    _check(u"l3 从出生点跑到终点", scene.goal_reached,
           u"%d 帧（%.1f 秒），金币 %d/%d，死亡 %d"
           % (frames, frames * DT, scene.world.taken_coins,
              scene.world.total_coins, scene.deaths))


# ---------------------------------------------------------------- M6 敌人与对话

L4 = os.path.join(config.LEVEL_DIR, "l4.txt")


def test_bat():
    _section(u"M6 蝙蝠巡逻")

    b = enemy.Bat(100.0, 200.0, 50.0)
    lo, hi = 1e9, -1e9
    for _ in range(600):
        b.update(DT)
        lo = min(lo, b.cx)
        hi = max(hi, b.cx)
    _check(u"蝙蝠不飞出巡逻区", lo >= 100.0 - 0.01 and hi <= 200.0 + 0.01,
           u"x ∈ [%.1f, %.1f]，区间 [100, 200]" % (lo, hi))
    # 600 帧 = 10 秒，行程 100px 在 70px/s 下约 1.4 秒单程，必然到过两端
    _check(u"两端都到过（真的往返）", hi > 195.0 and lo < 105.0,
           u"最近 %.1f / %.1f" % (lo, hi))
    hb = b.hitbox()
    _check(u"判定框比贴图窄", hb.width < 80 * config.BAT_SCALE,
           u"判定 %dpx < 贴图 %.0fpx" % (hb.width, 80 * config.BAT_SCALE))
    _check(u"判定框在贴图附近",
           abs(hb.centerx - b.cx) <= 1 and abs(hb.centery - b.cy) <= 12,
           u"box=%s cx=%.0f cy=%.0f" % (hb, b.cx, b.cy))

    # 单格巡逻（left == right）：贴着不动，不能因为反复反向而漂移
    still = enemy.Bat(500.0, 500.0, 300.0)
    for _ in range(120):
        still.update(DT)
    _check(u"单格蝙蝠原地悬停", abs(still.cx - 500.0) < 0.01,
           u"x=%.2f" % still.cx)


def test_rock_timing():
    _section(u"M6 落石时序")

    r = enemy.FallingRock(100.0, 100.0, 300.0)
    _check(u"落石先进入预警", r.state == "warn", r.state)
    _check(u"预警期不判定伤害", r.hitbox() is None, u"hitbox=%s" % (r.hitbox(),))

    frames = 0
    while r.state == "warn" and frames < 300:
        r.update(DT)
        frames += 1
    _check(u"预警约 %.1fs" % config.ROCK_WARN_TIME,
           abs(frames * DT - config.ROCK_WARN_TIME) < 0.05,
           u"实测 %.2fs" % (frames * DT))
    _check(u"预警结束后开始下落", r.state == "fall", r.state)
    _check(u"下落期才判定", r.hitbox() is not None,
           u"box=%s" % (r.hitbox(),))

    while r.state == "fall" and frames < 600:
        r.update(DT)
        frames += 1
    _check(u"落到地面高度就停", abs(r.y - 300.0) < 1.0, u"y=%.1f" % r.y)
    _check(u"落地后碎裂", r.state == "shatter", r.state)

    while not r.dead and frames < 900:
        r.update(DT)
        frames += 1
    _check(u"碎屑播完自动回收", r.dead, u"共 %d 帧" % frames)


def test_dialog_layout():
    _section(u"M6 对话排版")

    font, _ = scenes.get_font(21)
    long_text = u"石头落下前，地上会先出现一圈影子，" * 4
    lines = dialog.wrap_text(font, long_text, 400)
    _check(u"折行每行都不超宽",
           all(font.size(l)[0] <= 400 for l in lines),
           u"最宽 %dpx / 上限 400px" % max(font.size(l)[0] for l in lines))
    _check(u"长文本被折成多行", (len(lines) >= 3) and
           u"".join(lines) == long_text.replace(u"\n", u""),
           u"%d 行，字符不丢" % len(lines))
    _check(u"空行也能排版", dialog.wrap_text(font, u"", 400) == [u""])

    d = dialog.Dialog(u"老人", [u"第一页", u"第二页"])
    _check(u"从第一页开始", d.page() == u"第一页", d.page())
    _check(u"翻页返回 True 且停在第 2 页",
           d.advance() is True and d.page() == u"第二页", d.page())
    _check(u"最后一页翻完就结束",
           d.advance() is False and not d.active(), u"index=%d" % d.index)

    rect, _ = d.layout(font)
    _check(u"面板不越出屏幕",
           rect.left >= 0 and rect.right <= config.WIDTH
           and rect.top >= 0 and rect.bottom <= config.HEIGHT,
           u"%s" % (rect,))


def test_m6_parse():
    _section(u"M6 关卡解析：告示牌 / NPC / 敌人")
    try:
        w = world.World.load(L4)
    except world.LevelError as exc:
        _check(u"l4 可加载", False, exc.describe())
        return None

    _check(u"l4 尺寸 60x14", (w.width_tiles, w.height_tiles) == (60, 14),
           u"%d x %d" % (w.width_tiles, w.height_tiles))
    _check(u"3 块告示牌", len(w.signs) == 3, u"%d 块" % len(w.signs))
    _check(u"告示牌文本按出现顺序配对",
           all(s["pages"] for s in w.signs)
           and w.signs[0]["pages"][0].startswith(u"空格跳"),
           u"第一块「%s」" % w.signs[0]["pages"][0][:14])
    _check(u"1 个 NPC 且叫老人",
           len(w.npcs) == 1 and w.npcs[0]["name"] == u"老人",
           u"%s" % [n["name"] for n in w.npcs])
    _check(u"NPC 有 3 页台词", len(w.npcs[0]["pages"]) == 3,
           u"%d 页" % len(w.npcs[0]["pages"]))
    _check(u"2 只蝙蝠（连续 B 合并成巡逻段）", len(w.bats) == 2,
           u"%d 只：%s" % (len(w.bats),
                          [(b.left, b.right) for b in w.bats]))
    _check(u"1 个 UFO", len(w.ufos) == 1, u"%d 个" % len(w.ufos))
    _check(u"3 处落石点", len(w.rock_spawners) == 3,
           u"%d 处" % len(w.rock_spawners))

    # 敌人不能生在实心里，否则玩家看不见、也躲不开
    bad = [b for b in w.bats if w.is_solid_px(b.cx, b.cy)]
    _check(u"蝙蝠不在实心里", not bad, u"%d 只异常" % len(bad))
    bad = [u for u in w.ufos if w.is_solid_px(u.cx, u.cy)]
    _check(u"UFO 不在实心里", not bad, u"%d 个异常" % len(bad))

    # 落石点必须在天花板下方，且落点有地面（不然影子画到地图外）
    _check(u"落石点上方是天板",
           all(w.is_solid_px(s.cx, s.top_y - 10) for s in w.rock_spawners),
           u"%s" % [w.cell_at_px(s.cx, s.top_y - 10) for s in w.rock_spawners])
    _check(u"落石点有落点地面",
           all(s.ground_y < w.bounds.bottom for s in w.rock_spawners),
           u"%s" % [s.ground_y for s in w.rock_spawners])

    # 告示牌/NPC 要站在地面上
    for obj in w.signs + w.npcs:
        _check(u"%s 脚下是地面" % obj["name"],
               w.is_solid_px(obj["cell"].centerx, obj["cell"].bottom + 4),
               u"cell=(%d,%d)" % (obj["col"], obj["row"]))

    return w


def test_m6_errors():
    _section(u"M6 关卡文本的错误提示")

    cases = [
        (u"未知指令", u";!foo 随便\nP..S\n####\n", u"未知指令"),
        (u"牌子没有文本", u"P..S\n####\n", u"告示牌数量对不上"),
        (u"文本多一条", u";!sign 喂\nP...\n####\n", u"告示牌数量对不上"),
        (u"sign 后面没字", u";!sign\nP.S.\n####\n", u"没有文字"),
        (u"npc 格式缺页", u";!npc 老人\nP.N.\n####\n", u"格式"),
    ]
    for name, text, want in cases:
        path = _temp_level("e.txt", text)
        try:
            world.World.load(path)
            _check(u"%s 应当报错" % name, False, u"没报错")
        except world.LevelError as exc:
            msg = exc.describe()
            _check(u"%s" % name, want in msg, msg.splitlines()[0])


def test_m6_scene(app):
    _section(u"M6 对话暂停 / 敌人致死 / 重开复位")

    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(L4)
    w = scene.world
    if w is None:
        _check(u"l4 可加载", False, scene.load_error)
        return
    W = player.Player.WIDTH
    H = player.Player.HEIGHT

    # ---- 靠近 NPC -> 出现 E 提示 ----
    npc = w.npcs[0]
    scene.player.teleport(npc["cell"].centerx - W // 2 - 30,
                          npc["cell"].bottom - H)
    _run(scene, 3)
    _check(u"靠近 NPC 出现交互提示",
           w.focus is not None and w.focus["kind"] == "npc",
           u"focus=%s" % (w.focus["name"] if w.focus else None))

    # ---- 按 E 打开对话，整局暂停 ----
    ok = scene._try_interact()
    _check(u"E 打开对话", ok and scene.dialog is not None,
           u"pages=%d" % (len(scene.dialog.pages) if scene.dialog else 0))
    x0, t0, wt0 = scene.player.x, scene.level_time, w.time
    _run(scene, 60)
    _check(u"对话中玩家不动", abs(scene.player.x - x0) < 0.01,
           u"x %.1f -> %.1f" % (x0, scene.player.x))
    _check(u"对话中关卡计时冻结", abs(scene.level_time - t0) < 1e-9,
           u"%.3fs" % scene.level_time)
    _check(u"对话中世界也停（敌人不投弹）", abs(w.time - wt0) < 1e-9,
           u"world.time=%.3f" % w.time)

    # ---- 翻页到底自动关闭 ----
    pages = len(scene.dialog.pages)
    for _ in range(pages):
        scene._advance_dialog()
    _check(u"翻完最后一页自动关闭", scene.dialog is None, u"%d 页" % pages)
    _check(u"关掉后能重新打开", scene._try_interact() and scene.dialog is not None)
    scene.dialog = None

    # ---- 走远就没有提示 ----
    scene.player.teleport(npc["cell"].centerx - 320, npc["cell"].bottom - H)
    _run(scene, 3)
    _check(u"走远后提示消失", w.focus is None,
           u"focus=%s" % (w.focus["name"] if w.focus else None))

    # ---- 告示牌同样能读 ----
    sign = w.signs[0]
    scene.player.teleport(sign["cell"].centerx - W // 2 - 24,
                          sign["cell"].bottom - H)
    _run(scene, 3)
    _check(u"靠近告示牌出现提示",
           w.focus is not None and w.focus["kind"] == "sign",
           u"focus=%s" % (w.focus["name"] if w.focus else None))
    _check(u"告示牌对话的第一页是按键说明",
           scene._try_interact() and u"空格" in scene.dialog.page(),
           scene.dialog.page()[:14] if scene.dialog else u"-")
    scene.dialog = None

    # ---- 蝙蝠撞死 ----
    scene.restart()
    b = w.bats[0]
    scene.player.teleport(b.cx - W // 2, b.cy - H // 2)
    scene.invuln = 0.0
    _run(scene, 1)
    _check(u"碰到蝙蝠会死",
           scene.deaths == 1 and u"蝙蝠" in scene.last_death_cause,
           u"死亡 %d 次，原因「%s」" % (scene.deaths, scene.last_death_cause))

    # ---- 落石砸死 ----
    scene.restart()
    rs = w.rock_spawners[0]
    scene.player.teleport(rs.cx - W // 2, rs.ground_y - H)
    scene.invuln = 0.0
    for _ in range(300):
        _run(scene, 1)
        if scene.deaths:
            break
    _check(u"落石能砸死玩家",
           scene.deaths >= 1 and u"落石" in scene.last_death_cause,
           u"死亡 %d 次，原因「%s」，投下 %d 块"
           % (scene.deaths, scene.last_death_cause, w.rock_count))

    # ---- 重开复位 ----
    scene.restart()
    b = w.bats[0]
    _check(u"重开后场上没有落石",
           not w.rocks and w.rock_count == 0, u"%d 块" % len(w.rocks))
    _check(u"重开后蝙蝠回到中位",
           abs(b.cx - (b.left + b.right) * 0.5) < 1.0, u"x=%.0f" % b.cx)
    _check(u"重开后交互目标清空", w.focus is None, u"focus=%s" % (w.focus,))


def _auto_step(scene):
    """一个"会看路"的自动驾驶：前方没地、或者有墙，就起跳。

    为什么不沿用 l3 那套"落地就跳"：那套只在小坑面前碰巧成立，遇到
    台阶 + 坑相邻的段落会踩空（实测在 l4 的第 8 列必死）。这里多看一眼
    前方 30px 有没有地、6px 处有没有墙，就足够把一个纯地形关跑完——
    它证明的是"地形没画死"，不是"我操作好"。
    """
    p = scene.player
    w = scene.world
    if not p.on_ground:
        scene.input.jump_held = True
        return
    gap_ahead = not w.is_solid_px(p.rect.right + 30, p.rect.bottom + 6)
    wall_ahead = w.is_solid_px(p.rect.right + 6, p.rect.bottom - 12)
    if gap_ahead or wall_ahead:
        scene.input.jump_pressed = True
        scene.input.jump_held = True
    else:
        scene.input.jump_held = False


def test_m6_playable(app):
    _section(u"M6 第 4 关地形可通关")

    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(L4)
    w = scene.world
    if w is None:
        _check(u"l4 可加载", False, scene.load_error)
        return

    # 关掉敌人再跑：这一条测的是**地形**能不能过，不是能不能躲。
    # 混在一起的话，跑图失败时无法区分"关卡画错了"和"这次运气不好"。
    # 三个列表都要清：enemy_hit 查的是 bats/rocks，不看 enemies。
    w.bats = []
    w.ufos = []
    w.rock_spawners = []
    w.enemies = []
    w.rocks = []

    scene.override_axis = 1.0
    frames = 0
    for f in range(3600):
        _auto_step(scene)
        scene.update(DT)
        frames = f
        if scene.goal_reached:
            break
    scene.override_axis = None
    scene.input.jump_held = False
    _check(u"l4 从出生点一路跑到终点", scene.goal_reached,
           u"%d 帧（%.1f 秒），金币 %d/%d，死亡 %d"
           % (frames, frames * DT, w.taken_coins, w.total_coins, scene.deaths))


# ---------------------------------------------------------------- M7 新机关

L5 = os.path.join(config.LEVEL_DIR, "l5.txt")


def test_walker():
    _section(u"M7 走地怪")

    w = enemy.Walker(100.0, 200.0, 300.0)
    lo, hi = 1e9, -1e9
    for _ in range(400):
        w.update(DT)
        lo = min(lo, w.cx)
        hi = max(hi, w.cx)
    _check(u"走地怪不走出巡逻区", lo >= 100.0 - 0.01 and hi <= 200.0 + 0.01,
           u"x ∈ [%.1f, %.1f]" % (lo, hi))
    _check(u"走地怪真的在走（两端都到过）", hi > 195.0 and lo < 105.0,
           u"最近 %.1f / %.1f" % (lo, hi))

    box = w.hitbox()
    _check(u"走地怪判定框贴地且比身体窄",
           box.width < config.WALKER_BODY_W and box.bottom >= 300 - 4,
           u"box=%s，身体宽 %d" % (box, config.WALKER_BODY_W))
    zone = w.stomp_zone()
    _check(u"可踩区域在判定框上 70%",
           zone.height == int(box.height * config.STOMP_TOP_RATIO)
           and zone.top == box.top,
           u"zone=%s box=%s" % (zone, box))

    # 踩一次：立刻失去判定（同一帧不能再被判成碰撞），0.5 秒后彻底消失
    _check(u"第一次踩中有效", w.stomp() is True)
    _check(u"被踩后不再有致死判定", w.hitbox() is None and not w.alive,
           u"state=%s" % w.state)
    _check(u"同一只踩不了第二次", w.stomp() is False)
    frames = 0
    while w.state != "gone" and frames < 200:
        w.update(DT)
        frames += 1
    _check(u"闪烁 %.1fs 后消失" % config.WALKER_DIE_TIME,
           abs(frames * DT - config.WALKER_DIE_TIME) < 0.05,
           u"实测 %.2fs" % (frames * DT))

    w.reset()
    _check(u"重开后复活", w.alive and w.hitbox() is not None, w.state)


def test_rotor():
    _section(u"M7 旋转刺轮（低空刀片，禁跳区）")

    FLOOR = 704.0
    HEAD = FLOOR - player.Player.HEIGHT          # 站立头顶 634
    r = enemy.Rotor(1000.0, 576.0, phase=0.0)    # 轴心取 X 格上沿

    arms = r.arms()
    _check(u"四臂等分", len(arms) == config.ROTOR_ARMS
           and abs(arms[1][0] - arms[0][0] - math.pi / 2) < 1e-6,
           u"%d 条臂" % len(arms))
    _check(u"臂长恒定",
           all(abs(math.hypot(x - r.cx, y - r.cy) - config.ROTOR_ARM_LEN) < 0.01
               for _, x, y in arms),
           u"臂长 %.0f" % config.ROTOR_ARM_LEN)

    # 几何不变式：这一条是这个机关"能不能通关"的唯一保证。
    # 臂端一旦够到站立头顶，玩家贴着地跑也会被扫死，关卡直接不可通关。
    arm_tip = r.cy + config.ROTOR_ARM_LEN + config.ROTOR_TIP_R
    _check(u"臂端严格高于站立头顶（贴地跑不会被扫到）", arm_tip < HEAD,
           u"臂端 %.0f / 头顶 %.0f，余量 %.0fpx" % (arm_tip, HEAD, HEAD - arm_tip))

    # 全相位横穿：不是"运气好能过"，是 360 个相位一个都不该死
    fails = 0
    for k in range(360):
        r.phase = math.radians(k)
        r.reset()
        x = r.cx - 90.0
        ok = True
        while x <= r.cx + 90.0:
            r.update(DT)
            if r.hits(pygame.Rect(int(x), int(HEAD), 26, player.Player.HEIGHT)):
                ok = False
                break
            x += config.RUN_SPEED * DT
        if not ok:
            fails += 1
    _check(u"贴地横穿 180px，360 个起始相位全部安全", fails == 0,
           u"失败 %d 个相位" % fails)

    # 但威胁必须是真的：在刀片下面起跳，会被打下来
    jumped = hit_jump = 0
    for k in range(72):
        r.phase = math.radians(k * 5.0)
        r.reset()
        vy = config.JUMP_SPEED
        y = HEAD
        jumped += 1
        for _ in range(90):
            r.update(DT)
            vy += (config.GRAVITY_UP if vy < 0.0 else config.GRAVITY_DOWN) * DT
            y += vy * DT
            if y > HEAD:
                break
            if r.hits(pygame.Rect(int(r.cx) - 13, int(y), 26,
                                  player.Player.HEIGHT)):
                hit_jump += 1
                break
    _check(u"原地起跳会被刀片打下来", hit_jump == jumped,
           u"%d/%d 个相位" % (hit_jump, jumped))

    # 判定必须"跟着角度走"，不能是一个固定的外接框
    hop = pygame.Rect(int(r.cx) - 13, int(HEAD) - 40, 26, player.Player.HEIGHT)
    r.angle = math.pi / 2
    _check(u"臂朝下时命中跳到半空的人", r.hits(hop))
    # 四臂十字没有"全水平"的形态，但转到 45° 时两条臂都斜在两侧，
    # 正下方是空的 —— 这个空当必须真的能钻过去，否则就是个外接圆。
    r.angle = math.pi / 4
    _check(u"臂转到对角线时正下方让开", not r.hits(hop))

    # 远处的玩家永远安全
    far = pygame.Rect(2000, 600, 26, 70)
    hit_far = 0
    for _ in range(240):
        r.update(DT)
        if r.hits(far):
            hit_far += 1
    _check(u"离得远不会被扫到", hit_far == 0, u"%d 帧" % hit_far)

    # 逆时针：屏幕 y 向下，角度递减即视觉逆时针
    r.reset()
    a0 = r.angle
    r.update(0.2)
    _check(u"逆时针旋转", r.angle < a0,
           u"%.3f → %.3f" % (a0, r.angle))


def test_pendulum():
    _section(u"M7 荡锤")

    h = enemy.Pendulum(1000.0, 400.0, phase=0.0)
    worst = 0.0
    for _ in range(600):
        h.update(DT)
        bx, by = h.bob()
        d = math.hypot(bx - h.px, by - h.py)
        worst = max(worst, abs(d - config.PENDULUM_ARM))
    _check(u"锤心始终在摆长上（不做假动画）", worst < 0.01,
           u"最大偏差 %.4fpx" % worst)

    bobs = []
    h.reset()
    for _ in range(400):
        h.update(DT)
        bobs.append(h.bob())
    _check(u"摆动到两侧（不是原地晃）",
           max(b[0] for b in bobs) - min(b[0] for b in bobs) > 100,
           u"水平行程 %.0fpx" % (max(b[0] for b in bobs) - min(b[0] for b in bobs)))
    _check(u"最高点高于最低点（真的在摆而不是平移）",
           max(b[1] for b in bobs) - min(b[1] for b in bobs) > 40,
           u"竖直行程 %.0fpx" % (max(b[1] for b in bobs) - min(b[1] for b in bobs)))

    # 站在锤心最低点正下方：会被扫到；但一定存在"摆到外侧"的安全时刻
    low = 400.0 + config.PENDULUM_ARM
    under = pygame.Rect(1000 - 13, int(low) - 35, 26, 70)
    h.reset()
    hit = 0
    for _ in range(600):
        h.update(DT)
        if h.hits(under):
            hit += 1
    _check(u"锤摆过正下方时会命中", hit > 0, u"%d 帧" % hit)
    _check(u"但不是必死（有安全相位）", hit < 600, u"命中 %d/600" % hit)


def test_m7_parse():
    _section(u"M7 关卡解析：新机关与空中道具")
    try:
        w = world.World.load(L5)
    except world.LevelError as exc:
        _check(u"l5 可加载", False, exc.describe())
        return None

    _check(u"l5 尺寸 66x14", (w.width_tiles, w.height_tiles) == (66, 14),
           u"%d x %d" % (w.width_tiles, w.height_tiles))
    _check(u"2 只走地怪", len(w.walkers) == 2, u"%d 只" % len(w.walkers))
    _check(u"1 个刺轮", len(w.rotors) == 1, u"%d 个" % len(w.rotors))
    _check(u"1 个荡锤", len(w.hammers) == 1, u"%d 个" % len(w.hammers))
    _check(u"1 把伞", len(w.gliders) == 1, u"%d 把" % len(w.gliders))
    _check(u"2 个篝火", len(w.checkpoints) == 2,
           u"%d 个：%s" % (len(w.checkpoints),
                          [c["col"] for c in w.checkpoints]))
    # 索引必须等于"跑到的先后"。老版本按地图行序排：水池前那盏在天上第 8 行、
    # 荡锤前那盏贴地第 10 行，于是右边那盏排到了左边那盏前面，点亮顺序一乱，
    # "只允许往关卡后面点亮"的规则就把水池前那盏永久封死了。
    cols = [c["col"] for c in w.checkpoints]
    _check(u"篝火按列升序排列（= 跑到的先后）", cols == sorted(cols), u"%s" % cols)

    # 刺轮是"禁跳区"，玩家在它下面本来就没有跳的需求；必须有一只走地怪
    # 把这条道占住，刀片才有意义。
    rot0 = w.rotors[0]
    under = [wk for wk in w.walkers if wk.left <= rot0.cx <= wk.right]
    _check(u"有一只走地怪在刺轮下面巡逻", bool(under),
           u"%s" % [(round(wk.left), round(wk.right)) for wk in w.walkers])
    if under:
        wk = under[0]
        reach_x = config.ROTOR_ARM_LEN + config.ROTOR_TIP_R + player.Player.WIDTH
        room = max(rot0.cx - reach_x - wk.left, wk.right - (rot0.cx + reach_x))
        _check(u"巡逻段有一头在刀片扫掠圈外（能安全起跳）", room >= 20.0,
               u"最近的安全余量 %.0fpx" % room)

    # 篝火的**重生点**不能在机关扫掠范围内：复活即被砸，比没有存档点更糟
    ham0 = w.hammers[0]
    sweep = (config.PENDULUM_ARM * math.sin(config.PENDULUM_AMP)
             + config.PENDULUM_BOB_R + player.Player.WIDTH)
    for cp in w.checkpoints:
        _check(u"篝火 %d 列重生点不在荡锤摆幅内" % cp["col"],
               abs(cp["spawn"][0] + player.Player.WIDTH * 0.5 - ham0.px)
               > sweep, u"距离 %.0fpx / 摆幅 %.0fpx"
               % (abs(cp["spawn"][0] + 13 - ham0.px), sweep))

    # 走地怪必须站在地上
    for wk in w.walkers:
        _check(u"走地怪脚下是实心",
               w.is_solid_px(wk.cx, wk.ground_y + 4),
               u"x=%.0f ground=%.0f" % (wk.cx, wk.ground_y))

    # 吊点上方必须是横梁，否则锤子像凭空吊着
    for h in w.hammers:
        _check(u"荡锤吊在横梁下", w.is_solid_px(h.px, h.py - 6),
               u"吊点 (%.0f, %.0f)" % (h.px, h.py))

    # 半空中的伞：悬在水面上方，底边明显高于岸面——"站着够不到，得跳出去"
    it = w.gliders[0]
    col = it["col"]
    ledge = None
    for dc in (-1, 1):
        g = w.ground_y_below((col + dc) * config.TILE + config.TILE // 2,
                             it["rect"].bottom + 4)
        if g is not None:
            ledge = g if ledge is None else min(ledge, g)
    _check(u"伞悬在岸面上方 1~2 格",
           ledge is not None and 0 < ledge - it["rect"].bottom <= 2 * config.TILE,
           u"伞底边 %d，岸面 %s" % (it["rect"].bottom, ledge))
    _check(u"伞悬在水面上（脚下没有落脚点）",
           w.ground_y_below(it["rect"].centerx, it["rect"].bottom + 2) is None,
           u"脚下地面 %s"
           % w.ground_y_below(it["rect"].centerx, it["rect"].bottom + 2))
    # 站在岸边（最后一格）够不到：判定区在水的正上方，只靠走是拿不到的
    stand = pygame.Rect(col * config.TILE - player.Player.WIDTH,
                        (ledge or 0) - player.Player.HEIGHT,
                        player.Player.WIDTH, player.Player.HEIGHT)
    _check(u"站在岸边够不到（必须跳出去）", not stand.colliderect(it["rect"]),
           u"站立 %s / 判定 %s" % (stand, it["rect"]))
    return w


def test_m7_scene(app):
    _section(u"M7 踩怪 / 机关致死 / 重开复位")

    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(L5)
    w = scene.world
    if w is None:
        _check(u"l5 可加载", False, scene.load_error)
        return
    W = player.Player.WIDTH
    H = player.Player.HEIGHT

    # ---- 从上方落到走地怪头上：踩死 + 反弹 ----
    wk = w.walkers[0]
    scene.player.teleport(wk.cx - W * 0.5, wk.ground_y - H - 60)
    scene.invuln = 0.0
    scene.override_axis = 0.0
    frames = 0
    while not scene.player.stomp_count and frames < 60:
        scene.update(DT)
        frames += 1
    _check(u"落到头顶能踩死", scene.player.stomp_count == 1,
           u"%d 帧后踩中 %d 次（state=%s）"
           % (frames, scene.player.stomp_count, wk.state))
    _check(u"踩死时玩家还在（不是同归于尽）", scene.deaths == 0,
           u"死亡 %d 次：%s" % (scene.deaths, scene.last_death_cause))
    _check(u"踩完被弹起来", scene.player.vy < 0,
           u"vy=%.0f" % scene.player.vy)
    _check(u"被踩的怪进入闪烁", wk.state == "dying", wk.state)
    # 闪烁期没有判定：接着跑几帧，人还在空中/刚落地，都不该再死一次
    for _ in range(8):
        scene.update(DT)
    _check(u"踩死之后不会再被判死", scene.deaths == 0,
           u"死亡 %d 次：%s" % (scene.deaths, scene.last_death_cause))

    # ---- 侧面撞上去会死 ----
    scene.restart()
    wk = w.walkers[0]
    scene.player.teleport(wk.cx - W * 0.5, wk.ground_y - H)
    scene.invuln = 0.0
    scene.update(DT)
    _check(u"侧面撞到走地怪会死",
           scene.deaths == 1 and u"走地怪" in scene.last_death_cause,
           u"死亡 %d 次，原因「%s」" % (scene.deaths, scene.last_death_cause))

    # ---- 刺轮：贴地跑过是安全的，跳起来才挨 ----
    # 这一段有只走地怪正好巡逻到刀片下面（M7.2 的设计）。这里测的是刀片
    # 本身，所以先把怪收起来，测完再放回去。
    saved_walkers = w.walkers
    w.walkers = []
    scene.restart()
    rot = w.rotors[0]
    scene.player.teleport(rot.cx - 120 - W * 0.5, 11 * config.TILE - H)
    scene.invuln = 0.0
    scene.override_axis = 1.0
    frames = 0
    while scene.player.x < rot.cx + 70 and frames < 400:
        scene.update(DT)
        frames += 1
    scene.override_axis = None
    _check(u"贴地从刀片下方跑过去不会死", scene.deaths == 0,
           u"%d 帧跑到 x=%.0f，死亡 %d 次：%s"
           % (frames, scene.player.x, scene.deaths, scene.last_death_cause))

    # 同一位置换成"跳着过"：这是它唯一该杀人的方式
    scene.restart()
    scene.player.teleport(rot.cx - W * 0.5, 11 * config.TILE - H)
    scene.invuln = 0.0
    scene.input.jump_pressed = True
    scene.input.jump_held = True
    frames = 0
    while not scene.deaths and frames < 200:
        scene.update(DT)
        frames += 1
    scene.input.jump_held = False
    _check(u"在刀片下面起跳会被打下来",
           scene.deaths == 1 and u"刀片" in scene.last_death_cause,
           u"%d 帧（%.1fs）后死亡：「%s」"
           % (frames, frames * DT, scene.last_death_cause))

    w.walkers = saved_walkers

    # ---- 荡锤砸死 ----
    scene.restart()
    ham = w.hammers[0]
    scene.player.teleport(ham.px - W * 0.5, 11 * config.TILE - H)
    scene.invuln = 0.0
    frames = 0
    while not scene.deaths and frames < 400:
        scene.update(DT)
        frames += 1
    _check(u"站在锤子下面会被砸死",
           scene.deaths == 1 and u"荡锤" in scene.last_death_cause,
           u"%d 帧（%.1fs）后死亡：「%s」"
           % (frames, frames * DT, scene.last_death_cause))

    # ---- 重开：怪复活、机关回相位 ----
    scene.restart()
    _check(u"重开后走地怪全部复活",
           all(wk.alive for wk in w.walkers),
           u"%s" % [wk.state for wk in w.walkers])
    _check(u"重开后玩家重建，整关统计归零", scene.player.stomp_count == 0,
           u"%d" % scene.player.stomp_count)
    _check(u"重开后刺轮回到初始相位",
           abs(w.rotors[0].angle - w.rotors[0].phase) < 1e-6,
           u"angle=%.3f phase=%.3f" % (w.rotors[0].angle, w.rotors[0].phase))


def test_m7_air_glider(app):
    _section(u"M7 半空中的滑翔伞")

    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(L5)
    w = scene.world
    if w is None:
        _check(u"l5 可加载", False, scene.load_error)
        return

    # 伞挂在"跳满才够到"的高度上：判定区底边离岸面正好 2 格。
    # 这条是玩家的反馈——原来挂在 1 格，点一下跳就拿到了，于是玩家学会了
    # "跳一下"，然后在坑边被水吞掉：他根本不知道自己需要跳满。
    it = w.gliders[0]
    _check(u"伞的判定区底边在岸面往上 2 格",
           it["rect"].bottom == 9 * config.TILE - 2 * config.TILE,
           u"底边 %d，岸面 %d" % (it["rect"].bottom, 9 * config.TILE))

    # 低跳拿不到：按住 4 帧就松手（JUMP_CUT 会切掉上升速度），跳到一半
    scene.player.teleport(56 * config.TILE - player.Player.WIDTH,
                          9 * config.TILE - player.Player.HEIGHT)
    scene.override_axis = 1.0
    scene.input.jump_held = True
    scene.input.jump_pressed = True
    for i in range(30):
        if i == 4:
            scene.input.jump_held = False
            scene.input.jump_released = True
        scene.update(DT)
    _check(u"点一下跳（低跳）拿不到伞", not scene.player.has_glider,
           u"has_glider=%s y=%.0f" % (scene.player.has_glider, scene.player.y))

    # 低跳这一趟大概率已经掉进水里记了一次死亡，重新载一次关，
    # 后面的"一跳到底"要在干净的计数上跑。
    scene.input.jump_held = False
    scene.load_level(L5)
    w = scene.world
    if w is None:
        _check(u"l5 可加载", False, scene.load_error)
        return

    # 从岸上跳出去：伞在水面上方，必须靠跳（而不是走过去）拿
    scene.player.teleport(56 * config.TILE - player.Player.WIDTH,
                          9 * config.TILE - player.Player.HEIGHT)
    scene.override_axis = 1.0
    scene.input.jump_held = True
    scene.input.jump_pressed = True
    got_air = False
    for _ in range(70):
        scene.update(DT)
        if scene.player.has_glider:
            got_air = not scene.player.on_ground
            break
    _check(u"跳出去能拿到半空中的伞",
           scene.player.has_glider, u"has_glider=%s" % scene.player.has_glider)
    _check(u"拿到时人在空中（不是站着捡的）", got_air,
           u"on_ground=%s y=%.0f" % (scene.player.on_ground, scene.player.y))

    frames = 0
    while not scene.goal_reached and frames < 600:
        scene.input.jump_held = True
        scene.update(DT)
        frames += 1
    _check(u"滑翔过水坑到达对岸", scene.goal_reached and scene.deaths == 0,
           u"%d 帧（%.1fs）通关，死亡 %d 次"
           % (frames, frames * DT, scene.deaths))


def test_m7_playable(app):
    _section(u"M7 第 5 关地形可通关")

    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(L5)
    w = scene.world
    if w is None:
        _check(u"l5 可加载", False, scene.load_error)
        return

    # 只测地形与滑翔：机关全关（它们测的是反应，不是地形）
    w.bats = []
    w.ufos = []
    w.rock_spawners = []
    w.walkers = []
    w.rotors = []
    w.hammers = []
    w.enemies = []
    w.rocks = []

    scene.override_axis = 1.0
    frames = 0
    for f in range(3600):
        _auto_step(scene)
        scene.update(DT)
        frames = f
        if scene.goal_reached:
            break
    scene.override_axis = None
    scene.input.jump_held = False
    _check(u"l5 从出生点跑到终点", scene.goal_reached,
           u"%d 帧（%.1f 秒），金币 %d/%d，死亡 %d"
           % (frames, frames * DT, w.taken_coins, w.total_coins, scene.deaths))


def test_m7_checkpoint(app):
    _section(u"M7 第 5 关的篝火")

    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(L5)
    w = scene.world
    if w is None:
        _check(u"l5 可加载", False, scene.load_error)
        return

    cps = sorted(w.checkpoints, key=lambda c: c["col"])
    _check(u"两处篝火分别在通道出口与水池前",
           [c["col"] for c in cps] == [27, 55],
           u"%s" % [c["col"] for c in cps])

    # 荡锤前那个：点亮 → 在锤子下面送死 → 重生回篝火，而不是关底
    cp = cps[0]
    scene.player.teleport(cp["spawn"][0], cp["spawn"][1])
    _run(scene, 2)
    _check(u"碰到荡锤前的篝火会点亮", cp["active"], u"active=%s" % cp["active"])

    ham = w.hammers[0]
    scene.invuln = 0.0
    scene.player.teleport(ham.px - player.Player.WIDTH * 0.5,
                          11 * config.TILE - player.Player.HEIGHT)
    frames = 0
    while not scene.deaths and frames < 400:
        scene.update(DT)
        frames += 1
    _check(u"站在锤子下面还是会死", scene.deaths == 1,
           u"%d 帧，原因「%s」" % (frames, scene.last_death_cause))

    _run(scene, int(config.DEATH_FREEZE / DT) + 3)
    _check(u"死在荡锤下会回到篝火而不是从头跑",
           abs(scene.player.x - cp["spawn"][0]) < 1.0,
           u"x=%.0f，篝火 x=%d" % (scene.player.x, cp["spawn"][0]))

    # 重生点必须在摆幅之外：否则复活即被砸，比没有存档点更糟
    _run(scene, 90)
    _check(u"站在篝火旁边不会被动到", scene.deaths == 1,
           u"死亡 %d 次：「%s」" % (scene.deaths, scene.last_death_cause))

    # ---- 第二盏（水池前）必须也能点亮 ----
    # 这就是玩家报的那个"滑翔伞前的火堆不触发"：篝火列表按地图行序排，
    # 水池前那盏（更靠右）的索引反而更小，点亮荡锤前那盏之后就再也点不亮它。
    cp2 = cps[1]
    scene.player.teleport(cp2["spawn"][0], cp2["spawn"][1])
    _run(scene, 2)
    _check(u"水池前那盏篝火也能点亮", cp2["active"],
           u"active=%s，索引 %d" % (cp2["active"], scene.checkpoint_index))
    _check(u"点亮后重生点挪到水池前", scene.checkpoint == cp2["spawn"],
           u"checkpoint=%s，期望 %s" % (scene.checkpoint, cp2["spawn"]))

    deaths_before = scene.deaths
    scene.invuln = 0.0
    scene.player.teleport(59 * config.TILE, 9 * config.TILE - player.Player.HEIGHT)
    frames = 0
    while scene.deaths == deaths_before and frames < 200:
        scene.update(DT)
        frames += 1
    _run(scene, int(config.DEATH_FREEZE / DT) + 3)
    _check(u"掉进水池会回水池前的篝火", 
           abs(scene.player.x - cp2["spawn"][0]) < 1.0,
           u"x=%.0f，篝火 x=%d" % (scene.player.x, cp2["spawn"][0]))


# ---------------------------------------------------------------- M8 隐形机关

L6 = os.path.join(config.LEVEL_DIR, "l6.txt")
M8_FLOOR = 11 * config.TILE          # l6 的地面高度（脚底 y）


def _m8_scene(app, path=None):
    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(path or L6)
    return scene


def _m8_place(scene, x, feet=None):
    feet = M8_FLOOR if feet is None else feet
    scene.player.teleport(x, feet - player.Player.HEIGHT)
    scene.camera.snap_to(scene.player.rect)
    scene.invuln = 0.0
    scene.death_timer = 0.0
    scene.world.reset_traps()


def _m8_drive(scene, frames, axis=1.0):
    scene.override_axis = axis
    for _ in range(frames):
        scene.update(DT)


def _m8_wait_death(scene, frames):
    """跑到死为止，返回用了几帧（没死返回 frames）。"""
    n = scene.deaths
    i = 0
    while i < frames and scene.deaths == n:
        scene.update(DT)
        i += 1
    return i


def test_m8_parse():
    _section(u"M8 第 6 关：四种隐形机关")
    try:
        w = world.World.load(L6)
    except world.LevelError as exc:
        _check(u"l6 可加载", False, exc.describe())
        return None

    _check(u"l6 尺寸 72x14", (w.width_tiles, w.height_tiles) == (72, 14),
           u"%d x %d" % (w.width_tiles, w.height_tiles))
    _check(u"11 格伪装砖", len(w.bricks) == 11, u"%d 格" % len(w.bricks))
    _check(u"3 根天花板落刺", len(w.drop_spikes) == 3,
           u"%d 根" % len(w.drop_spikes))
    _check(u"1 堵突墙", len(w.risers) == 1, u"%d 堵" % len(w.risers))
    _check(u"1 处二连落石", len(w.twins) == 1, u"%d 处" % len(w.twins))
    cols = [c["col"] for c in w.checkpoints]
    _check(u"3 个篝火且按列升序", cols == sorted(cols) and len(cols) == 3,
           u"%s" % cols)

    # 伪装砖必须真的在"地面"那一层：顶边就是行走面，踩上去才成立
    _check(u"伪装砖顶边与地面齐平",
           all(b.rect.top == M8_FLOOR for b in w.bricks),
           u"%s" % sorted(set(b.rect.top for b in w.bricks)))
    # 砖下面必须是空的，否则塌了也看不出，机关等于没放
    _check(u"伪装砖下面是空的（能看见坑）",
           all(not w.is_solid_px(b.rect.centerx, b.rect.bottom + 6)
               for b in w.bricks),
           u"%s" % [(b.col, w.is_solid_px(b.rect.centerx, b.rect.bottom + 6))
                    for b in w.bricks])

    # 落刺必须挂在天花板上
    for s in w.drop_spikes:
        _check(u"落刺 %.0f 挂在天花板下" % s.cx,
               w.is_solid_px(s.cx, s.top_y - 6),
               u"top=%.0f" % s.top_y)

    # 突墙：地面上的槽、比跳高还高
    for r in w.risers:
        _check(u"突墙站在地面上", w.is_solid_px(r.cx, r.floor_y + 4),
               u"floor=%.0f" % r.floor_y)
        _check(u"突墙比跳高更高（跳不过去）",
               config.WALL_H > 127 + 12,
               u"墙 %d / 跳高 127" % config.WALL_H)
    return w


def test_m8_brick(app):
    _section(u"M8 伪装砖：跑得过去，停不下来")

    scene = _m8_scene(app)
    w = scene.world
    _m8_place(scene, 4 * config.TILE)
    _m8_drive(scene, 6)
    _m8_drive(scene, 96)
    _check(u"一路跑过 4 格砖不掉下去", scene.deaths == 0,
           u"死亡 %d「%s」x=%.0f" % (scene.deaths, scene.last_death_cause,
                                    scene.player.x))
    _check(u"跑过之后砖确实塌了",
           any(b.state == "gone" for b in w.bricks),
           u"%s" % [b.state for b in w.bricks[:4]])

    # 站在砖上不动 → 塌 → 掉进刺里
    scene = _m8_scene(app)
    _m8_place(scene, 8 * config.TILE)
    _m8_drive(scene, 1, axis=0.0)
    used = _m8_wait_death(scene, 90)
    _check(u"站在砖上不动会塌下去摔死", scene.deaths == 1,
           u"%d 帧，原因「%s」" % (used, scene.last_death_cause))

    # 塌掉之后会自己长回来（走回头路不能卡死）
    scene = _m8_scene(app)
    w = scene.world
    _m8_place(scene, 4 * config.TILE)
    for b in w.bricks:
        b.state = "gone"
        b.timer = 0.05
    _m8_drive(scene, int(config.BRICK_RESTORE / DT) + 6, axis=0.0)
    _check(u"塌掉 3 秒后砖自己长回来",
           all(b.state == "idle" for b in w.bricks),
           u"%s" % sorted(set(b.state for b in w.bricks)))


def test_m8_spike(app):
    _section(u"M8 天花板落刺：跑过去，别停下")

    scene = _m8_scene(app)
    w = scene.world
    s0 = w.drop_spikes[0]
    _check(u"平时不判死（收在天花板里）", s0.hitbox() is None,
           u"state=%s" % s0.state)

    # 全速穿过三根刺
    _m8_place(scene, 16 * config.TILE)
    _m8_drive(scene, 4)
    _m8_drive(scene, 150)
    _check(u"全速跑过三根刺不会死", scene.deaths == 0,
           u"死亡 %d「%s」x=%.0f" % (scene.deaths, scene.last_death_cause,
                                    scene.player.x))
    _check(u"跑过的时候刺确实扎下来了",
           any(s.state != "idle" for s in w.drop_spikes),
           u"%s" % [s.state for s in w.drop_spikes])

    # 停在刺底下 → 挨扎
    scene = _m8_scene(app)
    _m8_place(scene, 18 * config.TILE + 20)
    _m8_drive(scene, 1, axis=0.0)
    used = _m8_wait_death(scene, 90)
    _check(u"停在刺底下会被扎到", scene.deaths == 1,
           u"%d 帧，原因「%s」" % (used, scene.last_death_cause))

    # 站在圈里不会被无限连砸（边沿触发）：走完一个周期就闲着
    scene = _m8_scene(app)
    w = scene.world
    s0 = w.drop_spikes[0]
    _m8_place(scene, 18 * config.TILE + 20)
    scene.invuln = 999.0       # 只测上膛逻辑，先别让它把人扎死
    fired = False
    for _ in range(180):
        scene.update(DT)
        if s0.state != "idle":
            fired = True
    _check(u"站在原地会被扎一次", fired and s0.state == "idle",
           u"state=%s" % s0.state)
    for _ in range(60):
        scene.update(DT)
    _check(u"站着不动就一直闲着（不会连着砸）", s0.state == "idle",
           u"state=%s" % s0.state)

    # 玩家实测的死区：走过第 1 座、进到第 2 座的圈里再回头，
    # 第 1 座必须重新放刺。原来"走远了才上膛"用的是 1.6 格触发距离 + 1 格，
    # 两座刺隔 3 格（192px）时人永远走不到"够远"，第 1 座就废了。
    scene = _m8_scene(app)
    w = scene.world
    s0 = w.drop_spikes[0]
    s1 = w.drop_spikes[1]
    _m8_place(scene, 16 * config.TILE)
    scene.invuln = 999.0
    went = False
    for _ in range(140):
        scene.override_axis = 1.0
        scene.update(DT)
        if abs(scene.player.rect.centerx - s1.cx) <= config.SPIKE_TRIGGER:
            went = True
            break
    _check(u"先往前走，进到第 2 座的触发圈里", went,
           u"距第 2 座 %.0fpx" % abs(scene.player.rect.centerx - s1.cx))

    back_fired = False
    for _ in range(160):
        scene.override_axis = -1.0
        scene.update(DT)
        if s0.state != "idle":
            back_fired = True
            break
    _check(u"回头走过第 1 座，它又放刺了（没有死区）", back_fired,
           u"x=%.0f / 第 1 座 %.0f state=%s"
           % (scene.player.rect.centerx, s0.cx, s0.state))


def test_m8_wall(app):
    _section(u"M8 突墙：撞上去就是死，只能等")

    scene = _m8_scene(app)
    w = scene.world
    wl = w.risers[0]
    _m8_place(scene, wl.cx - 6 * config.TILE)
    _m8_drive(scene, 4)

    rose = False
    for i in range(90):
        scene.update(DT)
        if wl.state in ("rise", "hold"):
            rose = True
        if wl.h >= config.WALL_H:
            break
    _check(u"走近之后墙会顶起来", rose and wl.h >= config.WALL_H,
           u"h=%.0f state=%s" % (wl.h, wl.state))
    _check(u"墙是实心的（进碰撞表）", wl.solid() is not None,
           u"solid=%s" % (wl.solid(),))
    _check(u"左面有刺：判定箱比墙面更靠左",
           wl.hitbox() is not None and wl.hitbox().left < wl.rect().left,
           u"刺 %s / 墙 %s" % (wl.hitbox(), wl.rect()))

    # 一路顶着跑 → 撞在刺上死掉（这是玩家要求加的"撞墙的代价"）
    used = _m8_wait_death(scene, 120)
    _check(u"一路顶着跑会撞在刺上死", scene.deaths == 1,
           u"%d 帧「%s」" % (used, scene.last_death_cause))
    _check(u"死因写的是突墙", u"突墙" in scene.last_death_cause,
           u"「%s」" % scene.last_death_cause)

    # 看见墙起来就收脚：一根刺都不碰，等它落下再走
    scene = _m8_scene(app)
    wl = scene.world.risers[0]
    _m8_place(scene, wl.cx - 5 * config.TILE)
    for _ in range(150):
        scene.override_axis = 1.0
        scene.update(DT)
        if wl.state != "idle":
            break
    _m8_drive(scene, 16, axis=0.0)      # 急停：300px/s 刹到 0 只要 16px
    _check(u"停得住（墙起来了没撞上去）", scene.deaths == 0,
           u"死亡 %d「%s」距墙 %.0fpx"
           % (scene.deaths, scene.last_death_cause,
              wl.cx - scene.player.rect.right))

    for _ in range(150):
        scene.update(DT)
        if wl.state == "idle" and wl.h <= 0.5:
            break
    _check(u"墙会自己缩回去", wl.h <= 0.5, u"h=%.0f" % wl.h)
    _m8_drive(scene, 60)
    _check(u"缩回去之后人过得去", scene.player.rect.left > wl.cx,
           u"x=%.0f / 墙 %.0f" % (scene.player.x, wl.cx))
    _check(u"停下等一次全程不死", scene.deaths == 0,
           u"死亡 %d「%s」" % (scene.deaths, scene.last_death_cause))

    # 站在槽上不会被顶起来（唯一的"会卡死"的错误）
    scene = _m8_scene(app)
    wl = scene.world.risers[0]
    _m8_place(scene, wl.cx - player.Player.WIDTH // 2)
    before = scene.player.rect.copy()
    _m8_drive(scene, 60, axis=0.0)
    _check(u"站在槽上墙不会升（不夹人）",
           wl.h <= 0.5 and scene.deaths == 0,
           u"h=%.0f 死亡 %d" % (wl.h, scene.deaths))
    _check(u"站在槽上人也没被挤走",
           abs(scene.player.rect.x - before.x) <= 2,
           u"%d → %d" % (before.x, scene.player.rect.x))


def test_m8_twin(app):
    _section(u"M8 二连落石：远的那块影子先收")

    scene = _m8_scene(app)
    w = scene.world
    tw = w.twins[0]
    _m8_place(scene, 39 * config.TILE)
    _m8_drive(scene, 4)
    _m8_drive(scene, 40)
    _check(u"走近就掉两块石头", len(w.rocks) == 2, u"%d 块" % len(w.rocks))
    if len(w.rocks) == 2:
        wa = w.rocks[0].warn_total
        wb = w.rocks[1].warn_total
        _check(u"远的那块预警更长（影子先出现）", wb > wa,
               u"近 %.2fs / 远 %.2fs" % (wa, wb))
        _check(u"两块石头落点隔 2 格",
               abs(w.rocks[1].x - w.rocks[0].x) == config.TWIN_GAP,
               u"%.0f px" % abs(w.rocks[1].x - w.rocks[0].x))

    # 站中间那一格是安全的
    scene = _m8_scene(app)
    _m8_place(scene, 43 * config.TILE + 19)
    _m8_drive(scene, 1, axis=0.0)
    _m8_drive(scene, 120, axis=0.0)
    _check(u"站在两块影子中间不会死", scene.deaths == 0,
           u"死亡 %d「%s」" % (scene.deaths, scene.last_death_cause))

    # 站在近那块底下会死
    scene = _m8_scene(app)
    _m8_place(scene, 42 * config.TILE + 19)
    _m8_drive(scene, 1, axis=0.0)
    used = _m8_wait_death(scene, 90)
    _check(u"站在近那块底下会被砸到", scene.deaths == 1,
           u"%d 帧，原因「%s」" % (used, scene.last_death_cause))


def test_m8_respawn(app):
    _section(u"M8 重生时机关必须复位")

    scene = _m8_scene(app)
    w = scene.world
    _m8_place(scene, 8 * config.TILE)
    _m8_drive(scene, 1, axis=0.0)
    used = _m8_wait_death(scene, 90)
    _check(u"踩塌伪装砖掉下去会死", scene.deaths == 1,
           u"%d 帧「%s」" % (used, scene.last_death_cause))
    _check(u"死的时候砖确实是塌的",
           any(b.state == "gone" for b in w.bricks),
           u"%s" % [b.state for b in w.bricks[:4]])

    _run(scene, int(config.DEATH_FREEZE / DT) + 4)
    _check(u"重生了", scene.respawn_count == 1, u"%d 次" % scene.respawn_count)
    _check(u"重生后伪装砖全部复位（不会卡死在坑边）",
           all(b.state == "idle" for b in w.bricks),
           u"%s" % [b.state for b in w.bricks[:4]])
    _check(u"重生后场上没有残留的落石", not w.rocks, u"%d 块" % len(w.rocks))

    _check(u"死亡进了日志（列 + 原因）",
           len(scene.death_log) == 1
           and scene.death_log[0][1] == scene.last_death_cause,
           u"%s" % (scene.death_log,))
    _check(u"日志记的是死的那一列（第 8~10 列之间）",
           len(scene.death_log) == 1 and 7 <= scene.death_log[0][0] <= 10,
           u"%s" % (scene.death_log,))

    # 重生点本身不能在机关的触发圈里
    for cp in w.checkpoints:
        cx = cp["spawn"][0] + player.Player.WIDTH // 2
        for s in w.drop_spikes:
            _check(u"篝火 %d 列重生点不在落刺的触发圈里" % cp["col"],
                   abs(cx - s.cx) > config.SPIKE_TRIGGER,
                   u"距离 %.0fpx" % abs(cx - s.cx))


def test_m8_death_summary(app):
    _section(u"M8 死因日志与通关汇总")

    scene = _m8_scene(app)
    p = scene.player
    for col, cause in ((9, u"掉进深坑"), (9, u"掉进深坑"), (22, u"落刺扎中")):
        p.teleport(col * config.TILE, 0)
        scene.death_timer = 0.0
        scene.die(cause)

    _check(u"三次死亡都记下了", len(scene.death_log) == 3,
           u"%s" % (scene.death_log,))
    counts = {}
    for col, cause in scene.death_log:
        counts[(col, cause)] = counts.get((col, cause), 0) + 1
    _check(u"同一处死两次能归成一组", counts.get((9, u"掉进深坑")) == 2,
           u"%s" % (counts,))

    ok = True
    try:
        scene._print_death_summary()        # 开关关着：不打字，也不能报错
        config.LOG_EVENTS = True
        scene._print_death_summary()        # 开关开着：打一行
    except Exception as exc:                # 汇总出错会让通关瞬间崩掉
        ok = False
        print(u"        异常：%r" % (exc,))
    finally:
        config.LOG_EVENTS = False
    _check(u"死因汇总在两种开关状态下都不报错", ok, u"")


def test_m8_playable(app):
    _section(u"M8 第 6 关整关跑通")

    scene = _m8_scene(app)
    w = scene.world

    # 一个只会两件事的自动驾驶：一直往右；前面有升起的墙就停。
    # 它证明的是"这关的机关有解"，而不是"操作好"——落刺、伪装砖、
    # 二连石都靠"别停"过，突墙靠"等它落下"过，一个跳都不用按。
    reached = False
    frames = 0
    waits = 0
    while frames < 2000:
        blocked = False
        for wl in w.risers:
            r = wl.solid()
            if r is not None and 0 < r.left - scene.player.rect.right < 96:
                blocked = True
        if blocked:
            waits += 1
        scene.override_axis = 0.0 if blocked else 1.0
        scene.update(DT)
        frames += 1
        if scene.goal_reached:
            reached = True
            break

    _check(u"自动驾驶跑完全关", reached,
           u"%d 帧（%.1f 秒），x=%.0f" % (frames, frames * DT, scene.player.x))
    _check(u"全程 0 死亡", scene.deaths == 0,
           u"死亡 %d「%s」" % (scene.deaths, scene.last_death_cause))
    _check(u"路上确实等过突墙", waits > 0, u"等了 %d 帧" % waits)
    _check(u"金币至少拿到一半", w.taken_coins * 2 >= w.total_coins,
           u"%d / %d" % (w.taken_coins, w.total_coins))
    print(u"    通关：%.1f 秒，金币 %d/%d，死亡 %d"
          % (frames * DT, w.taken_coins, w.total_coins, scene.deaths))


# ---------------------------------------------------------------- M9 存档与界面

def test_m9_save():
    _section(u"M9 存档：读写、纪录、解锁")

    tmp = os.path.join(tempfile.mkdtemp(prefix="pyrun_save_"), "s.json")
    sv = save_mod.Save(tmp)
    _check(u"没有存档时按新玩家处理",
           sv.cleared_count() == 0 and not sv.all_unlocked)
    _check(u"第一关默认解锁", sv.unlocked("l1"))
    _check(u"第二关默认锁着", not sv.unlocked("l2"))

    rec = sv.record("l1", 40.0, 8, 12, 3)
    _check(u"首次通关记为新纪录",
           rec.get("first") and rec.get("time"), u"%s" % (rec,))
    _check(u"通关后下一关解锁", sv.unlocked("l2"))
    _check(u"文件已落盘", os.path.isfile(tmp))

    rec = sv.record("l1", 45.0, 10, 12, 1)
    _check(u"更慢的一局不刷新时间",
           not rec.get("time") and sv.best_time("l1") == 40.0,
           u"best=%.1f rec=%s" % (sv.best_time("l1"), rec))
    _check(u"金币更多会刷新", rec.get("coins") and sv.best_coins("l1") == 10,
           u"coins=%d" % sv.best_coins("l1"))

    rec = sv.record("l1", 38.0, 6, 12, 5)
    _check(u"更快的一局刷新时间",
           rec.get("time") and sv.best_time("l1") == 38.0,
           u"best=%.1f" % sv.best_time("l1"))

    sv2 = save_mod.Save(tmp)
    _check(u"重新读盘成绩一致",
           sv2.best_time("l1") == 38.0 and sv2.is_cleared("l1"),
           u"%s" % (sv2.entry("l1"),))
    _check(u"解锁状态也持久", sv2.unlocked("l2"))

    # 关卡后来加了金币（11 → 14 枚）：旧的 11/11 不能跟新的比大小
    sv.record("l1", 38.0, 5, 14, 0)
    _check(u"金币总数变了就作废旧记录", sv.best_coins("l1") == 5,
           u"coins=%d total=%d" % (sv.best_coins("l1"),
                                   sv.entry("l1").get("total")))

    sv.record("l1", 39.0, 14, 14, 0)
    _check(u"满金币算完美", sv.perfect("l1"))
    _check(u"完美要求先通关", not sv.perfect("l2"))

    sv.set_all_unlocked(True)
    _check(u"全解锁开关生效并落盘",
           sv.unlocked("l6") and save_mod.Save(tmp).unlocked("l6"))

    # ---- 坏存档：三条都不能抛，只能"退化成新玩家 + 留一句警告" ----
    io_utils.write_text(tmp, "{ 这不是 json")
    bad = save_mod.Save(tmp)
    _check(u"坏 JSON 不崩、按新玩家处理", bad.cleared_count() == 0)

    io_utils.write_text(tmp, u'{"version": 1, "levels": [1, 2, 3]}')
    bad = save_mod.Save(tmp)
    _check(u"levels 类型错不崩且记警告",
           bad.cleared_count() == 0 and bool(bad.warnings),
           u"warnings=%s" % bad.warnings)

    io_utils.write_text(tmp, u'{"version": 1, "levels": {"l9": {"cleared": true}}}')
    bad = save_mod.Save(tmp)
    _check(u"不认识的关卡被丢掉并记警告",
           bad.cleared_count() == 0 and bool(bad.warnings),
           u"warnings=%s" % bad.warnings)

    io_utils.write_text(tmp, u'{"version": 1, "levels": {"l1": {"cleared": true,'
                             u' "time": "很快", "coins": -3}}}')
    bad = save_mod.Save(tmp)
    _check(u"单个坏字段不带走整条记录",
           bad.is_cleared("l1") and bad.best_time("l1") is None
           and bad.best_coins("l1") == -1,
           u"%s" % (bad.entry("l1"),))


def test_m9_catalog():
    _section(u"M9 关卡目录")

    _check(u"目录里有六关", levels_catalog.count() == 6,
           u"%d 关" % levels_catalog.count())
    _check(u"关卡文件都在", not levels_catalog.missing_files(),
           u"缺：%s" % levels_catalog.missing_files())
    _check(u"key 不重复",
           len(set(lv["key"] for lv in levels_catalog.LEVELS))
           == levels_catalog.count())
    _check(u"路径反查 key",
           levels_catalog.path_to_key(os.path.join(config.LEVEL_DIR, "l4.txt"))
           == "l4")
    _check(u"最后一关没有下一关",
           levels_catalog.next_of("l6") is None)
    _check(u"第四关的下一关是第五关",
           levels_catalog.next_of("l4")["key"] == "l5")


def test_m9_select(app):
    _section(u"M9 关卡选择界面")

    app.save.clear()
    sel = scenes.LevelSelectScene(app)
    sel.on_enter()
    _check(u"渲染六张卡片", len(sel._cards) == 6, u"%d 张" % len(sel._cards))
    sel.draw(app.screen)
    pygame.display.flip()
    _check(u"选关界面可渲染（含锁与对勾）", True, u"已绘制一帧")
    _check(u"默认光标在第一个未通关的关", sel.index == 0, u"index=%d" % sel.index)

    # 方向键按网格走
    sel.handle_event(_key(pygame.K_RIGHT))
    _check(u"→ 移到下一列", sel.index == 1, u"index=%d" % sel.index)
    sel.handle_event(_key(pygame.K_DOWN))
    _check(u"↓ 跨一行 +3", sel.index == 4, u"index=%d" % sel.index)
    sel.handle_event(_key(pygame.K_DOWN))
    _check(u"最后一行按 ↓ 不动", sel.index == 4, u"index=%d" % sel.index)
    sel.handle_event(_key(pygame.K_LEFT))
    sel.handle_event(_key(pygame.K_LEFT))
    _check(u"第一列按 ← 不动", sel.index == 3, u"index=%d" % sel.index)

    # 锁着的关卡进不去
    sel.index = 3
    ok = sel._activate()
    _check(u"锁着的关卡进不去",
           not ok and app.scenes._pending is None and bool(sel.notice),
           u"ok=%s notice=%s" % (ok, sel.notice))

    # 通关三关之后，第四关开锁，光标也自动顶过去
    for k in ("l1", "l2", "l3"):
        app.save.record(k, 30.0, 5, 10, 0)
    sel.on_enter()
    _check(u"通关后光标推进到下一关", sel.index == 3, u"index=%d" % sel.index)
    sel.index = 3
    ok = sel._activate()
    _check(u"解锁后能进入", ok and app.scenes._pending == "game",
           u"pending=%s" % app.scenes._pending)
    _check(u"进的是第四关",
           os.path.basename(app.level_path) == "l4.txt", app.level_path)
    app.scenes._pending = None        # 别把切换带进后面的用例

    # F2 全解锁
    sel.handle_event(_key(pygame.K_F2))
    _check(u"F2 一键全解锁", app.save.unlocked("l6") and sel.notice,
           u"notice=%s" % sel.notice)

    # 清档要按两次
    sel.handle_event(_key(pygame.K_DELETE))
    _check(u"第一次 Delete 只提示不清档",
           sel._confirm_clear and app.save.cleared_count() == 3,
           u"confirm=%s 已通关 %d" % (sel._confirm_clear, app.save.cleared_count()))
    sel.handle_event(_key(pygame.K_DELETE))
    _check(u"第二次 Delete 才真的清空",
           not sel._confirm_clear and app.save.cleared_count() == 0,
           u"已通关 %d" % app.save.cleared_count())

    # 确认窗口会自己过期：等它超时后，单按一次不能清档
    app.save.record("l1", 10.0, 1, 10, 0)
    sel.handle_event(_key(pygame.K_DELETE))
    for _ in range(200):
        sel.update(DT)
    sel.handle_event(_key(pygame.K_DELETE))
    _check(u"确认窗口过期后不会误清档",
           app.save.cleared_count() == 1 and sel._confirm_clear,
           u"已通关 %d confirm=%s" % (app.save.cleared_count(),
                                      sel._confirm_clear))


def test_m9_menu(app):
    _section(u"M9 主菜单随进度变化")

    app.save.clear()
    menu = scenes.MenuScene(app)
    menu.on_enter()
    _check(u"新玩家显示「开始游戏」",
           menu.items[0][0] == u"开始游戏", menu.items[0][0])
    _check(u"菜单四项（含设置）",
           len(menu.items) == 4
           and menu.items[2][1] == "settings"
           and menu.items[3][1] == "quit",
           u"%s" % (menu.items,))

    app.save.record("l1", 30.0, 10, 12, 0)
    app.save.record("l2", 30.0, 10, 12, 0)
    menu.on_enter()
    _check(u"有进度后显示「继续游戏」",
           u"继续游戏" in menu.items[0][0] and u"滑翔伞" in menu.items[0][0],
           menu.items[0][0])
    _check(u"「开始游戏」直接进未通关的关",
           menu.items[0][1] == "play")

    # 点"开始游戏"应该落到第三关
    app.save.clear()
    app.save.record("l1", 30.0, 10, 12, 0)
    menu.on_enter()
    menu.index = 0
    menu._activate()
    _check(u"进入的是第一个未通关的关",
           os.path.basename(app.level_path) == "l2.txt", app.level_path)
    app.scenes._pending = None


def test_m9_pause(app):
    _section(u"M9 暂停面板")

    app.save.clear()
    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(config.DEFAULT_LEVEL)
    scene.override_axis = 1.0
    for _ in range(20):
        scene.update(DT)
    t0 = scene.level_time
    x0 = scene.player.x
    y0 = scene.player.y

    scene.handle_event(_key(pygame.K_ESCAPE))
    _check(u"Esc 打开暂停", scene.paused and scene.pause_index == 0)
    scene.draw(app.screen)
    pygame.display.flip()
    _check(u"暂停面板可渲染", True, u"已绘制一帧")

    # 暂停期间：计时不走、角色不动、世界不推进
    w0 = scene.world.time
    for _ in range(60):
        scene.update(DT)
    _check(u"暂停时计时不走", abs(scene.level_time - t0) < 1e-9,
           u"%.3f → %.3f" % (t0, scene.level_time))
    _check(u"暂停时角色不动", abs(scene.player.x - x0) < 0.01,
           u"%.1f → %.1f" % (x0, scene.player.x))
    _check(u"暂停时世界也不推进", abs(scene.world.time - w0) < 1e-9,
           u"%.3f → %.3f" % (w0, scene.world.time))

    # 暂停时按空格是"确认当前项"，不是跳。当前项是"继续游戏"，
    # 所以空格的效果是关掉暂停——但角色一毫米都不能动。
    scene.handle_event(_key(pygame.K_SPACE))
    _check(u"暂停里按空格是确认不是跳",
           not scene.paused and abs(scene.player.y - y0) < 0.01
           and abs(scene.player.vy) < 0.01,
           u"paused=%s y=%.1f vy=%.1f" % (scene.paused, scene.player.y,
                                          scene.player.vy))

    # 继续之后计时恢复
    for _ in range(10):
        scene.update(DT)
    _check(u"关掉暂停后继续计时", scene.level_time > t0,
           u"%.3f" % scene.level_time)

    # Esc 再按一次：打开再关掉
    scene.handle_event(_key(pygame.K_ESCAPE))
    scene.handle_event(_key(pygame.K_ESCAPE))
    _check(u"Esc 可以关掉暂停", not scene.paused)

    # "重开本关"
    scene.deaths = 2
    scene.handle_event(_key(pygame.K_ESCAPE))
    scene.pause_index = 1
    scene.handle_event(_key(pygame.K_RETURN))
    _check(u"暂停里重开本关",
           not scene.paused and scene.level_time == 0.0 and scene.deaths == 0,
           u"paused=%s t=%.2f d=%d" % (scene.paused, scene.level_time,
                                       scene.deaths))

    # "选择关卡"
    scene.handle_event(_key(pygame.K_ESCAPE))
    scene.pause_index = 2
    scene.handle_event(_key(pygame.K_RETURN))
    _check(u"暂停里能去选关", app.scenes._pending == "select",
           u"pending=%s" % app.scenes._pending)
    app.scenes._pending = None


def _m9_touch_goal(scene):
    """把角色传进终点区并立刻跑一次判定，模拟"跑到终点"。"""
    g = scene.world.goal_zone
    scene.player.teleport(g.centerx - player.Player.WIDTH // 2,
                          g.centery - player.Player.HEIGHT // 2)
    scene._post_physics()


def test_m9_goal(app):
    _section(u"M9 结算面板与连续挑战")

    app.save.clear()
    scene = scenes.GameScene(app)
    scene.on_enter()
    scene.load_level(config.DEFAULT_LEVEL)
    for _ in range(10):
        scene.update(DT)
    scene.world.taken_coins = 7
    _m9_touch_goal(scene)

    _check(u"碰到终点判定为通关", scene.goal_reached)
    scene.draw(app.screen)
    pygame.display.flip()
    _check(u"结算面板可渲染", True, u"已绘制一帧")
    _check(u"通关立刻写进存档", app.save.is_cleared("l1"),
           u"%s" % (app.save.entry("l1"),))
    _check(u"记下了下一关", scene.next_key == "l2", scene.next_key)
    _check(u"首次通关标记为新纪录", bool(scene.new_record.get("first")),
           u"%s" % (scene.new_record,))
    _check(u"成绩里带着金币数",
           app.save.best_coins("l1") == 7,
           u"coins=%d" % app.save.best_coins("l1"))

    # Enter：连续挑战，直接进下一关
    scene.handle_event(_key(pygame.K_RETURN))
    _check(u"Enter 直接进下一关",
           app.scenes._pending == "game"
           and os.path.basename(app.level_path) == "l2.txt",
           u"pending=%s path=%s" % (app.scenes._pending, app.level_path))
    app.scenes._pending = None

    # R：重来本关
    scene.handle_event(_key(pygame.K_r))
    _check(u"R 重来本关",
           not scene.goal_reached and scene.level_time == 0.0,
           u"goal=%s t=%.2f" % (scene.goal_reached, scene.level_time))

    # 最后一关：没有下一关，Enter 回选关
    scene2 = scenes.GameScene(app)
    scene2.load_level(levels_catalog.path_of("l6"))
    _m9_touch_goal(scene2)
    _check(u"最后一关没有下一关", scene2.next_key == "", scene2.next_key)
    scene2.handle_event(_key(pygame.K_RETURN))
    _check(u"最后一关 Enter 回选关", app.scenes._pending == "select",
           u"pending=%s" % app.scenes._pending)
    app.scenes._pending = None

    # Esc：选关（不是"返回菜单"，那是两回事）
    scene3 = scenes.GameScene(app)
    scene3.load_level(config.DEFAULT_LEVEL)
    _m9_touch_goal(scene3)
    scene3.handle_event(_key(pygame.K_ESCAPE))
    _check(u"结算面板 Esc 去选关", app.scenes._pending == "select",
           u"pending=%s" % app.scenes._pending)
    app.scenes._pending = None


# ---------------------------------------------------------------- M10 音效与设置

def test_m10_audio():
    _section(u"M10 音效：合成与降级")

    names = audio_mod.synth_names()
    _check(u"音效表齐全（9 种以上）", len(names) >= 9, u"%d 种：%s"
           % (len(names), u"、".join(names)))

    bad = []
    for name in names:
        s = audio_mod.synth_peek(name)
        if not s:
            bad.append(name + ":空")
            continue
        dur = len(s) / float(audio_mod.SAMPLE_RATE)
        peak = max(abs(v) for v in s)
        head = max(abs(v) for v in s[:30])
        tail = max(abs(v) for v in s[-30:])
        # 时长 0.02~0.6 秒、有声音但没削波、首尾都收到接近 0（防爆音）
        if not (0.02 <= dur <= 0.60):
            bad.append(u"%s:%.2fs" % (name, dur))
        elif peak < 800 or peak > 32000:
            bad.append(u"%s:peak=%d" % (name, peak))
        elif tail > peak * 0.35:
            bad.append(u"%s:尾 %.0f/%.0f" % (name, tail, peak))
        elif head > peak * 0.85:
            bad.append(u"%s:起音太硬" % name)
    _check(u"每个音效长度/峰值/包络都正常", not bad,
           u"%s" % (bad[:4] if bad else u"全部通过"))

    # 禁用状态：没有声卡时的一切调用都必须安全
    a = audio_mod.Audio(enabled=False)
    _check(u"禁用时不初始化 mixer", not a.available and a.volume > 0.0,
           a.status)
    _check(u"禁用时播放返回 False 不抛", a.play("coin") is False
           and a.play("不存在的音效") is False)
    a.set_volume(0.5)
    _check(u"禁用时改音量不崩", abs(a.volume - 0.5) < 1e-6)
    _check(u"静音开关能翻", a.toggle_mute() is True
           and a.toggle_mute() is False)


def test_m10_settings():
    _section(u"M10 设置：默认值、夹紧、持久化")

    tmp = os.path.join(tempfile.mkdtemp(prefix="pyrun_set_"), "s.json")
    sv = save_mod.Save(tmp)
    _check(u"默认音量 7 档", sv.get_setting("sfx") == 7, sv.get_setting("sfx"))
    _check(u"默认不显示调试", sv.get_setting("show_debug") is False)

    sv.set_setting("sfx", 99)
    _check(u"超过上限夹到 10", sv.get_setting("sfx") == 10)
    sv.set_setting("sfx", -5)
    _check(u"低于下限夹到 0", sv.get_setting("sfx") == 0)
    sv.set_setting("sfx", 6)
    sv.set_setting("show_debug", True)

    sv2 = save_mod.Save(tmp)
    _check(u"设置随存档持久",
           sv2.get_setting("sfx") == 6
           and sv2.get_setting("show_debug") is True,
           u"%s" % (sv2.settings,))

    sv2.clear()
    _check(u"清档不清设置",
           sv2.get_setting("sfx") == 6 and sv2.get_setting("show_debug") is True
           and sv2.cleared_count() == 0)

    # 坏的 settings：坏字段退回默认，好的字段不能跟着丢
    io_utils.write_text(tmp, u'{"version":1,"settings":'
                             u'{"sfx":"大声","show_debug":true},"levels":{}}')
    bad = save_mod.Save(tmp)
    _check(u"坏的音量退回默认、好的开关保留",
           bad.get_setting("sfx") == 7 and bad.get_setting("show_debug") is True,
           u"%s 警告 %s" % (bad.settings, bad.warnings))

    io_utils.write_text(tmp, u'{"version":1,"settings":[1,2],"levels":{}}')
    bad = save_mod.Save(tmp)
    _check(u"整块 settings 类型错不崩", bad.get_setting("sfx") == 7
           and bool(bad.warnings))


def test_m10_settings_scene(app):
    _section(u"M10 设置界面与事件")

    app.save.clear()
    app.save.set_setting("sfx", 7)
    app.save.set_setting("show_debug", False)
    sc = scenes.SettingsScene(app)
    sc.on_enter()
    _check(u"三个可编辑项", len(sc.ITEMS) == 3,
           u"%s" % [k for k, _ in sc.ITEMS])

    sc.index = 0
    sc._adjust(-1)
    _check(u"左键降一档音量", app.save.get_setting("sfx") == 6,
           app.save.get_setting("sfx"))
    _check(u"音量同步到播放器", abs(app.audio.volume - 0.6) < 0.01,
           u"vol=%.2f" % app.audio.volume)

    for _ in range(10):
        sc._adjust(-1)
    _check(u"按到底停在 0", app.save.get_setting("sfx") == 0,
           app.save.get_setting("sfx"))
    for _ in range(14):
        sc._adjust(1)
    _check(u"按到顶停在 10", app.save.get_setting("sfx") == 10,
           app.save.get_setting("sfx"))

    sc.index = 1
    before = bool(app.save.get_setting("show_debug"))
    sc._adjust(1)
    _check(u"调试项能翻转", bool(app.save.get_setting("show_debug")) != before)

    # 画一帧：音量条、开关、设备状态三处都不能抛
    try:
        sc.draw(app.screen)
        ok = True
        err = ""
    except Exception as exc:
        ok = False
        err = u"%s" % exc
    _check(u"设置界面能画出来", ok, err)

    sc.handle_event(_key(pygame.K_ESCAPE))
    _check(u"Esc 回主菜单", app.scenes._pending == "menu",
           app.scenes._pending)
    app.scenes._pending = None

    # 玩家事件：音效的输入源
    w = world.World.load(config.DEFAULT_LEVEL)
    p = player.Player(*w.spawn)
    inp = player.InputState()
    for _ in range(40):
        p.update(DT, inp, w.collision_solids())
    _check(u"静置时没有事件", not p.events, u"%s" % (p.events,))

    inp.jump_pressed = True
    inp.jump_held = True
    p.update(DT, inp, w.collision_solids())
    _check(u"起跳报 jump", "jump" in p.events, u"%s" % (p.events,))

    inp.jump_held = False
    inp.jump_released = True
    got_land = False
    for _ in range(120):
        p.update(DT, inp, w.collision_solids())
        if "land" in p.events:
            got_land = True
            break
    _check(u"落地报 land", got_land, u"%s" % (p.events,))

    inp.dash_pressed = True
    p.update(DT, inp, w.collision_solids())
    _check(u"冲刺报 dash", "dash" in p.events, u"%s" % (p.events,))
    # 一帧一次：事件不许跨帧累积，否则音效会每帧重放
    p.update(DT, inp, w.collision_solids())
    _check(u"事件不跨帧累积", "dash" not in p.events, u"%s" % (p.events,))


def test_m10_fx(app):
    _section(u"M10 粒子与震屏")

    ps = fx_mod.Particles()
    _check(u"空池不画也不崩", ps.count == 0 and ps.update(DT) is None)

    n = ps.burst("dust", 100, 200)
    _check(u"扬尘一次出一簇", n > 0 and ps.count == n, u"n=%d" % n)

    _check(u"未知粒子类型直接忽略",
           ps.burst("不存在的类型", 0, 0) == 0 and ps.count == n)

    ps.burst("debris", 0, 0, )
    for _ in range(40):
        ps.burst("spark", 0, 0)
    _check(u"总数不超过上限", ps.count <= fx_mod.MAX_PARTICLES,
           u"%d / %d（丢弃 %d）" % (ps.count, fx_mod.MAX_PARTICLES,
                                   ps.dropped))

    # 重力方向：碎块往下、火星往上。
    # 碎块刚炸开时是向上飞的（那是"被炸飞"，不是错误），所以不能拿位移
    # 判方向——要等重力把它翻过来，看末速度。
    d = fx_mod.Particles()
    d.burst("debris", 300, 300)
    for _ in range(14):
        d.update(DT)
    _check(u"碎块被重力拽下来",
           bool(d.items) and all(p[3] > 0.0 for p in d.items),
           u"vy=%s" % ([round(p[3]) for p in d.items[:3]],))

    e = fx_mod.Particles()
    e.burst("ember", 300, 300)
    ey0 = e.items[0][1]
    for _ in range(3):
        e.update(DT)
    _check(u"火星往上飘", all(p[1] < ey0 for p in e.items if p[4] > 0.1),
           u"y %.1f -> %.1f" % (ey0, e.items[0][1] if e.items else -1))

    # 寿命：跑够长一定清空（不留"永远不消失的粒子"）
    for _ in range(120):
        d.update(DT)
    _check(u"寿命到了会清空", d.count == 0, u"%d 个残留" % d.count)

    try:
        e.burst("spark", 100, 100)
        e.draw(app.screen, -50, -50)
        ok, err = True, ""
    except Exception as exc:
        ok, err = False, u"%s" % exc
    _check(u"粒子能画到屏幕上", ok, err)

    # 震屏：只动绘制偏移，不动相机位置
    cam = world.Camera((config.WIDTH, config.HEIGHT),
                       pygame.Rect(0, 0, 4000, 1200))
    cam.x, cam.y = 800.0, 400.0
    target = pygame.Rect(1000, 500, 26, 70)
    cam.update(DT, target)
    base = (-int(round(cam.x)), -int(round(cam.y)))
    cam.kick(9.0, 0.20)
    moved = False
    for _ in range(8):
        cam.update(DT, target)
        if cam.offset != base:
            moved = True
    _check(u"震屏让绘制偏移抖动", moved, u"offset=%s base=%s"
           % (cam.offset, base))
    _check(u"震屏不改变相机位置",
           abs(cam.x - (1000 + 13 - config.WIDTH * 0.5)) < 200.0,
           u"cam.x=%.1f" % cam.x)
    for _ in range(30):
        cam.update(DT, target)
    _check(u"震屏会自己停下", cam.shake_left == 0.0
           and cam.offset[0] == -int(round(cam.x)),
           u"offset=%s" % (cam.offset,))


# ---------------------------------------------------------------- 入口

def run(app):
    print("=" * 60)
    print(u" 火柴人跑酷 · 分阶段自检")
    print("=" * 60)

    # 自检故意让角色死几百次。事件日志是给试玩看的，这里关掉，否则
    # 几百行"死亡 N：…"会把真正的断言结果冲到看不见。
    #
    # **必须放在函数里，不能写在模块顶层**：main.py 在顶部就 import 了
    # selftest（为了 --selftest），模块级的副作用会连正常游戏一起关掉——
    # 试玩时一行死因都没打出来，查了半天才发现是这里。
    saved_log = config.LOG_EVENTS
    config.LOG_EVENTS = False
    # 自检会真的跑到终点（好几关），不能把成绩写进玩家自己的 save.json。
    # 换一份临时存档，跑完再换回来——和上面的事件日志是同一个道理：
    # 被调用的模块不许留下副作用。
    real_save = app.save
    tmp_dir = tempfile.mkdtemp(prefix="pyrun_selftest_")
    app.save = save_mod.Save(os.path.join(tmp_dir, "save.json"))
    # 自检会把同一个音效播几十次（设置界面试听、金币、死亡）。
    # 换一个禁用实例，跑完再换回来——理由和上面两条一样：被调用的模块
    # 不许给玩家留下可听可见的副作用。
    real_audio = app.audio
    app.audio = audio_mod.Audio(
        enabled=False, volume=real_audio.volume if real_audio else 0.7)
    try:
        return _run_all(app)
    finally:
        config.LOG_EVENTS = saved_log
        app.save = real_save
        app.audio = real_audio


def _run_all(app):
    test_scenes(app)
    test_sprites()
    test_anim_state()
    test_land_feel()
    test_dash()
    test_physics()
    test_oneway()
    test_bouncer()
    test_platform()
    test_platform_squeeze()
    test_m4_scene(app)
    test_glide()
    test_m5_scene(app)
    test_bat()
    test_rock_timing()
    test_dialog_layout()
    test_m6_parse()
    test_m6_errors()
    test_m6_scene(app)
    test_m6_playable(app)
    test_walker()
    test_rotor()
    test_pendulum()
    test_m7_parse()
    test_m7_scene(app)
    test_m7_checkpoint(app)
    test_m7_air_glider(app)
    test_m7_playable(app)
    test_m8_parse()
    test_m8_brick(app)
    test_m8_spike(app)
    test_m8_wall(app)
    test_m8_twin(app)
    test_m8_respawn(app)
    test_m8_playable(app)
    test_m9_save()
    test_m9_catalog()
    test_m9_menu(app)
    test_m9_select(app)
    test_m9_pause(app)
    test_m9_goal(app)
    test_m10_audio()
    test_m10_settings()
    test_m10_settings_scene(app)
    test_m10_fx(app)
    test_level_parse()
    test_level_errors()
    test_level_audit()
    test_camera()
    test_level_playable()

    fails = len([r for r in RESULTS if not r[0]])
    print("")
    print("-" * 60)
    if fails:
        print(u" 结果：%d 项失败 / 共 %d 项" % (fails, len(RESULTS)))
    else:
        print(u" 结果：全部通过，共 %d 项" % len(RESULTS))
    print("-" * 60)
    return 1 if fails else 0
