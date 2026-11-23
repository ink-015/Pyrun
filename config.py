# -*- coding: utf-8 -*-
"""全局常量与路径配置。

本文件只存放常量，不导入项目内其他模块（见 README §18.8）。
所有资源路径都由 BASE_DIR 拼接，不写死任何机器专属路径。
"""

import os

# ---------- 路径 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(BASE_DIR, "assets")
IMAGE_DIR = os.path.join(ASSET_DIR, "images")
AUDIO_DIR = os.path.join(ASSET_DIR, "audio")
LEVEL_DIR = os.path.join(BASE_DIR, "levels")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
SAVE_PATH = os.path.join(BASE_DIR, "save.json")

# ---------- 窗口 ----------
TITLE = "火柴人跑酷"
WIDTH = 960
HEIGHT = 540
FPS = 60
TILE = 64
FIXED_DT = 1.0 / 60.0

# ---------- 配色（README §2 功能色） ----------
COLOR_PAPER = (250, 247, 238)      # 纸底 #FAF7EE
COLOR_PAPER_LINE = (235, 231, 220)  # 极淡方格
COLOR_INK = (20, 20, 20)           # 墨线 / 主角
COLOR_MUTED = (126, 122, 112)      # 次要文字
COLOR_DANGER = (247, 201, 190)     # 危险 #F7C9BE
COLOR_COIN = (255, 214, 120)       # 金币 #FFD678
COLOR_CAMP = (242, 164, 75)        # 篝火 #F2A44B
COLOR_GROUND = (251, 250, 246)     # 地面 #FBFAF6
COLOR_HILL = (206, 203, 194)       # 远山 #CECBC2
COLOR_WATER = (198, 222, 232)

# ---------- 手感参数（README §5，M2 起使用） ----------
GRAVITY_UP = 1900.0
GRAVITY_DOWN = 2600.0
JUMP_SPEED = -640.0
JUMP_CUT = 0.42
JUMP_HOLD_GRAVITY_SCALE = 0.85
MAX_FALL_SPEED = 1100.0
RUN_SPEED = 300.0
GROUND_ACCEL = 2200.0
GROUND_DECEL = 2800.0
AIR_ACCEL = 1500.0
COYOTE_TIME = 0.10
JUMP_BUFFER_TIME = 0.12
LAND_SQUASH_TIME = 0.08
GLIDE_FALL_SPEED = 120.0
GLIDE_RUN_SPEED = 330.0
DASH_SPEED = 560.0
DASH_TIME = 0.16
DASH_COOLDOWN = 0.8
RESPAWN_TIME = 0.35
INVULN_TIME = 0.5

# ---------- 字体候选（按顺序回退） ----------
# 注意：不要用 pygame.font.match_font / SysFont —— 在部分 Windows 环境下
# 枚举注册表字体会抛 TypeError（pygame 已知问题）。这里直接按文件名探测。
FONT_CANDIDATES = ["simkai.ttf", "msyh.ttc", "simhei.ttf", "simsun.ttc", "Deng.ttf"]


def _font_dirs():
    """项目自带字体优先，其次是 Windows 字体目录（通过环境变量定位）。"""
    dirs = [os.path.join(ASSET_DIR, "fonts")]
    win = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if win:
        dirs.append(os.path.join(win, "Fonts"))
    return dirs


FONT_DIRS = _font_dirs()

# ---------- 启动自检清单（M0 只检查必需项） ----------
REQUIRED_DIRS = [
    IMAGE_DIR,
    os.path.join(IMAGE_DIR, "tiles"),
    os.path.join(IMAGE_DIR, "hero"),
    AUDIO_DIR,
]

REQUIRED_FILES = [
    os.path.join(IMAGE_DIR, "tiles", "tile.png"),
    os.path.join(IMAGE_DIR, "tiles", "tile_top.png"),
    os.path.join(IMAGE_DIR, "hero", "standright.png"),
    os.path.join(IMAGE_DIR, "hero", "runright0.png"),
    os.path.join(IMAGE_DIR, "checkpoints", "campfire.png"),
]


def check_environment():
    """启动自检，返回 (缺失目录列表, 缺失文件列表)。不抛异常。"""
    missing_dirs = [p for p in REQUIRED_DIRS if not os.path.isdir(p)]
    missing_files = [p for p in REQUIRED_FILES if not os.path.isfile(p)]
    if not os.path.isdir(LEVEL_DIR):
        missing_dirs.append(LEVEL_DIR)
    return missing_dirs, missing_files
