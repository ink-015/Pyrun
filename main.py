# -*- coding: utf-8 -*-
"""《火柴人跑酷》入口。

职责边界（README §18.9）：**窗口只在这里创建一次**。
场景只接收 surface，永远不调用 set_mode。

M1 内容：固定步长主循环 + 场景管理 + 菜单/游戏两个场景。
M2 内容：游戏场景接入玩家物理、灰盒地形与 F1 调试显示。
M2.5 内容：角色贴图动画（assets.py），素材缺失时退回代码绘制。
M3 内容：关卡文件（world.py + levels/l1.txt）、相机跟随、HUD 与终点结算。
命令行开关：
    python main.py                 正常启动，进主菜单
    python main.py --smoke         渲染一帧菜单并截图，用于环境验证
    python main.py --smoke-game    跳到第一关跑几步并截图
    python main.py --smoke-dash    抓一张冲刺中的画面（看残影与冷却条）
    python main.py --smoke-goal    跑到终点，截下结算面板
    python main.py --smoke-m4      在机关关 l2 截一张（篝火/地刺/单向平台/移动平台）
    python main.py --smoke-death   触发一次落水死亡，截下死亡定格画面
    python main.py --smoke-glide   第 3 关：先走过去捡伞，再抓一张滑翔中的画面
    python main.py --smoke-m6      第 4 关：NPC 对话 / 蝙蝠走廊 / 落石三张图
    python main.py --smoke-m7      第 5 关：踩怪 / 刺轮 / 荡锤 / 空中伞四张图
    python main.py --smoke-m8      第 6 关：伪装砖 / 落刺 / 突墙 / 二连石四张图
    python main.py --smoke-m9      界面四张图：主菜单 / 选关 / 暂停 / 结算
    python main.py --level l2      直接进入指定关卡（文件名不含 .txt）
    python main.py --smoke-assets  渲染 M0 素材验证画面并截图
    python main.py --smoke-anim    按游戏内比例摊开所有角色帧，核对锚点
    python main.py --smoke-run     连续截取跑动帧拼成一条，判断动作连贯性
                                   （可选第二参数 canvas / content 对比锚点）
    python main.py --selftest      运行分阶段自检（场景/贴图/动画/物理/关卡/相机）
    python main.py --bench 180 game   帧率基准，第二个参数可指定场景
    python main.py --fps           运行时在控制台打印实际帧率
"""

import math
import os
import sys
import time

import pygame

import assets
import compat
import config
import levels_catalog
import player
import save as save_mod
import scenes
import selftest


class App(object):
    """全局上下文。场景通过 self.app 拿到屏幕、时钟与切换入口。"""

    def __init__(self):
        self.screen = None
        self.clock = None
        self.scenes = None
        # 存档由 App 持有：场景只读它、只在通关时写它。
        # 不能让每个场景自己 new 一个——那样两个存档对象各自持有不同的
        # 内存副本，谁后写谁覆盖，进度会莫名其妙丢。
        self.save = None
        self.running = True

    def quit(self):
        self.running = False


# ---------------------------------------------------------------- 环境报告

def report_environment():
    """打印版本、根目录与自检结果。缺失项只警告，不阻止启动。"""
    print("=" * 56)
    print(" 火柴人跑酷 · 启动")
    print("=" * 56)
    print(" pygame :", pygame.version.ver)
    print(" python :", sys.version.split()[0])
    print(" 焦点   :", compat.focus_event_model())
    print(" 根目录 :", config.BASE_DIR)

    missing_dirs, missing_files = config.check_environment()
    for p in missing_dirs:
        print(" [缺失目录]", p)
    for p in missing_files:
        print(" [缺失文件]", p)
    if not missing_dirs and not missing_files:
        print(" 自检   : 通过（目录与关键素材齐全）")
    print("=" * 56)


# ---------------------------------------------------------------- M0 素材验证画面

