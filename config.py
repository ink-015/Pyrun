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

# 目标运行环境：海龟编辑器内置 Python 3.6.5 + pygame 1.9.6。
# pygame 1.9.6 在无头（SDL_VIDEODRIVER=dummy）下默认给出 8 位调色板表面，
# 会让文字变实心块、透明贴图贴不上，所以必须显式要求 32 位。
DISPLAY_DEPTH = 32

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
COLOR_DASH = (110, 158, 210)       # 冲刺冷却条（功能色，不参与美术）
COLOR_TRAIL = (186, 182, 172)      # 冲刺残影线，比墨线淡，不抢主体

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

# ---------- 角色动画（M2.5 接入素材） ----------
# 跑步帧按位移推进，不按时间：每走这么多像素换一帧。
# 8 帧 ÷ (300px/s ÷ 15.75px) ≈ 0.42s 一轮，是常见跑步循环节奏。
RUN_STRIDE_PX = 15.75
# 低于这个速度算"站着"，否则减速末段会播成慢动作迈腿
RUN_ANIM_MIN_SPEED = 25.0
# 落地反馈：整体下沉这么多像素再弹回（素材没有落地帧，用位移代替）
LAND_SINK_PX = 3.0
# 贴图锚点：canvas = 画布底边贴地（保留作者画的跑步起伏）
#           content = 内容底边贴地（每帧强制脚落地，起伏被抹平）
HERO_ANCHOR = "content"

# ---------- 相机（M3 起使用） ----------
# 指数平滑系数：每帧向目标靠拢 1-exp(-k*dt)，k 越大跟得越紧。
# 7.0 时一帧收敛约 11%，跑起来镜头略微滞后于角色，不晕也不脱节。
CAMERA_LERP = 7.0
# 竖直死区：角色在画面中线上下这么多像素内移动时，镜头不动。
# 没有它的话每次跳跃整个画面都会跟着上下弹，非常晕。
CAMERA_DEADZONE_Y = 48.0

# ---------- 关卡 ----------
DEFAULT_LEVEL = os.path.join(LEVEL_DIR, "l1.txt")

GLIDE_FALL_SPEED = 120.0
GLIDE_RUN_SPEED = 330.0
DASH_SPEED = 560.0
DASH_TIME = 0.16
DASH_COOLDOWN = 0.8
RESPAWN_TIME = 0.35
INVULN_TIME = 0.5

# ---------- 机关（M4 起使用） ----------
# 弹跳板初速：比跳跃（-640）高出一截，能上 1.8 格左右。
# 再高会让"跳不上去 = 用弹跳板"这条关卡语言失效，玩家会只靠弹跳板推图。
BOUNCE_SPEED = 980.0
# 双保险：正常流程靠"弹起后 vy<0"天然不会连触，这个冷却只防同帧多次判定
BOUNCE_COOLDOWN = 0.10
# 移动平台速度与行程（2 格）。速度取 90px/s：站在上面等一轮约 2.8 秒，
# 比角色跑速慢很多，玩家不会觉得自己在跟平台赛跑。
PLATFORM_SPEED = 90.0
PLATFORM_TRAVEL = 128.0
# 死亡定格：这段时间角色不再受物理控制，画面显示死亡提示再重生。
# 0.45s 够看清"我死了"又不至于烦。
DEATH_FREEZE = 0.45
# 危险格判定内缩：不留缝的话贴着刺边跑过也会死，手感像碰瓷
HAZARD_INSET = 6
# 篝火触发框：比格子矮一点，避免站在上层平台擦到下层篝火
CHECKPOINT_BOX = (48, 56)
# 单向平台板子厚度：只挡落下、不挡穿过，板子本身要薄才看得懂
ONEWAY_THICK = 14

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
    # M3 起没有关卡文件就没什么可玩的，启动时直接报出来
    DEFAULT_LEVEL,
]


def check_environment():
    """启动自检，返回 (缺失目录列表, 缺失文件列表)。不抛异常。"""
    missing_dirs = [p for p in REQUIRED_DIRS if not os.path.isdir(p)]
    missing_files = [p for p in REQUIRED_FILES if not os.path.isfile(p)]
    if not os.path.isdir(LEVEL_DIR):
        missing_dirs.append(LEVEL_DIR)
    return missing_dirs, missing_files
