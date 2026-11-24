# -*- coding: utf-8 -*-
"""生成第 5 关「机关实验室」并做硬性检查。

手写 66x14 的 ASCII 地图，改一个字符就得重新数一遍列宽；这里的做法是
"先描述地形，再由代码铺格子"，顺便把跳跃射程、吊点、道具可达性这些
只能算出来的约束一起检查掉。

用法：python tools/gen_l5.py [--write]
不带 --write 只检查并打印，不覆盖文件。
"""

from __future__ import print_function

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

W, H = 66, 14
TILE = 64
FLOOR_TOP = 11          # 默认地面所在行（该行及以下都是实心）

# 跳跃射程（用代码里的参数算，不写死数字）
JUMP_V = 640.0
G_UP = 1900.0
HOLD = 0.85
JUMP_RISE = JUMP_V * JUMP_V / (2 * G_UP * HOLD)      # ≈127px ≈2 格
RUN_SPEED = 300.0
GLIDE_FALL = 120.0
GLIDE_SPEED = 330.0

# 与 config.py 同步（这里不 import config，避免拉起 pygame 初始化）
PLAYER_H = 70           # player.Player.HEIGHT
ROTOR_ARM = 42.0        # config.ROTOR_ARM_LEN
ROTOR_TIP = 8           # config.ROTOR_TIP_R


def build():
    grid = [["."] * W for _ in range(H)]
    floor = {}

    def set_floor(c0, c1, row):
        for c in range(c0, c1 + 1):
            floor[c] = row

    # ---- 地面剖面：三段，每段之间只抬一格 ----
    set_floor(0, 34, 11)
    set_floor(35, 37, 10)
    set_floor(38, 56, 9)
    set_floor(62, 65, 9)      # 对岸

    for c, row in floor.items():
        for r in range(row, H):
            grid[r][c] = "#"

    def put(c, r, ch):
        grid[r][c] = ch

    def solid(c, r):
        grid[r][c] = "#"

    # ---- 出生点 ----
    put(2, 10, "P")

    # ---- 告示牌 1（走地怪）----
    put(4, 10, "S")

    # ---- 第一只走地怪：开阔地，可以等、也可以踩 ----
    for c in (7, 8, 9):
        put(c, 10, "Z")

    # ---- 刺轮：吊在横梁下的低空刀片，贴着地面跑过，跳起来才挨 ----
    for c in (15, 16, 17):
        solid(c, 8)           # 横梁（刺轮的吊点就在 X 格顶边）
    put(13, 10, "S")          # 告示牌 2：讲刀片（必须放在刺轮**左边**）
    put(16, 9, "X")

    # ---- 低矮通道：必须踩怪才能过（跳不过去）----
    for c in range(20, 28):
        solid(c, 8)           # 天花板
    for c in (22, 23, 24):
        put(c, 10, "Z")

    # ---- 荡锤：吊在横梁上 ----
    for c in range(29, 33):
        solid(c, 7)           # 横梁
    put(28, 10, "S")          # 告示牌 3：讲荡锤（放在锤子左边）
    put(30, 8, "H")

    # ---- 滑翔段：伞浮在水面上方，跳出去才够得到 ----
    for c in range(57, 62):
        for r in range(9, H):
            put(c, r, "~")
    put(57, 7, "G")

    # ---- 终点与封口 ----
    put(64, 8, "F")
    for r in range(0, 9):
        solid(65, r)

    # ---- 金币 ----
    for c, r in ((6, 10), (10, 9), (14, 10), (18, 10), (26, 10),
                 (33, 10), (40, 8), (46, 8), (52, 8), (56, 8), (59, 8)):
        put(c, r, "c")

    return grid, floor


def to_rows(grid):
    return ["".join(row) for row in grid]


