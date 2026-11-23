# -*- coding: utf-8 -*-
"""素材加载、缩放与缓存。

三个必须遵守的约束：

1. **路径**：一律由 `config.ASSET_DIR` 拼接，不依赖当前工作目录。
   VS Code 和海龟编辑器的工作目录不同，写相对路径必炸。

2. **缩放只在加载期做一次**。实测 `smoothscale` 处理 2000x800 要 7.68ms，
   放在 draw 里就是一帧掉到 100 FPS 以下。所以这里把缩放结果缓存下来，
   运行时只做 blit。

3. **素材缺失要能降级**。本模块只抛 `AssetMissing`，由画面层决定退回
   代码绘制还是直接报错——M1 的验收要求「不依赖外部素材」，这条底线
   不能因为接入贴图就丢掉。

关于 `hero/land.png`：文件名看着像「落地帧」，实际是一片草地加泥土的
地砖（100x40，且不含角色）。已实测确认，不要当角色帧加载。
"""

import os

import pygame

import config

# ---------------------------------------------------------------- 异常

class AssetMissing(Exception):
    """素材文件不存在或无法解码。调用方必须准备好降级方案。"""


# ---------------------------------------------------------------- 缓存

_image_cache = {}    # rel -> 原始 Surface
_scaled_cache = {}   # (rel, scale_key) -> 缩放后 Surface
_font_cache = {}     # (size, bold) -> Font
_missing = set()     # 已确认缺失的路径，避免每帧重试 stat


def _abs(rel):
    return os.path.join(config.ASSET_DIR, rel.replace("/", os.sep))


def image(rel):
    """加载原始尺寸图像（带缓存）。失败抛 AssetMissing。"""
    if rel in _image_cache:
        return _image_cache[rel]
    if rel in _missing:
        raise AssetMissing(rel)

    path = _abs(rel)
    if not os.path.isfile(path):
        _missing.add(rel)
        raise AssetMissing(u"文件不存在：%s" % path)
    try:
        surf = pygame.image.load(path)
    except Exception as exc:
        _missing.add(rel)
        raise AssetMissing(u"解码失败 %s：%s" % (path, exc))

    # 素材是黑线条 + 透明底，必须转成带 alpha 的 32 位表面。
    # 不转换的话 blit 会把透明区域当黑色实心块贴上去。
    if surf.get_alpha() is not None or surf.get_flags() & pygame.SRCALPHA:
        surf = surf.convert_alpha()
    _image_cache[rel] = surf
    return surf


def smooth_scaled(surf, factor, cache_key=None):
    """按比例缩放，结果缓存。factor 会先量化到 4 位小数当 key。"""
    if abs(factor - 1.0) < 1e-6:
        return surf
    key = (cache_key, round(factor, 4))
    if key in _scaled_cache:
        return _scaled_cache[key]
    w = max(1, int(round(surf.get_width() * factor)))
    h = max(1, int(round(surf.get_height() * factor)))
    out = pygame.transform.smoothscale(surf, (w, h))
    _scaled_cache[key] = out
    return out


def image_scaled(rel, factor):
    """加载并按比例缩放，全程缓存。"""
    return smooth_scaled(image(rel), factor, cache_key=rel)


# ---------------------------------------------------------------- 字体

def font(size, bold=False):
    """按文件路径探测中文字体，带缓存。返回 (font, 字体文件名)。

    `pygame.font.SysFont` / `match_font` 在部分 Windows 环境下会直接崩
    （枚举注册表字体抛 TypeError），所以这里逐个试字体文件。
    候选顺序来自 config.FONT_DIRS / config.FONT_CANDIDATES。
    """
    key = (size, bool(bold))
    if key in _font_cache:
        return _font_cache[key]

    for folder in config.FONT_DIRS:
        for name in config.FONT_CANDIDATES:
            path = os.path.join(folder, name) if folder else name
            if not os.path.isfile(path):
                continue
            try:
                f = pygame.font.Font(path, size)
                f.set_bold(bold)
                _font_cache[key] = (f, name)
                return _font_cache[key]
            except Exception:
                continue

    f = pygame.font.Font(None, size)   # 兜底：pygame 自带字体（无中文）
    f.set_bold(bold)
    _font_cache[key] = (f, "default")
    return _font_cache[key]


# ---------------------------------------------------------------- 角色动画

# 角色只有三类动作。跳跃只有一帧，上升下落共用——素材就这么给的，
# 不做假的下落帧（硬造第二帧只会更怪）。
HERO_TARGET_HEIGHT = 70.0   # 站立帧缩放到这个视觉高度，与碰撞盒同高


def _numbered(folder_rel, prefix):
    """按 runleft0.png / runleft1.png … 的序号连续读取，遇到缺号即停。

    不硬编码帧数：以后替换素材从 8 帧变 12 帧也不用改代码。
    """
    out = []
    i = 0
    while True:
        rel = "%s/%s%d.png" % (folder_rel, prefix, i)
        if not os.path.isfile(_abs(rel)):
            break
        out.append(rel)
        i += 1
    return out


