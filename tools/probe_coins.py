# -*- coding: utf-8 -*-
"""金币可达性探针。

为什么需要它：地图里的金币是不是"跳一跳就能吃到"，靠肉眼估高度很容易
翻车——跳高是 127px，而一格是 64px，差半格就是"永远差一点"。玩家反馈
"有金币拿不到"时，必须能用物理仿真给出确定的 yes/no，而不是再目测一遍。

做法（只关心"能不能碰到"，不关心"怎么跑过去"）：
  1. 枚举每枚金币附近所有可以站立的表面（地形顶面 + 移动平台的最高/最低位）；
  2. 把角色放到该表面上，试若干种输入脚本（朝金币跑 / 朝金币跳 / 原地跳）；
  3. 用真实的 Player.update 跑 120 帧，只要有一帧角色碰撞盒与金币相交，
     这枚金币就判"可从该表面拿到"。

结论分三档：
  OK     至少一个表面能拿到（并打印是哪种动作）
  BLOCK  金币本身埋在实心里（画都画在墙里，永远拿不到）
  FAIL   附近任何表面都碰不到——这就是玩家反馈的那种金币

用法：
    python tools/probe_coins.py            # 全部关卡
    python tools/probe_coins.py l2 l3      # 指定关卡
    python tools/probe_coins.py l2 -v      # 打印每一次尝试
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

import compat
import config
import levels_catalog
import player as player_mod
import world as world_mod

FRAMES = 120          # 单次尝试的时长（2 秒足够跳一次再落地）
LOOK_X = 420          # 只考虑金币左右这么远以内的落脚面
LOOK_Y = 420          # 只考虑金币下方这么深以内的落脚面


def _surfaces(w):
    """所有可站立的水平面：[(left, right, top, 标签)]。"""
    out = []
    for r in w.solids:
        out.append((r.left, r.right, r.top, "地形"))
    for p in w.platforms:
        # 双向行程都要算：站在最低位和最高位都能起跳
        lo, hi = p.rect.top, p.rect.top
        if p.axis == "y":
            lo, hi = p.rect.top - config.PLATFORM_TRAVEL, p.rect.top
        for top in (lo, hi):
            out.append((p.rect.left, p.rect.right, int(top), "平台"))
    return out


def _try(w, coin, sx, sy, axis, jump_at, verbose, tag):
    """从 (sx, sy) 出发按脚本跑，碰到金币就返回 True。"""
    p = player_mod.Player(sx, sy)
    inp = player_mod.InputState()
    box = coin["rect"]
    for f in range(FRAMES):
        inp.axis = axis
        if f == jump_at:
            inp.jump_pressed = True
        inp.jump_held = (jump_at >= 0 and f >= jump_at)
        if p.rect.colliderect(box):
            if verbose:
                print(u"      ✓ %s 第 %d 帧相交 (%.0f,%.0f) 轴=%+.0f 跳@%d"
                      % (tag, f, p.x, p.y, axis, jump_at))
            return True
        p.update(config.FIXED_DT, inp, w.collision_solids(),
                 oneways=w.oneways, bouncers=w.bouncers)
    if verbose:
        print(u"      ✗ %s 轴=%+.0f 跳@%d  末(%.0f,%.0f)"
              % (tag, axis, jump_at, p.x, p.y))
    return False


def probe(path, verbose=False):
    w = world_mod.World.load(path)
    print(u"== %s  金币 %d 枚" % (os.path.basename(path), len(w.coins)))
    surfaces = _surfaces(w)
    fails = []
    for i, coin in enumerate(w.coins):
        box = coin["rect"]
        cx, cy = box.centerx, box.centery
        tag = u"#%02d (%d,%d) 格(%d,%d)" % (i, cx, cy, cx // config.TILE,
                                            cy // config.TILE)
        # 埋进实心
        buried = None
        for r in w.solids:
            if r.colliderect(box):
                buried = r
                break
        if buried is not None:
            print(u"  %s  BLOCK 埋在实心里 %s" % (tag, buried))
            fails.append((i, "BLOCK"))
            continue

        cands = []
        for (l, r, top, kind) in surfaces:
            if top < cy - 40 or top > cy + LOOK_Y:
                continue
            if r < cx - LOOK_X or l > cx + LOOK_X:
                continue
            cands.append((l, r, top, kind))
        # 远的先试近的：按 |top 差| 排序，先试最自然的那块地
        cands.sort(key=lambda c: abs(c[2] - (cy + 70)))

        got = None
        for (l, r, top, kind) in cands:
            # 三个起始横坐标：正下方、左侧助跑位、右侧助跑位
            for sx in (min(max(cx - 13, l + 8), r - 34),
                       min(max(cx - 150, l + 8), r - 34),
                       min(max(cx + 120, l + 8), r - 34)):
                sy = top - player_mod.Player.HEIGHT
                for axis in ((1.0 if cx >= sx else -1.0), 0.0):
                    for jump_at in (1, 8, 14, 20):
                        if _try(w, coin, sx, sy, axis, jump_at, verbose,
                                u"%s@(%.0f,%.0f)" % (kind, sx, top)):
                            got = (kind, sx, top, axis, jump_at)
                            break
                    if got:
                        break
                if got:
                    break
            if got:
                break
        if got:
            print(u"  %s  OK    %s 站 (%.0f,%d) 轴%+.0f 跳@%d"
                  % (tag, got[0], got[1], got[2], got[3], got[4]))
        else:
            print(u"  %s  FAIL  %d 个落脚面都碰不到" % (tag, len(cands)))
            fails.append((i, "FAIL"))
    return fails


def main(argv):
    pygame.display.init()
    compat.make_display((64, 64))
    verbose = "-v" in argv
    keys = [a for a in argv[1:] if not a.startswith("-")]
    if not keys:
        keys = [lv["key"] for lv in [levels_catalog.at(i) for i in range(levels_catalog.count())]]
    bad = {}
    for k in keys:
        p = levels_catalog.path_of(k)
        if not p or not os.path.exists(p):
            print(u"!! 缺少关卡 %s" % k)
            continue
        f = probe(p, verbose)
        if f:
            bad[k] = f
    print(u"\n== 汇总")
    if not bad:
        print(u"  全部金币可达")
        return 0
    for k, f in bad.items():
        print(u"  %s：%s" % (k, u"、".join(u"#%02d %s" % (i, why) for i, why in f)))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
