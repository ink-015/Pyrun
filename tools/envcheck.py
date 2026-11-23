# -*- coding: utf-8 -*-
"""环境体检脚本：一条命令复现全部已知环境坑。

用法（命令行或海龟编辑器里都可以）：

    python tools/envcheck.py

输出的每一项都是今天实测踩过的坑。改代码后跑一次，能提前发现
"在新机器/编辑器升级后突然坏掉"的情况。

退出码 0 = 全部通过；1 = 有 FAIL。
"""

from __future__ import print_function

import glob
import io
import locale
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

import compat  # noqa: E402
import config  # noqa: E402
import io_utils  # noqa: E402

RESULTS = []


def check(name, fn, level="FAIL"):
    """level='SKIP' 表示失败不影响游戏运行（例如没有声卡）。"""
    try:
        detail = fn()
        ok = True
        msg = detail or ""
    except Exception as e:
        ok = level != "FAIL"
        msg = "%s: %s" % (type(e).__name__, e)
    RESULTS.append((ok, name, msg))
    tag = "PASS" if ok else "FAIL"
    print(u"  [%s] %-18s %s" % (tag, name, msg))
    sys.stdout.flush()


# ---------------------------------------------------------------- 1. 运行时
def sdl_label():
    """pygame 1.9.6 没有 version.SDL 属性，不能直接取。"""
    sdl = getattr(pygame.version, "SDL", None)
    if isinstance(sdl, tuple):
        return ".".join(str(x) for x in sdl)
    if isinstance(sdl, str) and sdl:
        return sdl
    return "1.2（pygame 未暴露版本号，按 1.9.6 推定）"


def is_sdl1():
    """SDL 1.2 与 SDL 2 的事件模型不同，部分检查只在 SDL1 下成立。"""
    sdl = getattr(pygame.version, "SDL", None)
    if isinstance(sdl, tuple) and sdl:
        return int(sdl[0]) < 2
    return True


def c_runtime():
    return "Python %s / pygame %s / SDL %s" % (
        sys.version.split()[0], pygame.version.ver, sdl_label())


def c_display_depth():
    screen = compat.make_display((config.WIDTH, config.HEIGHT))
    bits = screen.get_bitsize()
    assert bits == 32, "显示面只有 %d 位，文字会变实心块（需 32 位）" % bits
    return "%dx%d / %d 位 / %s" % (screen.get_width(), screen.get_height(), bits,
                                   pygame.display.get_driver())


# ---------------------------------------------------------------- 2. 兼容层
def c_rounded_stroke():
    """gfxdraw.aapolygon 曾漏画整条底边，这里验证描边四边闭合。"""
    surf = pygame.Surface((200, 100), pygame.SRCALPHA)
    surf.fill((255, 255, 255, 255))
    compat.rounded_rect(surf, (0, 0, 0), (10, 10, 180, 80), radius=12, width=3)

    def dark(p):
        c = surf.get_at((int(p[0]), int(p[1])))
        return c[0] + c[1] + c[2] < 300

    misses = []
    if not any(dark((100, y)) for y in range(86, 94)):
        misses.append("底边")
    if not any(dark((100, y)) for y in range(7, 15)):
        misses.append("上边")
    if not any(dark((x, 50)) for x in range(6, 15)):
        misses.append("左边")
    if not any(dark((x, 50)) for x in range(186, 195)):
        misses.append("右边")
    assert not misses, "描边缺失：" + "、".join(misses)
    return "四边闭合"


def c_rounded_fill():
    surf = pygame.Surface((200, 100), pygame.SRCALPHA)
    surf.fill((255, 255, 255, 255))
    compat.rounded_rect(surf, (0, 0, 0), (10, 10, 180, 80), radius=12)
    center = surf.get_at((100, 50))
    corner = surf.get_at((11, 11))
    assert center[0] < 40, "中心没填充"
    assert corner[0] > 200, "圆角处被填满，圆角失效"
    return "填充正常，圆角有效"


def c_panel():
    surf = pygame.Surface((300, 140))
    surf.fill((250, 247, 238))
    compat.panel(surf, (10, 10, 280, 120), radius=16)
    inner = surf.get_at((150, 70))
    assert inner[0] > 240, "面板内部不是浅色"
    return "panel 可用"


def c_clip_line():
    r = (0, 0, 10, 10)
    assert compat.clip_line(r, (5, 5), (8, 8)) is not None
    assert compat.clip_line(r, (-5, 5), (15, 5)) == ((0.0, 5.0), (10.0, 5.0))
    assert compat.clip_line(r, (20, 20), (30, 30)) is None
    return "三组用例全部正确"