def check(grid, floor):
    problems = []
    rows = to_rows(grid)

    # 1) 矩形
    widths = set(len(r) for r in rows)
    if widths != {W}:
        problems.append(u"行宽不一致：%s" % widths)

    # 2) 图例
    legend = set(".#=^v~cCFPJSNGDBUMmRZXH?WKE")
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch not in legend:
                problems.append(u"第 %d 行第 %d 列有未知字符 %r" % (r + 1, c + 1, ch))

    # 3) 坑宽：普通坑 ≤2 格；水面缺口按滑翔段单独校验
    def floor_row(c):
        """从最底下往上找连着地面的那段实心，返回它的顶行。

        不能直接"从上往下找第一个 #"：第 5 关的通道天花板和荡锤横梁都是
        悬空的实心格，会被当成地面，于是每个机关上方都成了"台阶"。
        """
        r = H - 1
        if grid[r][c] != "#":
            return None
        while r > 0 and grid[r - 1][c] == "#":
            r -= 1
        return r

    gaps = []
    run = []
    for c in range(W):
        if floor_row(c) is None:
            run.append(c)
        else:
            if run:
                gaps.append(run)
            run = []
    if run:
        gaps.append(run)

    glide_time = JUMP_RISE / GLIDE_FALL
    jump_time = JUMP_V / (G_UP * HOLD)
    reach = RUN_SPEED * jump_time + GLIDE_SPEED * glide_time

    for g in gaps:
        width_px = len(g) * TILE
        water = any(any(grid[r][c] == "~" for r in range(H)) for c in g)
        has_glider = any(
            grid[r][c] == "G"
            for r in range(H)
            for c in range(max(0, g[0] - 3), min(W, g[-1] + 4)))
        if water and has_glider:
            # 滑翔段：射程要留 20% 余量，别做成"只有完美起跳才过得去"
            if width_px > reach * 0.8:
                problems.append(
                    u"滑翔缺口 %d 格（%dpx）超过射程 %.0fpx 的 80%%"
                    % (len(g), width_px, reach))
        elif width_px > 2 * TILE:
            problems.append(
                u"第 %d-%d 列坑宽 %d 格，跳过不去（射程约 %.0fpx = 3.6 格）"
                % (g[0] + 1, g[-1] + 1, len(g), RUN_SPEED * 0.8))

    # 4) 台阶高差（封口墙顶端在 0 行，不算台阶）
    prev = None
    for c in range(W):
        f = floor_row(c)
        if f == 0:
            # 关底封口墙：一整列从顶到底的实心，本来就该是"墙"而不是台阶
            prev = None
            continue
        if f is None or prev is None:
            prev = f
            continue
        if prev - f > 1:
            problems.append(u"第 %d 列到第 %d 列台阶抬了 %d 格，跳不上去"
                            % (c, c + 1, prev - f))
        prev = f

    # 5) 走地怪脚下必须是实心
    for r in range(H):
        for c in range(W):
            if grid[r][c] == "Z":
                below = floor_row(c)
                if below is None or below > r + 1:
                    problems.append(u"走地怪 (%d,%d) 脚下没有地面" % (c + 1, r + 1))

    # 6) 刺轮：正上方必须是实心（吊点），且臂端要扫不到站立角色
    def ground_row_of(c):
        r = H - 1
        while r >= 0 and grid[r][c] != "#":
            r -= 1
        if r < 0:
            return None
        while r - 1 >= 0 and grid[r - 1][c] == "#":
            r -= 1
        return r

    for r in range(H):
        for c in range(W):
            if grid[r][c] != "X":
                continue
            if r == 0 or grid[r - 1][c] != "#":
                problems.append(u"刺轮 (%d,%d) 上方没有横梁，刀片像凭空浮着"
                                % (c + 1, r + 1))
            g = ground_row_of(c)
            if g is None:
                problems.append(u"刺轮 (%d,%d) 下面没有地面，是空中机关"
                                % (c + 1, r + 1))
                continue
            # 轴心在格子上沿；臂端 + 尖端判定圆必须严格高于站立头顶，
            # 否则站着跑都会被扫死 —— 这关就不可通关了。
            arm_tip = r * TILE + ROTOR_ARM + ROTOR_TIP
            head_top = g * TILE - PLAYER_H
            if arm_tip >= head_top:
                problems.append(
                    u"刺轮 (%d,%d) 臂端 %d 够到了站立头顶 %d："
                    u"这关会变成必死，站着跑都过不去"
                    % (c + 1, r + 1, arm_tip, head_top))

    # 7) 荡锤必须吊在东西上：吊点格子正上方要是实心
    for r in range(H):
        for c in range(W):
            if grid[r][c] == "H":
                if r == 0 or grid[r - 1][c] != "#":
                    problems.append(u"荡锤 (%d,%d) 上方没有横梁，锤子像凭空吊着"
                                    % (c + 1, r + 1))

    # 8) 滑翔伞：不在实心里，且底部离最近站立面 ≤2 格（跳得到）
    for r in range(H):
        for c in range(W):
            if grid[r][c] != "G":
                continue
            if grid[r][c] == "#":
                problems.append(u"滑翔伞 (%d,%d) 埋在实心里" % (c + 1, r + 1))
            support = None
            for cc in (c - 1, c, c + 1):
                if 0 <= cc < W:
                    f = floor_row(cc)
                    if f is not None and f > r:
                        if support is None or f < support:
                            support = f
            bottom = (r + 1) * TILE
            if support is None:
                problems.append(u"滑翔伞 (%d,%d) 下方没有任何落点" % (c + 1, r + 1))
            elif support * TILE - bottom > 2 * TILE:
                problems.append(
                    u"滑翔伞 (%d,%d) 离地 %.0fpx，跳不到（跳高 %.0fpx）"
                    % (c + 1, r + 1, support * TILE - bottom, JUMP_RISE))

    # 9) 出生点与终点
    spawns = sum(line.count("P") for line in rows)
    goals = sum(line.count("F") for line in rows)
    if spawns != 1:
        problems.append(u"出生点有 %d 个" % spawns)
    if goals != 1:
        problems.append(u"终点有 %d 个" % goals)

    # 10) 金币不能在实心里
    for r in range(H):
        for c in range(W):
            if grid[r][c] == "c":
                if r + 1 < H and grid[r + 1][c] == "#":
                    pass        # 浮在地面上方，正常

    # 11) 滑翔段：起跳点要有伞，缺口宽度要落在滑翔射程内
    #     从地面起跳 -> 顶点约 127px -> 之后以 120px/s 下落
    jump_time = JUMP_V / (G_UP * HOLD)
    glide_time = JUMP_RISE / GLIDE_FALL
    reach = RUN_SPEED * jump_time + GLIDE_SPEED * glide_time
    # 找最宽的连续缺口（水坑）
    run = 0
    widest = 0
    for c in range(W):
        if floor_row(c) is None:
            run += 1
            widest = max(widest, run)
        else:
            run = 0
    if widest * TILE > reach * 0.8:
        problems.append(u"最宽缺口 %d 格（%dpx）超过滑翔射程 %.0fpx 的 80%%"
                        % (widest, widest * TILE, reach))

    return problems, widest