def draw_asset_check_frame(screen, font_big, font_small, font_name):
    """M0 遗留的素材可读性验证画面，只在 --smoke-assets 时使用。

    M1 的正常路径完全不读素材，这个函数是独立的调试件。
    """
    screen.fill(config.COLOR_PAPER)

    for x in range(0, config.WIDTH, 64):
        pygame.draw.line(screen, config.COLOR_PAPER_LINE, (x, 0), (x, config.HEIGHT))
    for y in range(0, config.HEIGHT, 64):
        pygame.draw.line(screen, config.COLOR_PAPER_LINE, (0, y), (config.WIDTH, y))

    pts = [(x, 300 + int(18 * math.sin(x / 120.0))) for x in range(0, config.WIDTH + 1, 8)]
    pygame.draw.lines(screen, config.COLOR_HILL, False, pts, 3)

    ground_y = 440
    pygame.draw.rect(screen, config.COLOR_GROUND, (0, ground_y, config.WIDTH, config.HEIGHT - ground_y))
    top_line = [(x, ground_y + int(1.2 * math.sin(x / 17.0))) for x in range(-2, config.WIDTH + 4, 12)]
    pygame.draw.lines(screen, config.COLOR_INK, False, top_line, 3)
    for x in range(12, config.WIDTH, 64):
        pygame.draw.line(screen, (214, 210, 200), (x, ground_y + 10), (x + 4, config.HEIGHT), 1)

    tile_top = pygame.image.load(os.path.join(config.IMAGE_DIR, "tiles", "tile_top.png")).convert_alpha()
    tile_fill = pygame.image.load(os.path.join(config.IMAGE_DIR, "tiles", "tile.png")).convert_alpha()
    for i in range(3):
        screen.blit(tile_top, (660 + i * config.TILE, 312))
        screen.blit(tile_fill, (660 + i * config.TILE, 312 + config.TILE))

    hero = pygame.image.load(os.path.join(config.IMAGE_DIR, "hero", "standright.png")).convert_alpha()
    bbox = hero.get_bounding_rect()
    screen.blit(hero, (150 - bbox.x, ground_y - bbox.bottom))

    coin = pygame.image.load(os.path.join(config.IMAGE_DIR, "collectibles", "tile_coin.png")).convert_alpha()
    coin = pygame.transform.smoothscale(coin, (44, 44))
    coin = compat.tint(coin, config.COLOR_COIN)
    screen.blit(coin, (420, ground_y - 120))

    camp = pygame.image.load(os.path.join(config.IMAGE_DIR, "checkpoints", "campfire.png")).convert_alpha()
    camp = pygame.transform.smoothscale(camp, (72, 72))
    camp = compat.tint(camp, config.COLOR_CAMP)
    cb = camp.get_bounding_rect()
    screen.blit(camp, (540 - cb.x, ground_y - cb.bottom - 2))

    screen.blit(font_big.render("M0 环境检查通过", True, config.COLOR_INK), (40, 36))
    screen.blit(font_small.render("pygame %s  ·  960x540  ·  60 FPS" % pygame.version.ver,
                                  True, config.COLOR_MUTED), (42, 84))
    screen.blit(font_small.render("字体：%s   素材：assets/images" % font_name,
                                  True, config.COLOR_MUTED), (42, 110))


# ---------------------------------------------------------------- 截图

def save_screenshot(surface, name):
    """把当前画面存到 docs/，返回完整路径。"""
    os.makedirs(config.DOCS_DIR, exist_ok=True)
    out = os.path.join(config.DOCS_DIR, name)
    pygame.image.save(surface, out)
    return out


