# -*- coding: utf-8 -*-
"""《火柴人跑酷》入口。

M0 阶段只负责：
  1. 初始化 pygame 与控制台信息输出
  2. 启动自检（目录、关键素材）
  3. 打开 960x540 窗口并稳定运行
  4. 把一张纸底 + 真实素材的画面画出来，用于确认素材可读

玩法逻辑从 M1 起逐步接入，窗口与主循环只能在这里创建一次（README §18.9）。
"""

import math
import os
import sys

import pygame

import compat
import config


def load_font(size, bold=False):
    """按文件路径探测中文字体，全部失败则退回 pygame 默认字体。

    不使用 pygame.font.match_font / SysFont：它在部分 Windows 上枚举注册表
    字体会抛 TypeError，导致游戏起不来。
    """
    for folder in config.FONT_DIRS:
        for name in config.FONT_CANDIDATES:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                try:
                    font = pygame.font.Font(path, size)
                    font.set_bold(bold)
                    return font, name
                except Exception:
                    continue
    font = pygame.font.Font(None, size)
    font.set_bold(bold)
    return font, "default"


def report_environment():
    """打印版本、根目录与自检结果。缺失项只警告，不阻止启动。"""
    print("=" * 56)
    print(" 火柴人跑酷 · M0 环境检查")
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


def draw_static_frame(screen, font_big, font_small, font_name):
    """M0 验证画面：纸底 + 地面 + 主角 + 金币 + 篝火。不参与后续玩法。"""
    screen.fill(config.COLOR_PAPER)

    # 极淡方格纸（README §23.5 允许少量淡格）
    for x in range(0, config.WIDTH, 64):
        pygame.draw.line(screen, config.COLOR_PAPER_LINE, (x, 0), (x, config.HEIGHT))
    for y in range(0, config.HEIGHT, 64):
        pygame.draw.line(screen, config.COLOR_PAPER_LINE, (0, y), (config.WIDTH, y))

    # 远山：一条铅笔线
    pts = [(x, 300 + int(18 * math.sin(x / 120.0))) for x in range(0, config.WIDTH + 1, 8)]
    pygame.draw.lines(screen, config.COLOR_HILL, False, pts, 3)

    # 地面：tile_* 是带内缩边框的单块贴图，平铺会出现双边框，
    # 所以地面改用"纸白填充 + 手绘顶线 + 短竖纹"，贴图只用于独立方块。
    ground_y = 440
    pygame.draw.rect(screen, config.COLOR_GROUND, (0, ground_y, config.WIDTH, config.HEIGHT - ground_y))
    top_line = [(x, ground_y + int(1.2 * math.sin(x / 17.0))) for x in range(-2, config.WIDTH + 4, 12)]
    pygame.draw.lines(screen, config.COLOR_INK, False, top_line, 3)
    for x in range(12, config.WIDTH, 64):
        pygame.draw.line(screen, (214, 210, 200), (x, ground_y + 10), (x + 4, config.HEIGHT), 1)

    # 悬浮方块：验证 tile 贴图能正常加载
    tile_top = pygame.image.load(os.path.join(config.IMAGE_DIR, "tiles", "tile_top.png")).convert_alpha()
    tile_fill = pygame.image.load(os.path.join(config.IMAGE_DIR, "tiles", "tile.png")).convert_alpha()
    for i in range(3):
        screen.blit(tile_top, (660 + i * config.TILE, 312))
        screen.blit(tile_fill, (660 + i * config.TILE, 312 + config.TILE))

    # 主角：按不透明区域底边对齐地面，避免图片留白造成"悬空"
    hero = pygame.image.load(os.path.join(config.IMAGE_DIR, "hero", "standright.png")).convert_alpha()
    bbox = hero.get_bounding_rect()
    screen.blit(hero, (150 - bbox.x, ground_y - bbox.bottom))

    # 金币（烫金）
    coin = pygame.image.load(os.path.join(config.IMAGE_DIR, "collectibles", "tile_coin.png")).convert_alpha()
    coin = pygame.transform.smoothscale(coin, (44, 44))
    coin = compat.tint(coin, config.COLOR_COIN)
    screen.blit(coin, (420, ground_y - 120))

    # 篝火（存档点，点亮态 = 橙）
    camp = pygame.image.load(os.path.join(config.IMAGE_DIR, "checkpoints", "campfire.png")).convert_alpha()
    camp = pygame.transform.smoothscale(camp, (72, 72))
    camp = compat.tint(camp, config.COLOR_CAMP)
    cb = camp.get_bounding_rect()
    screen.blit(camp, (540 - cb.x, ground_y - cb.bottom - 2))

    # 文案
    screen.blit(font_big.render("M0 环境检查通过", True, config.COLOR_INK), (40, 36))
    screen.blit(font_small.render("pygame %s  ·  960x540  ·  60 FPS" % pygame.version.ver,
                                  True, config.COLOR_MUTED), (42, 84))
    screen.blit(font_small.render("字体：%s   素材：assets/images" % font_name,
                                  True, config.COLOR_MUTED), (42, 110))
    hint = font_small.render("Esc 退出", True, config.COLOR_MUTED)
    screen.blit(hint, (config.WIDTH - hint.get_width() - 32, 40))


def main():
    pygame.init()
    pygame.display.set_caption(config.TITLE)
    screen = compat.make_display((config.WIDTH, config.HEIGHT))
    clock = pygame.time.Clock()

    report_environment()
    print(" 显示   : %dx%d / %d 位 / 驱动 %s"
          % (screen.get_width(), screen.get_height(), screen.get_bitsize(),
             pygame.display.get_driver()))

    font_big, font_name = load_font(34, bold=True)
    font_small, _ = load_font(18)
    print(" 字体   :", font_name)

    smoke = "--smoke" in sys.argv
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        draw_static_frame(screen, font_big, font_small, font_name)
        pygame.display.flip()

        if smoke:
            out = os.path.join(config.DOCS_DIR, "m0_check.png")
            os.makedirs(config.DOCS_DIR, exist_ok=True)
            pygame.image.save(screen, out)
            print(" 截图   :", out)
            running = False

        clock.tick(config.FPS)

    pygame.quit()


if __name__ == "__main__":
    main()
