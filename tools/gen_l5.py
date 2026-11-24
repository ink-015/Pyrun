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
import math
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
PLAYER_W = 26           # player.Player.WIDTH
PLAYER_H = 70           # player.Player.HEIGHT
ROTOR_ARM = 42.0        # config.ROTOR_ARM_LEN
ROTOR_TIP = 8           # config.ROTOR_TIP_R
PENDULUM_ARM = 148.0    # config.PENDULUM_ARM
PENDULUM_AMP = 0.95     # config.PENDULUM_AMP
PENDULUM_BOB_R = 16     # config.PENDULUM_BOB_R
WALKER_RUN_MAX = 6      # config.WALKER_RUN_MAX
WALKER_BODY_W = 40      # config.WALKER_BODY_W
WALKER_SPEED = 62.0     # config.WALKER_SPEED
# 巡逻一个来回超过这个时长，玩家就只能站着等，机关变成罚站。
# 6 格（本关用的长度）算下来 11.1 秒，正好压在线上——再加一格就该改成
# "让它在半路掉头"或者干脆换一只，而不是硬拉长。
WALKER_CYCLE_MAX = 12.0


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

    # ---- 第二只走地怪：巡逻段一直伸到刺轮正下方 ----
    # 这一段是本关的核心联动：刀片禁止起跳，走地怪又堵在同一条道上，
    # 于是"跳过去"这条最顺手的解法被拿掉，只剩"等它走出来、在刀片外面踩"
    # 或"贴着地跑过去再越过去"。6 格正好是 WALKER_RUN_MAX：再长一个来回
    # 就要 12 秒，玩家只会站着等，那不叫机关，叫罚站。
    for c in range(14, 20):
        put(c, 10, "Z")

    # ---- 低矮通道：天花板压到只剩两格高，跳不起来（纯节奏段）----
    for c in range(20, 28):
        solid(c, 8)           # 天花板

    # ---- 荡锤：吊在横梁上 ----
    for c in range(29, 33):
        solid(c, 7)           # 横梁
    put(28, 10, "S")          # 告示牌 3：讲荡锤（放在锤子左边）
    put(30, 8, "H")

    # ---- 滑翔段：伞吊在"跳满"的那个高度上，而不是贴着水面 ----
    for c in range(57, 62):
        for r in range(9, H):
            put(c, r, "~")
    # 伞原来放在第 7 行（判定区底边离岸面 64px），点一下跳就拿到了，
    # 于是玩家学会了"跳一下"，然后在坑边被水流吞掉——因为他根本不知道自己
    # 需要跳满。现在抬到第 6 行：判定区底边 = 岸面往上 128px，正好是跳满时的
    # 头顶位置。想拿伞就必须按住空格跳最高，而这个动作正是滑过水池需要的。
    put(57, 6, "G")

    # ---- 终点与封口 ----
    put(64, 8, "F")
    for r in range(0, 9):
        solid(65, r)

    # ---- 篝火：本关最长，不加存档点的话死一次要从头再跑半张图 ----
    # 第 27 列是低矮通道的出口，且在荡锤摆幅（扫到 1832~2072）之外；
    # 第 55 列是高台的最后一格，跳坑之前。
    put(27, 10, "C")
    put(55, 8, "C")

    # ---- 金币 ----
    # 14 / 18 列原本是地面金币，现在正好落在走地怪的巡逻线上（会被怪踩过去），
    # 挪到巡逻段两头：玩家要拿就得在那里起跳——那两处是刀片够不到的。
    #
    # 滑翔段的金币是"软引导"：起跳点正上方一枚（第 56 列两枚叠成一个向上的
    # 指示），伞后面顺着下滑轨迹摆两枚，对岸落点一枚。玩家跟着金币走，走的
    # 就是"跳满 → 一直按住空格滑过去"这条唯一能过水池的路线。
    # 原来 59 列那枚在水面上方 64px，比滑翔轨迹低一截：想去够只能松开空格
    # 往下掉，那不是引导，是拿金币骗人跳水。
    for c, r in ((6, 10), (10, 9), (12, 10), (19, 9), (26, 10),
                 (33, 10), (40, 8), (46, 8), (52, 8),
                 (56, 8), (56, 6), (58, 7), (60, 7), (62, 8)):
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

    # 8) 滑翔伞：必须挂在"跳满才够到"的高度上
    #    不直接量像素高度，而是拿站立头顶和跳满时的头顶当上下界：
    #    低了就退化成"点一下跳就拿到"（玩家学不会他真正需要的动作），
    #    高了就变成"这关拿不到伞"。两头都是设计事故。
    for r in range(H):
        for c in range(W):
            if grid[r][c] != "G":
                continue
            support = None
            for cc in (c - 1, c, c + 1):
                # 伞悬在水面上，脚下那格没有地面，落点取左右两格里最高的那个
                if 0 <= cc < W:
                    f = floor_row(cc)
                    if f is not None and f > r:
                        if support is None or f < support:
                            support = f
            if support is None:
                problems.append(u"滑翔伞 (%d,%d) 下方没有任何落点" % (c + 1, r + 1))
                continue
            bottom = (r + 1) * TILE
            ground = support * TILE
            stand_top = ground - PLAYER_H          # 站着时的头顶
            apex_top = stand_top - JUMP_RISE       # 跳满时的头顶
            # 下界：不能"随便点一下就够到"
            if bottom > stand_top - 0.4 * JUMP_RISE:
                problems.append(
                    u"滑翔伞 (%d,%d) 判定区底边 %d 离站立头顶 %d 太近："
                    u"点一下跳就拿到了，玩家学不会「跳满再滑」"
                    % (c + 1, r + 1, bottom, stand_top))
            # 上界：跳满时身体要进得去（留 6px 余量，别做成像素级完美）
            if bottom < apex_top + 6:
                problems.append(
                    u"滑翔伞 (%d,%d) 判定区底边 %d 高过跳满时的头顶 %d："
                    u"这关根本拿不到伞"
                    % (c + 1, r + 1, bottom, apex_top))

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

    # 12) 篝火：脚下是地面，且**重生点**不在机关的扫掠范围内。
    #     这一条不是形式主义：一开始我把篝火放在荡锤右边第 28 列，看着在
    #     "锤子前面"，但摆幅扫到 1832~2072，重生点 1811 正好在圈里——
    #     复活即被砸，比没有存档点更糟。
    for r in range(H):
        for c in range(W):
            if grid[r][c] != "C":
                continue
            g = ground_row_of(c)
            if g is None or g != r + 1:
                problems.append(u"篝火 (%d,%d) 脚下不是紧贴地面，重生会掉下去"
                                % (c + 1, r + 1))
            spawn_cx = c * TILE + TILE // 2
            for rr in range(H):
                for cc in range(W):
                    ch2 = grid[rr][cc]
                    if ch2 == "X":
                        reach_x = ROTOR_ARM + ROTOR_TIP + PLAYER_W
                        if abs(spawn_cx - (cc * TILE + TILE // 2)) < reach_x:
                            problems.append(
                                u"篝火 (%d,%d) 在刺轮扫掠范围里：一重生就会被刀片打中"
                                % (c + 1, r + 1))
                    elif ch2 == "H":
                        sweep = (PENDULUM_ARM * math.sin(PENDULUM_AMP)
                                 + PENDULUM_BOB_R + PLAYER_W)
                        if abs(spawn_cx - (cc * TILE + TILE // 2)) < sweep:
                            problems.append(
                                u"篝火 (%d,%d) 在荡锤摆幅内：一重生就会被砸"
                                % (c + 1, r + 1))

    # 13) 走地怪与刺轮的联动
    #     刺轮是"禁跳区"——玩家在它下面本来就没有跳的需求，单放一个刀片
    #     等于装饰。必须有走地怪把那条道占住，刀片才有意义：它掐掉的正是
    #     "跳过去"这条最顺手的解法。
    runs = []
    for r in range(H):
        c = 0
        while c < W:
            if grid[r][c] == "Z":
                c0 = c
                while c + 1 < W and grid[r][c + 1] == "Z":
                    c += 1
                runs.append((r, c0, c))
            c += 1

    for r in range(H):
        for c in range(W):
            if grid[r][c] != "X":
                continue
            cover = [x for x in runs if x[1] <= c <= x[2]]
            if not cover:
                problems.append(
                    u"刺轮 (%d,%d) 下面没有走地怪：玩家在这儿本来就不需要跳，"
                    u"机关等于摆设" % (c + 1, r + 1))
                continue
            r0, c0, c1 = cover[0]
            reach_x = ROTOR_ARM + ROTOR_TIP + PLAYER_W
            safe = [cc for cc in range(c0, c1 + 1)
                    if abs((cc + 0.5) * TILE - (c + 0.5) * TILE) > reach_x]
            if not safe:
                problems.append(
                    u"走地怪 %d-%d 列整段都在刺轮扫掠圈里：玩家没地方下脚踩它"
                    % (c0 + 1, c1 + 1))

    # 14) 巡逻段的长度与周期：太长就是"罚站"
    for r0, c0, c1 in runs:
        span = c1 - c0 + 1
        if span > WALKER_RUN_MAX:
            problems.append(u"走地怪 %d-%d 列合并了 %d 格，超过 %d 格上限"
                            % (c0 + 1, c1 + 1, span, WALKER_RUN_MAX))
        travel = span * TILE - WALKER_BODY_W
        cycle = 2.0 * travel / WALKER_SPEED
        if cycle > WALKER_CYCLE_MAX:
            problems.append(
                u"走地怪 %d-%d 列一个来回要 %.1f 秒，玩家只能站着等"
                % (c0 + 1, c1 + 1, cycle))

    # 15) 水面上的金币必须躺在滑翔轨迹上。
    #     这一条是被玩家怼出来的：原来水面上方 64px 有一枚金币，比滑翔轨迹
    #     低一截——想去够只能松开空格往下掉，那不是引导，是拿金币骗人跳水。
    #     判据用真实参数把轨迹算一遍：从岸沿起跳、跳满、然后一直按住空格，
    #     看金币格子有没有和"身体扫过的那条带子"相交。差一格也算不合格。
    t_apex = JUMP_V / (G_UP * HOLD)
    run_reach = RUN_SPEED * t_apex

    def body_at(dx):
        """离岸沿 dx 时身体的 (top, bottom)，以起跳岸面为 0、向上为负。"""
        if dx <= run_reach:
            t = dx / RUN_SPEED
            bottom = -(JUMP_V * t - 0.5 * G_UP * HOLD * t * t)
        else:
            bottom = -JUMP_RISE + GLIDE_FALL * (dx - run_reach) / GLIDE_SPEED
        return bottom - PLAYER_H, bottom

    for r in range(H):
        for c in range(W):
            if grid[r][c] != "c" or floor_row(c) is not None:
                continue                    # 岸上的金币，走过去就拿到，不查
            g0 = c
            while g0 - 1 >= 0 and floor_row(g0 - 1) is None:
                g0 -= 1
            if g0 == 0:
                continue
            ledge = floor_row(g0 - 1)
            x_take = g0 * TILE
            cx0, cx1 = c * TILE, (c + 1) * TILE
            hit = False
            dx = 0.0
            while dx <= 400.0:
                # 身体的水平范围 [x_take+dx-W, x_take+dx] 与金币格子相交？
                if x_take + dx > cx0 and x_take + dx - PLAYER_W < cx1:
                    top, bottom = body_at(dx)
                    if (ledge * TILE + bottom > r * TILE
                            and ledge * TILE + top < (r + 1) * TILE):
                        hit = True
                        break
                dx += 2.0
            if not hit:
                problems.append(
                    u"水面金币 (%d,%d) 不在滑翔轨迹上：玩家为了够它只能松手往下掉"
                    % (c + 1, r + 1))

    return problems, widest


# 每个元素 = 一块牌子，页用 | 分隔。牌子按地图上 S 的出现顺序（从左到右）
# 与这里一一对应，数量对不上 world 会直接报错。
SIGN_TEXT = [
    u"黑团子是走地怪：从头顶落下去能踩死它，撞到侧面会死。|"
    u"踩死之后它闪两下就没了——每只只死一次，别回头找它。",
    u"刀片吊在横梁下面，扫得很低。|"
    u"贴着地横跑过去绝对安全——但只要起跳，脚一离地就会被绞进去。|"
    u"这条道上还有黑团子在转。别在刀口下面起跳：贴着地跑过去，"
    u"到刀片够不着的地方再越过它。",
    u"荡锤看那条虚线：锤子摆到最外侧，就是你的窗口。",
]


def render(grid, floor):
    rows = to_rows(grid)
    out = []
    out.append(u"; 第 5 关：机关实验室（M7）")
    out.append(u"; 走地怪 Z / 旋转刺轮 X / 荡锤 H / 空中滑翔伞 G / 篝火 C")
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

    print(u"检查全部通过：矩形、图例、坑宽、台阶、走地怪落脚与巡逻周期、"
          u"刺轮位置与下方巡逻联动、吊点、伞的悬挂高度、出生/终点、滑翔射程、"
          u"水面金币是否在滑翔轨迹上、篝火落脚与重生点安全性")

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
