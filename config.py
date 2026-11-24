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
COLOR_GLIDE = (118, 162, 190)      # 滑翔伞（功能色，和冲刺的蓝拉开一点）
COLOR_NPC = (94, 148, 106)         # NPC 名字与对话提示（绿，见设计稿）
COLOR_SIGN = (176, 138, 96)        # 告示牌木头
COLOR_ROCK = (146, 139, 130)       # 落石与碎屑
# 蝙蝠贴图本身是彩色卡通灰，叠在纸面上偏"塑料"。乘一层暖灰让它落回
# 纸面的色系，同时把红眼睛压暗——眼睛太艳会把注意力全吸走。
COLOR_BAT = (168, 160, 150)

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

# ---------- 道具：滑翔伞（M5 起使用） ----------
# 下落上限 120px/s：正常极限是 1100，差一个数量级，玩家一眼能看出"我在飘"。
# 水平 330 略快于跑速 300——道具的价值是"够到跑不到的地方"，不是数值变强。
GLIDE_FALL_SPEED = 120.0
GLIDE_RUN_SPEED = 330.0
# 滑翔时若无方向输入，水平速度按这个减速度衰减。
# 用 AIR_ACCEL(1500) 会让人松手后 0.2 秒就停住，像踩着刹车滑翔。
GLIDE_DECEL = 240.0
# 伞面挂在头顶上方多少像素。24 时伞几乎贴在头上，看着像帽子；
# 32 加上 20px 的伞面高度，缰绳才有可见的长度，读得出"伞在兜着他"。
GLIDE_CANOPY_LIFT = 32
# 道具拾取判定：整格宽、合计 3 格高（道具所在格 + 往上 2 格）。
# 只按格子中心给 40x40 会出事：玩家在道具前方起跳，正好从它头顶飞过去，
# 一点都碰不到；而滑翔伞是通关必需道具，"跳一下就漏捡"不可接受。
ITEM_CATCH_ROWS = 3

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
# 到端点后停一下再往回走。没有停留时间的话，升降台刚把玩家送到顶就立刻
# 下沉，玩家从静止开始跑 19px 都来不及，只能靠跳——这就是"一直挤一直跳"
# 的由来。0.6 秒足够走动，也不至于等到不耐烦。
PLATFORM_DWELL = 0.6
# 死亡定格：这段时间角色不再受物理控制，画面显示死亡提示再重生。
# 0.45s 够看清"我死了"又不至于烦。
DEATH_FREEZE = 0.45
# 危险格判定内缩：不留缝的话贴着刺边跑过也会死，手感像碰瓷
HAZARD_INSET = 6
# 篝火触发框：比格子矮一点，避免站在上层平台擦到下层篝火
CHECKPOINT_BOX = (48, 56)
# 单向平台板子厚度：只挡落下、不挡穿过，板子本身要薄才看得懂
ONEWAY_THICK = 14
# 终点判定区高度（格）。旗子按"一根杆"算，从杆上任意高度经过都算到；
# 只判脚下那一格的话，蹦着过去的玩家会从旗子头顶飞过去。
GOAL_ZONE_ROWS = 3

# ---------- 敌人与落石（M6 起使用） ----------
# 蝙蝠巡逻速度 70px/s：只有跑速的 1/4。玩家永远跑得过它——"打得过"是
# 数值问题，"敢不敢贴着它过去"是节奏问题，本作只做后者。
BAT_SPEED = 70.0
# 80px 素材缩到 42px：约 0.6 个身位（角色高 70），够看清、又不会堵住通道。
BAT_SCALE = 0.62
# 判定框比贴图小一圈：翅膀尖占了两侧各 8px，按贴图判定会出现
# "还差半个身位就被翅膀刮死"，手感像碰瓷。
BAT_HITBOX = (30, 18)
BAT_BOB_AMP = 8.0
BAT_BOB_SPEED = 2.2
BAT_FPS = 9.0
# 一段连续 'B' 最多几格。太长的话蝙蝠贴着天花板飞一屏，玩家只能干等。
BAT_PATROL_MAX = 6

# UFO：悬停，玩家进入射程后周期性投石
UFO_SCALE = 0.82          # 60px -> 49px
UFO_HITBOX = (44, 26)
UFO_RANGE = 6 * TILE      # 6 格：进圈就开始掉石头，退出去就停
UFO_FIRE_INTERVAL = 2.6
UFO_DROP_OFFSET = 22      # 石头从机腹下方这么远处出现
UFO_TARGET_SLACK = 110    # 落点最多偏离自己这么远，不能隔半张图砸人

