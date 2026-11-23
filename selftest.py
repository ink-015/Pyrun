# -*- coding: utf-8 -*-
"""分阶段自检。入口：python main.py --selftest

M1 场景部分需要真实 Display（要渲染一帧）；
M2 物理部分是纯逻辑，只操作 Player + Rect，不读键盘、不画图，
所以土狼时间、跳跃缓冲这类"靠帧数才测得准"的东西可以精确断言。

每条断言都对应 README §19 的某一项验收，不许靠手感。
"""

import pygame

import assets
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


# ---------------------------------------------------------------- 入口

def run(app):
    print("=" * 60)
    print(u" 火柴人跑酷 · 分阶段自检")
    print("=" * 60)

    test_scenes(app)
    test_sprites()
    test_anim_state()
    test_land_feel()
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