def run_smoke_anim(app):
    """把角色各动作按**游戏内真实比例**摊开画一遍，用于核对锚点。

    为什么必须单独做这一张：素材每帧在自己的画布内是有上下起伏的
    （跑动帧脚底距画布底边 0~18px，那是作者的弹跳节奏）。锚点选错时
    在动图上很难看出来，但摊在一条地面线上就一目了然——
    脚是贴着线跑，还是整个人在地上蹦。
    """
    screen = app.screen
    screen.fill(config.COLOR_PAPER)
    for x in range(0, config.WIDTH, 64):
        pygame.draw.line(screen, config.COLOR_PAPER_LINE, (x, 0), (x, config.HEIGHT))
    for y in range(0, config.HEIGHT, 64):
        pygame.draw.line(screen, config.COLOR_PAPER_LINE, (0, y), (config.WIDTH, y))

    try:
        hero = assets.load_hero()
    except assets.AssetMissing as exc:
        print(u" 角色贴图缺失：%s" % exc)
        return 1

    f, _ = scenes.get_font(14)

    def ground(y, note):
        pygame.draw.line(screen, config.COLOR_INK, (0, y), (config.WIDTH, y), 2)
        screen.blit(f.render(note, True, config.COLOR_MUTED), (8, y - 20))

    def put(img, cx, foot_y, action, facing, idx):
        # 走和游戏里完全相同的锚点计算，避免"检查图好看、进游戏却错位"
        x, y = hero.blit_pos(cx, foot_y, action, facing, idx)
        screen.blit(img, (x, y))

    # 上排：8 帧跑步，铺在同一水平线上
    g1 = 300
    ground(g1, u"run x8  (%d 帧)" % hero.frame_count("run", -1))
    run = hero.frames["run"][-1]
    for i, img in enumerate(run):
        cx = 70 + i * 112
        put(img, cx, g1, "run", -1, i)
        lb = f.render("run%d" % i, True, config.COLOR_MUTED)
        screen.blit(lb, (cx - lb.get_width() // 2, g1 + 4))

    # 左下：站立与跳跃两种朝向
    g2 = 500
    ground(g2, u"idle / jump")
    idle_l = hero.frame("idle", -1, 0)
    idle_r = hero.frame("idle", 1, 0)
    jump_l = hero.frame("jump", -1, 0)
    jump_r = hero.frame("jump", 1, 0)
    put(idle_l, 90, g2, "idle", -1, 0)
    put(idle_r, 220, g2, "idle", 1, 0)
    put(jump_l, 360, g2, "jump", -1, 0)
    put(jump_r, 490, g2, "jump", 1, 0)
    for cx, name in ((90, "idle L"), (220, "idle R"), (360, "jump L"), (490, "jump R")):
        lb = f.render(name, True, config.COLOR_MUTED)
        screen.blit(lb, (cx - lb.get_width() // 2, g2 + 4))

    # 右下：碰撞盒与贴图的对齐检查
    box = pygame.Rect(0, 0, player.Player.WIDTH, player.Player.HEIGHT)
    box.center = (760, g2 - player.Player.HEIGHT // 2)
    put(idle_l, 760, g2, "idle", -1, 0)
    pygame.draw.rect(screen, (200, 60, 60), box, 1)
    lb = f.render(u"26x70 hitbox", True, config.COLOR_MUTED)
    screen.blit(lb, (760 - lb.get_width() // 2, g2 + 4))

    out = save_screenshot(screen, "hero_ingame.png")
    print(u" 角色     : %s" % hero.describe())
    print(u" 截图     : %s" % out)
    return 0


def run_bench(app, frames):
    """限速跑 N 帧，报告实际帧率。

    因为每帧都调 clock.tick(FPS)，跑满说明渲染确实跟得上 60；
    如果渲染超预算，帧率会掉到 60 以下，这里能看出来。
    """
    clock = app.clock
    clock.tick(config.FPS)  # 先空转一帧，丢掉初始化抖动
    worst = 0.0
    total_ms = 0.0
    t0 = time.time()

    for _ in range(frames):
        ms = clock.tick(config.FPS)
        total_ms += ms
        if ms > worst:
            worst = ms
        app.scenes.update(config.FIXED_DT)
        app.scenes.draw(app.screen)
        pygame.display.flip()

    elapsed = time.time() - t0
    fps = frames / elapsed if elapsed > 0 else 0.0

    # 第二段：不限速，测纯渲染开销。
    # Windows 默认定时器精度约 15.6ms，clock.tick 的休眠会被向上取整，
    # 导致"限速 60"实测总在 17ms 左右——那是系统定时器的锅，不是渲染慢。
    # 只有不限速测出来的才是真实开销，M2 加物理后要盯这个数。
    t0 = time.time()
    for _ in range(frames):
        app.scenes.update(config.FIXED_DT)
        app.scenes.draw(app.screen)
        pygame.display.flip()
    free_elapsed = time.time() - t0
    free_ms = free_elapsed / frames * 1000.0
    free_fps = frames / free_elapsed if free_elapsed > 0 else 0.0
    budget = 1000.0 / config.FPS

    print("-" * 56)
    print(u" 帧率基准：%d 帧" % frames)
    print(u" 限速实测：%.2f FPS（%.2f ms/帧，最慢 %.2f ms）"
          % (fps, total_ms / frames, worst))
    print(u" 纯渲染  ：%.2f ms/帧（不限速上限 %.1f FPS）" % (free_ms, free_fps))
    print(u" 帧预算  ：%.2f ms" % budget)
    print(u" 驱动    ：%s" % pygame.display.get_driver())
    print("-" * 56)

    if free_ms >= budget:
        print(u" 结论：渲染已超预算，需要优化")
        return 1
    if fps >= config.FPS * 0.95:
        print(u" 结论：稳定 60 FPS，渲染余量 %.1f 倍" % (budget / max(free_ms, 0.01)))
        return 0
    print(u" 结论：渲染有余量，限速帧率偏低源于系统定时器精度（非代码问题）")
    return 0


# ---------------------------------------------------------------- 主流程

def _pick_level(argv):
    """解析 --level：可以给 l2、l2.txt 或完整路径，缺省用第一关。"""
    if "--level" not in argv:
        return config.DEFAULT_LEVEL
    i = argv.index("--level")
    if i + 1 >= len(argv):
        return config.DEFAULT_LEVEL
    name = argv[i + 1]
    if os.path.isabs(name) or os.sep in name:
        return name
    if not name.endswith(".txt"):
        name += ".txt"
    return os.path.join(config.LEVEL_DIR, name)


def main():
    pygame.init()
    pygame.display.set_caption(config.TITLE)
    screen = compat.make_display((config.WIDTH, config.HEIGHT))
    clock = pygame.time.Clock()

    report_environment()
    print(" 显示   : %dx%d / %d 位 / 驱动 %s"
          % (screen.get_width(), screen.get_height(), screen.get_bitsize(),
             pygame.display.get_driver()))

    font_big, font_name = scenes.get_font(34, bold=True)
    font_small, _ = scenes.get_font(18)
    print(" 字体   :", font_name)

    app = App()
    app.screen = screen
    app.clock = clock
    # 截图与自检会人为制造"通关"，一律只读，绝不写玩家的 save.json。
    readonly = any(a.startswith("--smoke") for a in sys.argv) or "--selftest" in sys.argv
    app.save = save_mod.Save(readonly=readonly)
    if app.save.warnings:
        for w in app.save.warnings:
            print(u" 存档     : %s" % w)
    print(u" 存档     : %s（%s）" % (app.save.path, app.save.summary()))
    app.scenes = scenes.SceneManager(app)
    app.scenes.register("menu", scenes.MenuScene)
    app.scenes.register("select", scenes.LevelSelectScene)
    app.scenes.register("game", scenes.GameScene)
    app.scenes.start("menu")

    # --level 先落到 app 上，游戏场景构造时会读它；不写就还是第一关
    app.level_path = _pick_level(sys.argv)

    # ---- 一次性渲染并截图的调试分支 ----
    if "--smoke-assets" in sys.argv:
        draw_asset_check_frame(screen, font_big, font_small, font_name)
        pygame.display.flip()
        out = os.path.join(config.DOCS_DIR, "m0_check.png")
        os.makedirs(config.DOCS_DIR, exist_ok=True)
        pygame.image.save(screen, out)
        print(" 截图   :", out)
        pygame.quit()
        return 0

    if "--smoke" in sys.argv:
        app.scenes.draw(screen)
        pygame.display.flip()
        print(" 截图   :", save_screenshot(screen, "m1_menu.png"))
        pygame.quit()
        return 0

    if "--smoke-dash" in sys.argv:
        # 冲刺过程截图：跑到有速度，然后起手冲刺，抓冲刺中的一帧
        app.scenes.start("game")
        scene = app.scenes.current
        for _ in range(20):
            app.scenes.update(config.FIXED_DT)
        scene.override_axis = 1.0
        for _ in range(40):
            app.scenes.update(config.FIXED_DT)
        scene.input.dash_pressed = True
        for _ in range(3):
            app.scenes.update(config.FIXED_DT)
        p = scene.player
        print(u" 冲刺中   : dashing=%s  vx=%.1f  dash_time=%.3f"
              % (p.dashing, p.vx, p.dash_time))
        app.scenes.draw(screen)
        pygame.display.flip()
        print(" 截图   :", save_screenshot(screen, "m26_dash.png"))
        pygame.quit()
        return 0

    if "--smoke-game" in sys.argv:
        # 跳到游戏场景：先落稳，再按住右跑到第一处台阶前，
        # 让画面里同时出现地面、台阶、金币和相机已经跟随的证据
        app.scenes.start("game")
        scene = app.scenes.current
        for _ in range(20):
            app.scenes.update(config.FIXED_DT)
        scene.override_axis = 1.0
        for _ in range(96):
            app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 动画状态 : %s #%d" % (scene.player.anim_state, scene.player.anim_frame))
        print(u" 相机     : x=%.1f  offset=%s"
              % (scene.camera.x, scene.camera.offset))
        print(" 截图   :", save_screenshot(screen, "m3_game.png"))
        pygame.quit()
        return 0

    if "--smoke-goal" in sys.argv:
        # 直接跑到终点并截下结算面板，作为「终点可达」的视觉证据
        app.scenes.start("game")
        scene = app.scenes.current
        w = scene.world
        scene.player.x = w.goal_rect.centerx - 120
        scene.player.y = w.goal_rect.bottom - scene.player.HEIGHT
        scene.camera.snap_to(scene.player.rect)
        scene.override_axis = 1.0
        for _ in range(40):
            app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 终点     : reached=%s  用时 %.1fs  金币 %d/%d"
              % (scene.goal_reached, scene.level_time,
                 w.taken_coins, w.total_coins))
        print(" 截图   :", save_screenshot(screen, "m3_goal.png"))
        pygame.quit()
        return 0

    if "--smoke-m4" in sys.argv:
        # 机关关：直接把玩家放到移动平台上，让一屏里同时出现
        # 水坑 + 平台 + 篝火 + 升降台 + 藏币台，用来核对机关画得对不对
        app.level_path = os.path.join(config.LEVEL_DIR, "l2.txt")
        app.scenes.start("game")
        scene = app.scenes.current
        plat = [p for p in scene.world.platforms if p.axis == "x"][0]
        scene.player.teleport(plat.rect.centerx - player.Player.WIDTH // 2,
                              plat.rect.top - player.Player.HEIGHT)
        for _ in range(40):
            app.scenes.update(config.FIXED_DT)
        print(u" 平台     : %s  offset=%.0f" % (plat.rect, plat.offset))
        print(u" 玩家     : x=%.0f 脚底=%.0f（平台顶 %d）"
              % (scene.player.x, scene.player.rect.bottom, plat.rect.top))
        app.scenes.draw(screen)
        pygame.display.flip()
        print(" 截图   :", save_screenshot(screen, "m4_level2.png"))
        pygame.quit()
        return 0

    if "--smoke-death" in sys.argv:
        # 死亡定格画面。用第一次水坑，最直观
        app.level_path = os.path.join(config.LEVEL_DIR, "l2.txt")
        app.scenes.start("game")
        scene = app.scenes.current
        water = scene.world.hazard_boxes[1][0]
        scene.player.teleport(water.centerx, water.top)
        for _ in range(2):
            app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 死亡     : %d 次，原因「%s」，定格 %.2fs"
              % (scene.deaths, scene.last_death_cause, scene.death_timer))
        print(" 截图   :", save_screenshot(screen, "m4_death.png"))
        pygame.quit()
        return 0

    if "--smoke-glide" in sys.argv:
        # M5 滑翔伞：先真的走过去捡伞（顺带截下提示条与 HUD），
        # 再从起跳台跑出去按住空格，抓一张飘在水坑上方的画面
        app.level_path = os.path.join(config.LEVEL_DIR, "l3.txt")
        app.scenes.start("game")
        scene = app.scenes.current
        p = scene.player
        scene.show_debug = False        # 截图要看的是玩家看到的样子，不是调试面板

        scene.override_axis = 1.0
        for _ in range(26):
            app.scenes.update(config.FIXED_DT)
        scene.override_axis = None
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 拾取     : 伞=%s  x=%.0f  提示「%s」"
              % (p.has_glider, p.x, scene.toast_text))
        print(" 截图   :", save_screenshot(screen, "m5_item.png"))

        p.teleport(19 * config.TILE, 6 * config.TILE - p.HEIGHT)
        scene.camera.snap_to(p.rect)
        scene.override_axis = 1.0
        scene.input.jump_held = True      # 只按住，不按边沿：走出去自然进入滑翔
        # 100 帧：此时正好飘到水坑中段，水面也在视野里，看得出"下面是死路"
        for _ in range(100):
            app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 滑翔     : %s  vy=%.0f  vx=%.0f  x=%.0f（水坑 21~28 列）"
              % (p.gliding, p.vy, p.vx, p.x))
        print(" 截图   :", save_screenshot(screen, "m5_glide.png"))
        pygame.quit()
        return 0

    if "--smoke-m6" in sys.argv:
        # M6：一次跑三个画面——NPC 对话、蝙蝠走廊、落石预警/下落
        app.level_path = os.path.join(config.LEVEL_DIR, "l4.txt")
        app.scenes.start("game")
        scene = app.scenes.current
        p = scene.player
        scene.show_debug = False
        W = player.Player.WIDTH
        H = player.Player.HEIGHT

        # 1) 站在老人旁边（偏右 46px，别和 NPC 叠在一起）按 E
        npc = scene.world.npcs[0]
        p.teleport(npc["cell"].centerx - W // 2 + 46, npc["cell"].bottom - H)
        scene.camera.snap_to(p.rect)
        for _ in range(6):
            app.scenes.update(config.FIXED_DT)
        print(u" 交互目标 : %s（%s）"
              % (scene.world.focus["name"] if scene.world.focus else u"无",
                 scene.world.focus["kind"] if scene.world.focus else "-"))
        scene._try_interact()
        for _ in range(30):
            app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 对话     : 第 %d/%d 页「%s」  暂停中=%s"
              % (scene.dialog.index + 1, len(scene.dialog.pages),
                 scene.dialog.page()[:16], scene.dialog is not None))
        print(" 截图   :", save_screenshot(screen, "m6_dialog.png"))

        # 2) 蝙蝠走廊
        scene.dialog = None
        p.teleport(18 * config.TILE, 9 * config.TILE - H)
        scene.camera.snap_to(p.rect)
        for _ in range(40):
            app.scenes.update(config.FIXED_DT)
        b = scene.world.bats[0]
        print(u" 蝙蝠     : x=%.0f（区间 %.0f~%.0f）y=%.0f  帧=%d"
              % (b.cx, b.left, b.right, b.cy, len(b.frames)))
        app.scenes.draw(screen)
        pygame.display.flip()
        print(" 截图   :", save_screenshot(screen, "m6_bat.png"))

        # 3) 落石：一直跑到有石头真的在往下掉
        p.teleport(37 * config.TILE + 8, 11 * config.TILE - H)
        scene.camera.snap_to(p.rect)
        scene.invuln = 99.0             # 截图用：别被砸死，不然拍到的是死亡面板
        falling = None
        for _ in range(300):
            app.scenes.update(config.FIXED_DT)
            for r in scene.world.rocks:
                if r.state == "fall":
                    falling = r
                    break
            if falling is not None:
                break
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 落石     : 场上 %d 块，状态 %s，已投下 %d 块"
              % (len(scene.world.rocks),
                 falling.state if falling else u"无", scene.world.rock_count))
        print(" 截图   :", save_screenshot(screen, "m6_rock.png"))
        pygame.quit()
        return 0

    if "--smoke-m7" in sys.argv:
        # M7：四张图——踩怪、刺轮、荡锤、半空中的伞
        app.level_path = os.path.join(config.LEVEL_DIR, "l5.txt")
        app.scenes.start("game")
        scene = app.scenes.current
        p = scene.player
        scene.show_debug = False
        W = player.Player.WIDTH
        H = player.Player.HEIGHT

        # 1) 踩怪：从走地怪头顶正上方掉下去，抓"闪烁消失"的那一帧。
        #    这里刻意不开无敌——踩中判定只在 invuln<=0 时才会走。
        wk = scene.world.walkers[0]
        p.teleport(wk.cx - W * 0.5, wk.ground_y - 3 - 26 - H - 46)
        scene.camera.snap_to(p.rect)
        for _ in range(2):
            app.scenes.update(config.FIXED_DT)
        scene.override_axis = 0.0
        for _ in range(12):
            app.scenes.update(config.FIXED_DT)
            if p.stomp_count:
                break
        # 停在"还看得见"的那一闪上：闪烁是按 die_t 取模的，早两帧晚两帧
        # 就拍到空了，所以循环到可见帧为止再画。
        for _ in range(10):
            if int(wk.die_t * config.WALKER_DIE_FLICKER) % 2 == 1:
                break
            app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 踩怪     : 踩中 %d 次，走地怪状态 %s，vy=%.0f（应为负）"
              % (p.stomp_count, wk.state, p.vy))
        print(" 截图   :", save_screenshot(screen, "m7_stomp.png"))

        # 2) 刺轮 + 走地怪：这一张要同时拍到"头顶在转的刀片"和"刀片正下方
        #    巡逻的黑团子"——它俩是一套机关：刀片禁跳，黑团子堵路，逼你先把
        #    怪清掉再贴地跑过去。等角度而不是直接设，会拍到闪到空的那一帧，
        #    所以这里跑几帧后把角度定死再画。
        scene.override_axis = 0.0
        rot = scene.world.rotors[0]
        mate = scene.world.walkers[1] if len(scene.world.walkers) > 1 else None
        p.teleport(rot.cx - 150 - W * 0.5, 704 - H)
        scene.invuln = 0.0
        scene.camera.snap_to(p.rect)
        scene.toast_text = ""          # 把上一张"踩掉了走地怪"的横幅清掉
        scene.toast_timer = 0.0
        if mate is not None:
            mate.cx = rot.cx + 6
            mate.dir = 1
        for _ in range(20):
            app.scenes.update(config.FIXED_DT)
        rot.angle = math.pi / 2
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 刺轮     : 臂长 %.0f，周期 %.2fs；刀片下方巡逻的黑团子 x=%.0f"
              % (config.ROTOR_ARM_LEN, 2 * math.pi / config.ROTOR_SPEED,
                 mate.cx if mate is not None else -1))
        print(" 截图   :", save_screenshot(screen, "m7_rotor.png"))

        # 3) 荡锤：站在摆幅外侧（锤子扫不到的位置），画面里同时有梁、链、球
        ham = scene.world.hammers[0]
        p.teleport(ham.px + config.PENDULUM_ARM + 24, 704 - H)
        scene.camera.snap_to(p.rect)
        for _ in range(40):
            app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        bx, by = ham.bob()
        print(u" 荡锤     : 吊点 (%.0f, %.0f)，锤心 (%.0f, %.0f)，摆角 %.0f°"
              % (ham.px, ham.py, bx, by, math.degrees(ham.angle)))
        print(" 截图   :", save_screenshot(screen, "m7_hammer.png"))

        # 4) 半空中的伞：伞挂在"跳满"的那个高度上，金币一路引到伞边。
        #    这一张要停在**碰到伞之前**——捡起来之后伞就没了，画面里只剩人
        #    在空中，看不出"伞在这个高度"这件事。
        scene.invuln = 0.0
        p.teleport(56 * config.TILE - W, 9 * config.TILE - H)
        p.has_glider = False
        for it in scene.world.gliders:
            it["taken"] = False
        scene.camera.snap_to(p.rect)
        scene.override_axis = 1.0
        scene.input.jump_held = True
        scene.input.jump_pressed = True
        for _ in range(15):
            app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 空中道具 : 起跳弧顶点附近 y=%.0f（站立时 %d，伞底边 %d）"
              % (p.y, 9 * config.TILE - H,
                 scene.world.gliders[0]["rect"].bottom))
        print(" 截图   :", save_screenshot(screen, "m7_glider.png"))

        # 接着跑完这一段，确认伞拿得到、也滑得过去
        for _ in range(40):
            app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 滑翔     : 伞=%s 滑翔中=%s x=%.0f（水坑 57~61 列）vy=%.0f"
              % (p.has_glider, p.gliding, p.x, p.vy))
        print(" 截图   :", save_screenshot(screen, "m7_glide.png"))
        pygame.quit()
        return 0

    if "--smoke-m8" in sys.argv:
        # M8：四张图——伪装砖、落刺、突墙、二连石。
        # 每一张都要拍到"线索"本身：薄板下面的坑、扎下来的刺、挡路的墙、
        # 两块还没落地的影子。这四种机关的全部信息都在画面上，拍不出来
        # 就说明设计没落实。
        app.level_path = os.path.join(config.LEVEL_DIR, "l6.txt")
        app.scenes.start("game")
        scene = app.scenes.current
        p = scene.player
        scene.show_debug = False
        W = player.Player.WIDTH
        H = player.Player.HEIGHT
        floor = 11 * config.TILE

        # 1) 伪装砖：站在砖上等它裂开，画面里同时有薄板、裂缝和下面的刺。
        #    这里必须留在砖上——跑过去的话拍到的是"平坦地面"，看不出机关。
        w = scene.world
        scene.override_axis = 0.0
        p.teleport(9 * config.TILE + 18, floor - H)
        scene.camera.snap_to(p.rect)
        scene.invuln = 99.0
        for _ in range(14):
            app.scenes.update(config.FIXED_DT)
        # 跑过整排时，四块砖的裂纹深浅是不一样的——把那个瞬间摆出来：
        # 只让脚下一块裂的话，角色正好把裂纹挡住，图上什么都看不到。
        for i, b in enumerate(w.bricks[:4]):
            b.state = "crack"
            b.timer = config.BRICK_CRACK_TIME * (0.95 - 0.22 * i)
        scene.invuln = 0.0          # 无敌闪烁会把角色画没，截图前清掉
        scene.world.draw(screen, scene.camera, show_prompt=False)
        scene._draw_player(screen)
        scene._draw_hud(screen)
        pygame.display.flip()
        print(u" 伪装砖   : %s（踩上 %.2f 秒后塌）"
              % ([b.state for b in w.bricks[:4]], config.BRICK_CRACK_TIME))
        print(" 截图   :", save_screenshot(screen, "m8_brick.png"))

        # 2) 落刺：停在触发圈里不动，等它扎到一半
        w = scene.world
        sp = w.drop_spikes[0]
        p.teleport(sp.cx - W * 0.5, floor - H)
        scene.camera.snap_to(p.rect)
        scene.invuln = 99.0
        for _ in range(60):
            app.scenes.update(config.FIXED_DT)
            if sp.state == "hold" or (sp.state == "fall" and sp.tip > 660):
                break
        scene.invuln = 0.0
        scene.world.draw(screen, scene.camera, show_prompt=False)
        scene._draw_player(screen)
        scene._draw_hud(screen)
        pygame.display.flip()
        print(u" 落刺     : 状态 %s，刺尖 y=%.0f（地面 %.0f）"
              % (sp.state, sp.tip, sp.ground_y))
        print(" 截图   :", save_screenshot(screen, "m8_spike.png"))

        # 3) 突墙：让它升到顶，人正好被挡在左边
        w = scene.world
        wl = w.risers[0]
        w.reset_traps()
        p.teleport(wl.cx - 150, floor - H)
        scene.camera.snap_to(p.rect)
        scene.invuln = 99.0
        scene.override_axis = 1.0
        for _ in range(90):
            app.scenes.update(config.FIXED_DT)
            if wl.h >= config.WALL_H:
                break
        scene.invuln = 0.0
        scene.world.draw(screen, scene.camera, show_prompt=False)
        scene._draw_player(screen)
        scene._draw_hud(screen)
        pygame.display.flip()
        print(u" 突墙     : 高 %.0f（跳高 127），玩家右沿 %.0f / 墙左沿 %.0f"
              % (wl.h, p.rect.right, wl.cx - config.WALL_THICK * 0.5))
        print(" 截图   :", save_screenshot(screen, "m8_wall.png"))

        # 4) 二连石：两块都在预警期，地上两道影子一大一小
        w = scene.world
        w.reset_traps()
        tw = w.twins[0]
        p.teleport(tw.cx - 140, floor - H)
        scene.camera.snap_to(p.rect)
        scene.invuln = 99.0
        scene.override_axis = 0.0
        for _ in range(40):
            app.scenes.update(config.FIXED_DT)
            if len(w.rocks) == 2:
                break
        for _ in range(18):          # 再走几帧，让两块影子都收拢一点
            app.scenes.update(config.FIXED_DT)
        scene.invuln = 0.0
        scene.world.draw(screen, scene.camera, show_prompt=False)
        scene._draw_player(screen)
        scene._draw_hud(screen)
        pygame.display.flip()
        print(u" 二连石   : %d 块，预警 近 %.2fs / 远 %.2fs，落点 %.0f / %.0f"
              % (len(w.rocks),
                 w.rocks[0].warn_total if w.rocks else 0,
                 w.rocks[1].warn_total if len(w.rocks) > 1 else 0,
                 tw.cx, tw.cx + tw.gap))
        print(" 截图   :", save_screenshot(screen, "m8_twin.png"))

        pygame.quit()
        return 0

    if "--smoke-m9" in sys.argv:
        # M9 的四张界面图：主菜单 / 选关 / 暂停 / 结算。
        # 存档在 main 开头就按 --smoke* 判定为只读，这里注入的进度只活在
        # 内存里，不会把假成绩写进 save.json。
        sv = app.save
        sv.levels = {}
        sv.record("l1", 37.0, 10, 12, 2)
        sv.record("l2", 42.5, 11, 11, 0)

        app.scenes.start("menu")
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 菜单     : %s" % [l for l, _ in app.scenes.current.items])
        print(" 截图   :", save_screenshot(screen, "m9_menu.png"))

        app.scenes.goto("select")
        app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 选关     : 光标停在第 %d 张（第一个未通关的）"
              % (app.scenes.current.index + 1))
        print(" 截图   :", save_screenshot(screen, "m9_select.png"))

        # 暂停：挑第 3 关，画面里有滑翔伞和水池，一眼能看出"世界停住了"
        app.level_path = levels_catalog.path_of("l3")
        app.scenes.goto("game")
        app.scenes.update(config.FIXED_DT)
        scene = app.scenes.current
        for _ in range(12):
            app.scenes.update(config.FIXED_DT)
        scene.paused = True
        scene.pause_index = 1
        scene.invuln = 0.0
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 暂停     : paused=%s" % scene.paused)
        print(" 截图   :", save_screenshot(screen, "m9_pause.png"))

        # 结算：直接传进终点，走一遍真实的判定与存档（只读）
        scene.paused = False
        g = scene.world.goal_zone
        scene.player.teleport(g.centerx - scene.player.WIDTH // 2,
                              g.centery - scene.player.HEIGHT // 2)
        scene._post_physics()
        scene.invuln = 0.0
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 结算     : goal=%s next=%s rec=%s"
              % (scene.goal_reached, scene.next_key, scene.new_record))
        print(" 截图   :", save_screenshot(screen, "m9_goal.png"))
        pygame.quit()
        return 0

    if "--smoke-run" in sys.argv:
        # 连续截取跑动中的角色，拼成一条，用于肉眼判断动作是否连贯。
        # 这里刻意用纯平地面而不是 GameScene 的灰盒地形：
        # 灰盒地形在 x=170 就有平台侧面会挡住角色，跑到一半会停下来，
        # 看不出整轮跑步循环。
        # 用 --smoke-run content 可以生成另一种锚点的对照图。
        anchor = "canvas"
        i = sys.argv.index("--smoke-run")
        if i + 1 < len(sys.argv) and sys.argv[i + 1] in ("canvas", "content"):
            anchor = sys.argv[i + 1]
        hero = assets.load_hero(anchor=anchor)
        solids = [pygame.Rect(-4000, 460, 8000, 80)]
        p = player.Player(0, 460 - player.Player.HEIGHT)
        inp = player.InputState()
        inp.axis = 1.0
        for _ in range(6):                  # 先落稳并加速到跑速
            p.update(config.FIXED_DT, inp, solids)

        gw, gh = 96, 112
        frames = 10
        strip = pygame.Surface((gw * frames, gh))
        strip.fill(config.COLOR_PAPER)
        count = 1
        for i in range(frames):
            for _ in range(3):              # 每 3 帧取一格，一轮约 25 帧
                p.update(config.FIXED_DT, inp, solids)
            cell = pygame.Surface((gw, gh))
            cell.fill(config.COLOR_PAPER)
            pygame.draw.line(cell, config.COLOR_INK, (0, gh - 12), (gw, gh - 12), 2)
            count = hero.frame_count(p.anim_state, p.facing)
            idx = p.anim_frame % count
            img = hero.frame(p.anim_state, p.facing, idx)
            x, y = hero.blit_pos(gw // 2, gh - 12, p.anim_state, p.facing, idx)
            cell.blit(img, (x, y))
            strip.blit(cell, (i * gw, 0))
            pygame.draw.line(strip, (230, 226, 216), (i * gw, 0), (i * gw, gh), 1)

        f, _ = scenes.get_font(13)
        strip2 = pygame.Surface((gw * frames, gh + 20))
        strip2.fill(config.COLOR_PAPER)
        strip2.blit(strip, (0, 0))
        strip2.blit(f.render(u"anchor=%s, %d frames, every 3 ticks" % (anchor, count),
                             True, config.COLOR_MUTED), (6, gh + 2))
        name = "hero_run_strip.png" if anchor == "canvas" else "hero_run_strip_content.png"
        out = save_screenshot(strip2, name)
        print(u" 动画状态 : %s 帧数 %d 锚点 %s" % (p.anim_state, count, anchor))
        print(" 截图   :", out)
        pygame.quit()
        return 0

    if "--selftest" in sys.argv:
        code = selftest.run(app)
        pygame.quit()
        return code

    if "--smoke-anim" in sys.argv:
        code = run_smoke_anim(app)
        pygame.quit()
        return code

    if "--bench" in sys.argv:
        i = sys.argv.index("--bench")
        frames = 180
        scene = "menu"
        if i + 1 < len(sys.argv):
            try:
                frames = max(1, int(sys.argv[i + 1]))
            except ValueError:
                pass
        if i + 2 < len(sys.argv):
            scene = sys.argv[i + 2]
        if scene != "menu":
            app.scenes.start(scene)
        code = run_bench(app, frames)
        pygame.quit()
        return code

    # ---- 固定步长主循环 ----
    # --level 指定关卡时直接进关，跳过菜单。给试玩和截图脚本用的快速通道，
    # 顺带绕过"解锁"——否则想看一眼第 6 关，得先把前五关打通。
    if "--level" in sys.argv:
        app.scenes.start("game")

    show_fps = "--fps" in sys.argv
    fps_timer = 0.0
    accumulator = 0.0

    while app.running:
        frame_ms = clock.tick(config.FPS)
        app.scenes.handle_events(pygame.event.get())
        if not app.running:
            break

        # 逻辑固定 1/60 秒一步，渲染帧率可波动；卡顿后最多追 5 步，不雪崩
        accumulator += frame_ms / 1000.0
        if accumulator > 0.25:
            accumulator = 0.25
        steps = 0
        while accumulator >= config.FIXED_DT and steps < 5:
            app.scenes.update(config.FIXED_DT)
            accumulator -= config.FIXED_DT
            steps += 1

        app.scenes.draw(screen)
        pygame.display.flip()

        if show_fps:
            fps_timer += frame_ms / 1000.0
            if fps_timer >= 2.0:
                print(" FPS    : %.1f  (场景 %s)"
                      % (clock.get_fps(), app.scenes.current_name))
                fps_timer = 0.0

    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