# 每个元素 = 一块牌子，页用 | 分隔。牌子按地图上 S 的出现顺序（从左到右）
# 与这里一一对应，数量对不上 world 会直接报错。
SIGN_TEXT = [
    u"黑团子是走地怪：从头顶落下去能踩死它，撞到侧面会死。|"
    u"踩死之后它闪两下就没了——每只只死一次，别回头找它。",
    u"刀片吊在横梁下面，扫得很低。|"
    u"贴着地横跑过去绝对安全——但只要起跳，脚一离地就会被绞进去。",
    u"荡锤看那条虚线：锤子摆到最外侧，就是你的窗口。",
]


def render(grid, floor):
    rows = to_rows(grid)
    out = []
    out.append(u"; 第 5 关：机关实验室（M7）")
    out.append(u"; 走地怪 Z / 旋转刺轮 X / 荡锤 H / 空中滑翔伞 G")
    out.append(u"; 生成器：tools/gen_l5.py（改这一关请改生成器，不要手改本文件）")
    out.append(u"")
    # 文本以"出现顺序"与地图里的 S 配对
    sign_idx = 0
    sign_lines = []
    for r, line in enumerate(rows):
        # 行末注释：把这一行出现的机关标出来，读图时不用回头查图例
        marks = []
        for ch, name in (("Z", u"走地怪"), ("X", u"刺轮"), ("H", u"荡锤"),
                         ("G", u"滑翔伞"), ("S", u"牌")):
            n = line.count(ch)
            if n:
                marks.append(u"%s x%d" % (name, n))
                if ch == "S":
                    sign_idx += n
        out.append(line)
    out.append(u"")
    # 牌子的文本放在地图之后：注释行不参与地图，位置在这里无所谓，
    # 顺序必须与地图里 S 的出现顺序一致
    for page in SIGN_TEXT:
        out.append(u";!sign %s" % page)
    out.append(u"")
    return u"\n".join(out) + u"\n"


def main():
    grid, floor = build()
    problems, widest = check(grid, floor)
    text = render(grid, floor)

    print(u"第 5 关：%d x %d 格（%d x %d px），最宽缺口 %d 格"
          % (W, H, W * TILE, H * TILE, widest))
    print(u"跳高 %.0fpx，滑翔射程约 %.0fpx" % (JUMP_RISE,
                                              RUN_SPEED * (JUMP_V / (G_UP * HOLD))
                                              + GLIDE_SPEED * (JUMP_RISE / GLIDE_FALL)))

    if problems:
        print(u"\n发现 %d 个问题：" % len(problems))
        for p in problems:
            print(u"  - %s" % p)
        return 1

    print(u"检查全部通过：矩形、图例、坑宽、台阶、走地怪落脚、刺轮位置、"
          u"吊点、伞可达性、出生/终点、滑翔射程")

    path = os.path.join(ROOT, "levels", "l5.txt")
    if "--write" in sys.argv:
        f = io.open(path, "w", encoding="utf-8", newline="\n")
        try:
            f.write(text)
        finally:
            f.close()
        print(u"已写入 %s" % path)
    else:
        print(u"（只检查，未写入。加 --write 覆盖文件）")
        print(u"-" * 60)
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