def c_dist():
    assert abs(compat.dist((0, 0), (3, 4)) - 5.0) < 1e-6
    return "dist(3,4)=5"


def c_tint():
    src = pygame.Surface((10, 10), pygame.SRCALPHA)
    src.fill((255, 255, 255, 255))
    src.set_at((5, 5), (0, 0, 0, 255))          # 一条黑线
    out = compat.tint(src, config.COLOR_COIN)
    got = out.get_at((0, 0))[:3]
    # BLEND_RGBA_MULT 用 (d*s)>>8，白色会得到 254 而不是 255，允许 ±2
    diff = max(abs(got[i] - config.COLOR_COIN[i]) for i in range(3))
    assert diff <= 2, "白色处染色偏差过大：%s vs %s" % (got, config.COLOR_COIN)
    assert out.get_at((5, 5))[0] < 40, "黑线被染掉了"
    return "白色染色 %s（偏差 %d）/ 黑线保留" % (got, diff)


# ---------------------------------------------------------------- 3. 编码
def _tmpdir():
    import tempfile
    if not hasattr(_tmpdir, "d"):
        _tmpdir.d = tempfile.mkdtemp(prefix="pyrun_envcheck_")
    return _tmpdir.d


# ---------------------------------------------------------------- 3. 焦点事件（三套 SDL 模型）
def c_focus_event():
    """焦点事件在三个 pygame 版本上是三套不同模型，验证 compat 认得出当前这套。

    用 event.Event 直接构造事件对象、不 post，避免依赖显示驱动是否过滤事件。
    """
    if hasattr(pygame, "WINDOWFOCUSLOST") and hasattr(pygame, "WINDOWFOCUSGAINED"):
        # pygame 2.6+：独立事件类型
        lost = pygame.event.Event(pygame.WINDOWFOCUSLOST)
        gained = pygame.event.Event(pygame.WINDOWFOCUSGAINED)
    elif hasattr(pygame, "WINDOWEVENT") and hasattr(pygame, "WINDOWEVENT_FOCUS_LOST"):
        # pygame 2.0~2.5：统一类型 + 子类型
        lost = pygame.event.Event(pygame.WINDOWEVENT, {"event": pygame.WINDOWEVENT_FOCUS_LOST})
        gained = pygame.event.Event(pygame.WINDOWEVENT, {"event": pygame.WINDOWEVENT_FOCUS_GAINED})
    else:
        # SDL 1.2：ACTIVEEVENT + state 位
        lost = pygame.event.Event(pygame.ACTIVEEVENT, {"state": 2, "gain": 0})
        gained = pygame.event.Event(pygame.ACTIVEEVENT, {"state": 2, "gain": 1})

    assert compat.focus_lost(lost), "focus_lost() 没认出失去焦点事件"
    assert compat.focus_gained(gained), "focus_gained() 没认出获得焦点事件"
    assert not compat.focus_lost(gained), "获得焦点被误判为失去焦点"
    assert not compat.focus_gained(lost), "失去焦点被误判为获得焦点"
    return "%s，四种判定全对" % compat.focus_event_model()


def c_utf8_roundtrip():
    tmp = os.path.join(_tmpdir(), "utf8.txt")
    text = u"第一关 · 中文\n第二行：跳跃\n"
    io_utils.write_text(tmp, text)
    back = io_utils.read_text(tmp)
    assert back == text, "往返内容不一致"

    # 反证：默认编码不是 UTF-8 时，裸 open() 读 UTF-8 中文必然抛异常。
    # 但如果解释器处于 UTF-8 模式（PYTHONUTF8=1、-X utf8、或 3.15+ 的默认行为），
    # 裸 open() 也不会崩——那只是环境不同，不能判失败，否则换台机器就误报。
    enc = locale.getpreferredencoding(False)
    if enc.lower().replace("-", "").replace("_", "") == "utf8":
        return "io_utils 正常；默认编码 %s（UTF-8 模式），GBK 反证不适用" % enc

    crashed = False
    try:
        with io.open(tmp, "r") as f:
            f.read()
    except UnicodeDecodeError:
        crashed = True
    except LookupError:
        crashed = True
    assert crashed, "默认编码是 %s，裸 open() 却没崩，字符集假设需复核" % enc
    return "io_utils 正常；默认编码 %s，裸 open() 确实 UnicodeDecodeError" % enc


