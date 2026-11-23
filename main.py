# -*- coding: utf-8 -*-
"""《火柴人跑酷》入口。

职责边界（README §18.9）：**窗口只在这里创建一次**。
场景只接收 surface，永远不调用 set_mode。

M1 内容：固定步长主循环 + 场景管理 + 菜单/游戏两个场景。
M2 内容：游戏场景接入玩家物理、灰盒地形与 F1 调试显示。
M2.5 内容：角色贴图动画（assets.py），素材缺失时退回代码绘制。
命令行开关：
    python main.py                 正常启动，进主菜单
    python main.py --smoke         渲染一帧菜单并截图，用于环境验证
    python main.py --smoke-game    跳到游戏场景跑几步并截图
    python main.py --smoke-assets  渲染 M0 素材验证画面并截图
    python main.py --smoke-anim    按游戏内比例摊开所有角色帧，核对锚点
    python main.py --smoke-run     连续截取跑动帧拼成一条，判断动作连贯性
                                   （可选第二参数 canvas / content 对比锚点）
    python main.py --selftest      运行分阶段自检（场景 + 贴图 + 动画 + 物理）
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
import player
import scenes
import selftest


class App(object):
    """全局上下文。场景通过 self.app 拿到屏幕、时钟与切换入口。"""

    def __init__(self):
        self.screen = None
        self.clock = None
        self.scenes = None
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
    app.scenes = scenes.SceneManager(app)
    app.scenes.register("menu", scenes.MenuScene)
    app.scenes.register("game", scenes.GameScene)
    app.scenes.start("menu")

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

    if "--smoke-game" in sys.argv:
        # 跳到游戏场景：先落稳，再按住左跑一小段（左侧无遮挡），
        # 确保画面里是跑动帧而不是站立帧
        app.scenes.start("game")
        scene = app.scenes.current
        for _ in range(20):
            app.scenes.update(config.FIXED_DT)
        scene.override_axis = -1.0
        for _ in range(14):
            app.scenes.update(config.FIXED_DT)
        app.scenes.draw(screen)
        pygame.display.flip()
        print(u" 动画状态 : %s #%d" % (scene.player.anim_state, scene.player.anim_frame))
        print(" 截图   :", save_screenshot(screen, "m2_game.png"))
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