# 落石：先预警再落下。预警期间不判定，玩家有 0.9 秒挪开。
ROCK_WARN_TIME = 0.9
ROCK_FALL_SPEED = 700.0
ROCK_SIZE = 26
ROCK_HITBOX = 18
ROCK_SHARD_TIME = 0.35    # 落地后碎屑停留时间，给"砸中了/砸空了"一个反馈
# 天花板裂缝（'R'）的掉落周期。每个裂缝相位不同，免得一排裂缝同步落石。
ROCK_SPAWN_INTERVAL = 2.4

# ---------- 走地怪（M7 起使用） ----------
# 62px/s：比蝙蝠还慢一点。它挡的是路，不是节奏，所以必须慢到"看得清、
# 数得出几步"。判 34x26，贴图 36x30，同样小一圈。
WALKER_SPEED = 62.0
WALKER_HITBOX = (34, 26)
# 身体比判定框大一圈（40x32 vs 34x26）：怪物要"看起来比它的判定更胖"，
# 玩家才不会觉得自己明明没碰到却死了——反过来的宽容才是能接受的。
WALKER_BODY_W = 40
WALKER_BODY_H = 32
WALKER_STEP_FPS = 6.0
# 被踩死后的闪烁时长。0.5 秒里闪 8 次左右：够看出"它没了"，又不至于
# 长到挡住脚下的落点。
WALKER_DIE_TIME = 0.5
WALKER_DIE_FLICKER = 16.0   # 每秒闪几次
# 单格 'Z' 的巡逻半程（像素）。只有一个格子时也得让玩家看出它在动。
WALKER_SOLO_PATROL = 24.0
WALKER_RUN_MAX = 6          # 一段连续 'Z' 最多合并几格
# 踩中反弹速度。比弹跳板（980）低：踩怪是"奖励一次跳"，不是"弹射器"。
STOMP_BOUNCE = 560.0
# 脚底必须落在怪物判定框的上 70% 以内才算踩中。用"判定中心"当分界线的话，
# 斜着擦到上半边也会被算成踩踏，看着像人被怪吸下去。
STOMP_TOP_RATIO = 0.7

# ---------- 旋转刺轮（M7 起使用） ----------
# 四臂十字，吊在格子**上沿**（横梁底面）。臂长 46px 是算出来的，不是拍的：
#
# 轴心 y=576、臂长 42，臂端 618，加上尖端判定圆 8 得到 626；
# 站立角色头顶在 634。所以刀片**扫不到站着的人**（留 8px 余量），
# 但跳起来 8px 以上就会撞上。
#
# 为什么不能做成"横在通道里、等它转开再穿过去"——试过，物理上不成立：
# 轴心离头顶只有 26px 时，角色横穿 160px 相当于绕轴心转了 **144°**，
# 而四条臂每 90° 就有一条。角色跑过去的那 0.53 秒里臂只转 43°，
# 等于"人自己绕着风扇转了一圈"。穷举 360 个起始相位，顺时针 0%、逆时针 0%，
# 一个都过不去。要让相位窗口成立，轴心得离头顶 400px 以上，屏幕外了。
#
# 所以它改成了另一种机关：**禁跳区**。刀片下面横着跑绝对安全，
# 想跳起来抄近道就会被打下来。旋转仍然有意义——它告诉你"上面有东西在动"。
ROTOR_ARMS = 4
ROTOR_ARM_LEN = 42.0
ROTOR_SPEED = 1.6
# 逆时针：臂在屏幕底部那一段与玩家前进方向同向，相对速度更小，
# 视觉上是"让开你"，而不是迎着你的脸扫过来。
ROTOR_SPIN = -1.0
ROTOR_ARM_THICK = 8
ROTOR_TIP_R = 8
# 碰撞采样步长：臂上每隔 7px 取一个小圆，8px 一档能保证不漏判
# （玩家碰撞盒最窄处 26px，远大于采样间距）。
ROTOR_SAMPLE_STEP = 7
ROTOR_HUB_R = 7

# ---------- 荡锤（M7 起使用） ----------
# 摆长 148px：吊点在 H 格顶边（贴着横梁底面），锤心落到地面以上 44px，
# 正好扫过站立角色的腰腿。摆到 ±54° 时锤心抬高到 599，从头顶掠过——
# "摆到最外侧就安全"这件事必须是真的能穿过去，否则玩家只能硬等。
PENDULUM_ARM = 148.0
PENDULUM_AMP = 0.95        # 摆幅（弧度），±54°
PENDULUM_SPEED = 1.7       # 角频率，一个来回约 3.7 秒
PENDULUM_BOB_R = 16
PENDULUM_CHAIN_DOTS = 9

# ---------- 告示牌与 NPC（M6 起使用） ----------
# 交互距离按水平算：竖着给太大会出现"站在三层平台上也能跟底下的人说话"。
SIGN_RANGE = 84
NPC_RANGE = 96
# 气泡提示离目标头顶多高
PROMPT_LIFT = 26

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