def c_json_roundtrip():
    tmp = os.path.join(_tmpdir(), "data.json")
    data = {u"关卡": 1, u"死亡": 3, u"道具": [u"滑翔伞"]}
    io_utils.write_json(tmp, data)
    back = io_utils.read_json(tmp, None)
    assert back == data, "JSON 往返不一致"
    assert io_utils.read_json(os.path.join(_tmpdir(), "不存在.json"), {}) == {}
    return "中文键值往返正常，缺失文件返回默认值"


# ---------------------------------------------------------------- 4. 音频
def c_mixer():
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
    except Exception as e:
        return "无声卡，已降级（%s）" % e
    pygame.mixer.set_num_channels(24)
    return "采样率 %s，声道 %d" % (pygame.mixer.get_init(), pygame.mixer.get_num_channels())


def c_audio_files():
    oggs = sorted(glob.glob(os.path.join(config.AUDIO_DIR, "*", "*.ogg")))
    assert oggs, "assets/audio 下没有 .ogg"
    if not pygame.mixer.get_init():
        return "跳过：无音频设备，共 %d 个文件未试听" % len(oggs)
    t0 = time.time()
    bad = []
    for p in oggs:
        try:
            s = pygame.mixer.Sound(p)
            s.get_length()
        except Exception as e:
            bad.append("%s(%s)" % (os.path.basename(p), e))
    assert not bad, "加载失败：" + "，".join(bad[:3])
    return "%d 个全部可加载，耗时 %.0f ms" % (len(oggs), (time.time() - t0) * 1000)


# ---------------------------------------------------------------- 5. 素材与字体
def c_images():
    pngs = []
    for d in sorted(os.listdir(config.IMAGE_DIR)):
        folder = os.path.join(config.IMAGE_DIR, d)
        if os.path.isdir(folder):
            pngs.extend(sorted(glob.glob(os.path.join(folder, "*.png"))))
    assert pngs, "assets/images 下没有 png"
    bad = []
    for p in pngs:
        try:
            im = pygame.image.load(p)
            im = im.convert_alpha()
            w, h = im.get_size()
            assert w > 0 and h > 0
        except Exception as e:
            bad.append(os.path.basename(p))
    assert not bad, "损坏或无法加载：%s" % ", ".join(bad[:5])
    return "%d 张全部可加载" % len(pngs)


def c_font():
    font, name = None, None
    for folder in config.FONT_DIRS:
        for fn in config.FONT_CANDIDATES:
            p = os.path.join(folder, fn)
            if os.path.isfile(p):
                try:
                    font = pygame.font.Font(p, 24)
                    name = fn
                    break
                except Exception:
                    continue
        if font:
            break
    assert font is not None, "一个中文字体都没加载成功"
    surf = font.render(u"跳跃 空格 停", True, (0, 0, 0))
    w, h = surf.get_size()
    assert w > 20 and h > 10, "文字尺寸异常 %s" % ((w, h),)
    ink = 0
    for x in range(0, w, 2):
        for y in range(0, h, 2):
            if surf.get_at((x, y))[3] > 30:
                ink += 1
    assert ink > (w * h) // 40, "文字几乎是空白（编码或字体不匹配）"
    return "%s，%dx%d，非空像素 %d" % (name, w, h, ink)


# ---------------------------------------------------------------- 6. 语法与 API 静态扫描
# 分两类，因为它们的失效范围完全不同：
#
#  A. Python 3.7+ 语法/标准库 —— 任何环境都禁。哪怕当前用 3.11 跑得好好的，
#     一旦回到海龟的 3.6 就是语法错误，交付验收会直接崩。
#  B. pygame 2.0+ 专有 API —— 只在 pygame 1.9.6 下禁。用 3.11 开发时它们是合法的，
#     而且写双环境兼容代码（例如焦点事件分支）必须用到，不能一律封杀。
FORBIDDEN_PY = [
    ("math.dist(", "Python 3.8+，改用 compat.dist"),
    ("capture_output=", "Python 3.7+ subprocess 参数，改用 stdout=subprocess.PIPE"),
    ("from __future__ import annotations", "Python 3.7+"),
    ("import dataclasses", "Python 3.7+ 标准库（本机是 backport，不保证别人也有）"),
]
FORBIDDEN_PYGAME2 = [
    ("border_radius", "pygame 2.0+ 参数，1.9.6 没有，改用 compat.rounded_rect"),
    (".clipline(", "pygame 2.0+ 方法，改用 compat.clip_line"),
    ("pygame.SCALED", "pygame 2.0+，1.9.6 没有"),
    ("WINDOWFOCUSLOST", "SDL1.2 没有这个事件，需按 SDL 版本分支后再用"),
]
ALLOW_FILES = {"compat.py", "envcheck.py"}


