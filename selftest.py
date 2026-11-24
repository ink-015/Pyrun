# -*- coding: utf-8 -*-
"""分阶段自检。入口：python main.py --selftest

M1 场景部分需要真实 Display（要渲染一帧）；
M2 物理部分是纯逻辑，只操作 Player + Rect，不读键盘、不画图，
所以土狼时间、跳跃缓冲这类"靠帧数才测得准"的东西可以精确断言。

每条断言都对应 README §19 的某一项验收，不许靠手感。
"""

import os
import tempfile

import pygame

import assets
import config
import io_utils
import player
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


# ---------------------------------------------------------------- 入口

def run(app):
    print("=" * 60)
    print(u" 火柴人跑酷 · 分阶段自检")
    print("=" * 60)

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
    test_level_parse()
    test_level_errors()
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