def hero_anim_specs():
    """返回 {动作名: {"left": [相对路径...], "right": [...]}}。"""
    folder = "images/hero"
    return {
        "idle": {
            "left": ["%s/standleft.png" % folder],
            "right": ["%s/standright.png" % folder],
        },
        "run": {
            "left": _numbered(folder, "runleft"),
            "right": _numbered(folder, "runright"),
        },
        "jump": {
            "left": ["%s/jumpleft.png" % folder],
            "right": ["%s/jumpright.png" % folder],
        },
    }


class HeroSprites(object):
    """角色贴图集合。

    frames[动作][朝向] = [Surface, ...]，朝向用 -1（左）/ +1（右）。
    缩放比例由站立帧的内容高度算出，所有动作共用同一比例，
    这样跑步、跳跃的相对大小与素材原稿一致。

    anchor 决定「脚踩在哪里」，这是本类最重要的一个决定：

      "canvas"  —— 画布底边对齐地面。跑动帧在画布内本身有 0~18px 的
                   上下位移（作者画的跑步起伏），这样会**原样保留**，
                   跑起来有弹性；代价是中段几帧脚离地较远。
      "content" —— 内容底边对齐地面。每帧都把脚压回地面，起伏被抹平，
                   看着像贴地滑行，但绝不会出现"脚悬空"。

    两种都实测过，见 docs/hero_run_strip.png 与 docs/hero_run_strip_content.png。
    """

    def __init__(self, target_height=HERO_TARGET_HEIGHT, anchor="canvas"):
        self.frames = {}
        self.canvas = (0, 0)
        self.scale = 1.0
        self.target_height = target_height
        self.anchor = anchor
        self._foot = {}      # (动作, 朝向, 帧号) -> 脚底距画布顶部的像素
        self._build()


    def _build(self):
        specs = hero_anim_specs()
        idle_left = specs["idle"]["left"][0]
        raw = image(idle_left)
        box = raw.get_bounding_rect()
        if box.height <= 0:
            raise AssetMissing(u"站立帧内容为空，无法确定缩放比例")
        # 用站立帧定标：它是最能代表「角色高度」的一帧
        self.scale = float(self.target_height) / box.height
        self.canvas = (int(round(raw.get_width() * self.scale)),
                       int(round(raw.get_height() * self.scale)))

        for action, sides in specs.items():
            self.frames[action] = {}
            for side, rels in sides.items():
                facing = -1 if side == "left" else 1
                seq = []
                for i, rel in enumerate(rels):
                    raw = image(rel)
                    box = raw.get_bounding_rect()
                    seq.append(image_scaled(rel, self.scale))
                    if self.anchor == "content":
                        # 内容底边（画布坐标）× 缩放 = 脚底距缩放后画布顶部的距离
                        self._foot[(action, facing, i)] = int(round(
                            (box.y + box.height) * self.scale))
                    else:
                        self._foot[(action, facing, i)] = seq[-1].get_height()
                self.frames[action][facing] = seq

    # ------------------------------------------------------------ 查询
    def frame_count(self, action, facing):
        return len(self.frames[action][facing])

    def frame(self, action, facing, index):
        seq = self.frames[action][facing]
        return seq[index % len(seq)]

    def foot_offset(self, action, facing, index):
        """脚底距贴图顶部的像素数。锚点模式不同，这个值不同。"""
        n = self.frame_count(action, facing)
        return self._foot[(action, facing, index % n)]

    def blit_pos(self, foot_center_x, foot_y, action, facing, index):
        """给定脚底中心点，返回贴图的 blit 左上角坐标。"""
        img = self.frame(action, facing, index)
        x = int(round(foot_center_x - img.get_width() / 2.0))
        y = int(round(foot_y - self.foot_offset(action, facing, index)))
        return (x, y)

    def canvas_of(self, facing):
        seq = self.frames["idle"][facing]
        return seq[0].get_size()

    def describe(self):
        parts = []
        for action in ("idle", "run", "jump"):
            n = len(self.frames[action][1])
            parts.append("%s=%d帧" % (action, n))
        return u"%s，缩放 %.3f，画布 %dx%d，锚点 %s" % (
            "、".join(parts), self.scale, self.canvas[0], self.canvas[1],
            self.anchor)


def load_hero(target_height=HERO_TARGET_HEIGHT, anchor=None):
    """加载角色贴图；缺失时抛 AssetMissing，调用方需降级。"""
    return HeroSprites(target_height, anchor or config.HERO_ANCHOR)


# ---------------------------------------------------------------- 自检辅助

def cache_info():
    return {
        "images": len(_image_cache),
        "scaled": len(_scaled_cache),
        "fonts": len(_font_cache),
        "missing": sorted(_missing),
    }


def clear_cache():
    """仅测试用：清空缓存，验证冷加载路径。"""
    _image_cache.clear()
    _scaled_cache.clear()
    _font_cache.clear()
    _missing.clear()