def c_static_scan():
    rules = list(FORBIDDEN_PY)
    sdl1 = is_sdl1()
    if sdl1:
        rules += FORBIDDEN_PYGAME2
    hits = []
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        base = os.path.basename(path)
        if base in ALLOW_FILES:
            continue
        try:
            text = io_utils.read_text(path)
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for pat, why in rules:
                if pat in line:
                    hits.append("%s:%d 用了 %s（%s）" % (base, i, pat, why))
    assert not hits, "; ".join(hits[:4])
    scope = "SDL1 全表" if sdl1 else "SDL2 下仅 Python 兼容项"
    return "根目录 .py 无禁用 API（%s，%d 条规则）" % (scope, len(rules))


def c_walrus():
    hits = []
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        if os.path.basename(path) in ALLOW_FILES:
            continue
        for i, line in enumerate(io_utils.read_text(path).splitlines(), 1):
            if ":=" in line and not line.strip().startswith("#"):
                hits.append("%s:%d" % (os.path.basename(path), i))
    assert not hits, "疑似海象运算符（3.8+）：%s" % ", ".join(hits[:4])
    return "未发现 := "


# ---------------------------------------------------------------- 7. 性能基线
def c_perf():
    tile = pygame.image.load(os.path.join(config.IMAGE_DIR, "tiles", "tile_top.png")).convert_alpha()
    hero = pygame.image.load(os.path.join(config.IMAGE_DIR, "hero", "runright3.png")).convert_alpha()
    work = pygame.Surface((config.WIDTH, config.HEIGHT))

    def frame():
        work.fill(config.COLOR_PAPER)
        for x in range(-config.TILE, config.WIDTH + config.TILE, config.TILE):
            work.blit(tile, (x, 400))
            work.blit(tile, (x, 464))
        for i in range(40):
            work.blit(hero, (i * 22 % 900, 320))

    t0 = time.time()
    for _ in range(120):
        frame()
    ms = (time.time() - t0) * 1000 / 120
    assert ms < 12.0, "40 个精灵单帧 %.1f ms，已接近 16.7ms 预算" % ms
    return "40 精灵 %.2f ms/帧（预算 16.7）" % ms


def c_panel_cost():
    work = pygame.Surface((config.WIDTH, config.HEIGHT))
    t0 = time.time()
    for _ in range(60):
        compat.panel(work, (20, 20, 300, 120), radius=16, width=3)
    ms = (time.time() - t0) * 1000 / 60
    return "%.2f ms/次（>0.5 必须缓存，不要每帧重画）" % ms


# ---------------------------------------------------------------- 主流程
def main():
    pygame.init()

    print("=" * 70)
    print(u" 火柴人跑酷 · 环境体检")
    print("=" * 70)

    check(u"运行时版本", c_runtime)
    check(u"显示面 32 位", c_display_depth)
    check(u"圆角描边四边闭合", c_rounded_stroke)
    check(u"圆角填充与圆角", c_rounded_fill)
    check(u"面板 panel()", c_panel)
    check(u"线段裁剪 clip_line", c_clip_line)
    check(u"距离 dist", c_dist)
    check(u"功能色染色 tint", c_tint)
    check(u"焦点事件分支", c_focus_event)
    check(u"UTF-8 读写 io_utils", c_utf8_roundtrip)
    check(u"JSON 读写", c_json_roundtrip)
    check(u"音频设备", c_mixer, level="SKIP")
    check(u"音效可加载", c_audio_files, level="SKIP")
    check(u"图片可加载", c_images)
    check(u"中文字体", c_font)
    check(u"禁用 API 扫描", c_static_scan)
    check(u"3.8+ 语法扫描", c_walrus)
    check(u"渲染性能", c_perf)
    check(u"面板开销", c_panel_cost)

    print("")
    fails = len([r for r in RESULTS if not r[0]])
    print("-" * 70)
    if fails:
        print(u" 结果：%d 项失败，共 %d 项" % (fails, len(RESULTS)))
    else:
        print(u" 结果：全部通过，共 %d 项" % len(RESULTS))
    print("-" * 70)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
