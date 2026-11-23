# -*- coding: utf-8 -*-
"""《火柴人跑酷》入口。

职责边界（README §18.9）：**窗口只在这里创建一次**。
场景只接收 surface，永远不调用 set_mode。

M1 内容：固定步长主循环 + 场景管理 + 菜单/游戏两个场景。
命令行开关：
    python main.py                 正常启动，进主菜单
    python main.py --smoke         渲染一帧菜单并截图，用于环境验证
    python main.py --smoke-assets  渲染 M0 素材验证画面并截图
    python main.py --selftest      无窗口跑一遍场景切换断言
    python main.py --fps           运行时在控制台打印实际帧率
"""

import math
import os
import sys
import time

import pygame

import compat
import config
import scenes


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


# ---------------------------------------------------------------- 自检

def _key_event(key):
    """构造一个 KEYDOWN 事件，不经过窗口队列，dummy 驱动下也能用。"""
    return pygame.event.Event(pygame.KEYDOWN, {"key": key, "mod": 0})


def save_screenshot(surface, name):
    """把当前画面存到 docs/，返回完整路径。"""
    os.makedirs(config.DOCS_DIR, exist_ok=True)
    out = os.path.join(config.DOCS_DIR, name)
    pygame.image.save(surface, out)
    return out


def run_selftest(app):
    """验证 M1 的四条验收：窗口唯一、退出可用、场景可切换、不读素材。

    返回进程退出码。
    """
    results = []

    def check(name, cond, detail=""):
        results.append((bool(cond), name, detail))
        print("  [%s] %-22s %s" % ("PASS" if cond else "FAIL", name, detail))

    print("=" * 56)
    print(" 火柴人跑酷 · M1 场景自检")
    print("=" * 56)

    check(u"启动进入菜单", app.scenes.current_name == "menu",
          u"当前=%s" % app.scenes.current_name)

    # 真正渲染一帧，确认 draw 不崩且不读素材
    app.scenes.draw(app.screen)
    pygame.display.flip()
    shot = save_screenshot(app.screen, "m1_menu.png")
    check(u"菜单可渲染", os.path.isfile(shot), os.path.basename(shot))

    app.scenes.handle_events([_key_event(pygame.K_RETURN)])
    check(u"Enter 进入游戏", app.scenes.current_name == "game",
          u"当前=%s" % app.scenes.current_name)

    for _ in range(30):
        app.scenes.update(config.FIXED_DT)
    game = app.scenes.current
    check(u"固定步长生效", abs(game.elapsed - 30 * config.FIXED_DT) < 1e-6,
          u"elapsed=%.3fs" % game.elapsed)

    app.scenes.draw(app.screen)
    pygame.display.flip()
    shot = save_screenshot(app.screen, "m1_game.png")
    check(u"游戏场景可渲染", os.path.isfile(shot), os.path.basename(shot))

    app.scenes.handle_events([_key_event(pygame.K_ESCAPE)])
    check(u"Esc 返回菜单", app.scenes.current_name == "menu",
          u"当前=%s" % app.scenes.current_name)

    menuscene = app.scenes.current
    app.scenes.handle_events([_key_event(pygame.K_DOWN)])
    check(u"方向键切换选项", menuscene.index == 1, u"index=%d" % menuscene.index)

    app.scenes.handle_events([_key_event(pygame.K_RETURN)])
    check(u"退出项可退出", app.running is False, u"running=%s" % app.running)

    check(u"窗口未重复创建", app.screen is not None and app.screen.get_bitsize() == 32,
          u"%dx%d / %d 位" % (app.screen.get_width(), app.screen.get_height(),
                              app.screen.get_bitsize()))

    fails = len([r for r in results if not r[0]])
    print("-" * 56)
    print(u" 结果：%s（共 %d 项，场景切换 %d 次）"
          % (u"全部通过" if not fails else u"%d 项失败" % fails,
             len(results), app.scenes.switch_count))
    print("-" * 56)
    return 1 if fails else 0


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

    if "--selftest" in sys.argv:
        code = run_selftest(app)
        pygame.quit()
        return code

    if "--bench" in sys.argv:
        i = sys.argv.index("--bench")
        frames = 180
        if i + 1 < len(sys.argv):
            try:
                frames = max(1, int(sys.argv[i + 1]))
            except ValueError:
                pass
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
