# -*- coding: utf-8 -*-
"""生成第 4 关（机关综合关）：levels/l4.txt

这一关把 M6 的三样新东西按"先教一样、再叠一样"的顺序排开：

    0..7     起步平地，第 5 列一块告示牌（教"按 E 看牌子"）
    8..9     2 格水坑（热身）
    10..15   平地，第 12 列老人 NPC（讲蝙蝠和落石怎么看）
    16..17   台阶（抬 1 格）
    18..25   高台，头顶 1 只蝙蝠来回飞（第一课：绕/跳过去）
    26..27   高台上的 2 格水坑（掉下去就回篝火）
    28..33   落地高台，头顶蝙蝠 + 金币
    34..35   台阶（降 1 格）
    36..43   开裂天花板，3 处落石点（第二课：看地上的影子）
    44..45   2 格水坑
    46..59   终段：篝火、悬停 UFO、终点旗

文本（;!sign / ;!npc）与地图里的 S / N 按出现顺序配对，解析器会校验数量。

用法：python tools/gen_l4.py            # 打印并写文件
      python tools/gen_l4.py --check    # 只检查不写
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

W, H = 60, 14
GROUND = 11              # 主行走面所在行
PIT_W = 2                # 坑宽（格）：2 格 = 128px，普通跳跃（≈263px）够过

HEADER = u"""; 第 4 关 · 蝙蝠、落石与牌子
; 图例见 README §11.2。列宽必须一致，改地图请保持矩形。
;!sign 空格跳 / Shift 冲刺 / E 看牌子|前面有坑，掉下去会回到上一个篝火。
;!sign 天花板在开裂。|石头落下前，地上会先出现一圈影子，影子收拢就砸下来了——看到影子就挪开。
;!sign 那东西一直盯着你。|它只往你脚底下扔石头，看见影子收拢前跑出去就行。
;!npc 老人|小伙子，上面那些灰蝙蝠不会追你，只在自己那一段来回飞。|别在它贴地的时候硬挤，跳过去，或者等它飞开。|再往前是开裂的天花板，记住：先看影子，再想金币。
"""


def blank():
    return [["." for _ in range(W)] for _ in range(H)]


def fill(rows, c0, c1, r0, r1, ch="#"):
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            rows[r][c] = ch


def put(rows, c, r, ch):
    rows[r][c] = ch


def build():
    rows = blank()

    # ---- 地面：五段，中间夹三个坑 ----
    fill(rows, 0, 7, GROUND, H - 1)
    fill(rows, 10, 15, GROUND, H - 1)
    fill(rows, 28, 33, 9, H - 1)
    fill(rows, 36, 43, GROUND, H - 1)
    fill(rows, 46, W - 1, GROUND, H - 1)

    # ---- 两级台阶上高台（每级只抬 1 格）----
    fill(rows, 16, 17, 10, H - 1)
    fill(rows, 18, 25, 9, H - 1)
    # 下台阶
    fill(rows, 34, 35, 10, H - 1)

    # ---- 三个水坑 ----
    fill(rows, 8, 9, GROUND, H - 1, "~")
    fill(rows, 26, 27, 9, H - 1, "~")          # 高台上的坑
    fill(rows, 44, 45, GROUND, H - 1, "~")

    # ---- 开裂的天花板 ----
    # 一块悬在头顶的岩板，裂缝就在它底下。没有这块板子的话，
    # 石头看起来是"凭空从天上掉下来"，玩家不会把它和天花板联系到一起。
    fill(rows, 36, 43, 6, 7)
    for c in (37, 40, 43):
        put(rows, c, 8, "R")

    # ---- 右端封口墙 ----
    fill(rows, W - 1, W - 1, 6, GROUND - 1)

    # ---- 出生点 / 终点 / 篝火 ----
    put(rows, 2, GROUND - 1, "P")
    # 篝火放在**落石区之前**（第 34 列，下台阶的第一格），不是原来的第 46 列：
    # 落石是这关唯一"看一眼就得停"的机关，被砸死却要回到关卡起点重跑，
    # 惩罚太重、也太远——玩家会以为这关的难点是"跑得不够快"。
    # 放在开裂天花板入口前，试错的代价才是"再来一次这段"。
    put(rows, 34, 9, "C")
    put(rows, 56, GROUND - 1, "F")

    # ---- 告示牌与 NPC ----
    put(rows, 5, GROUND - 1, "S")
    put(rows, 12, GROUND - 1, "N")
    put(rows, 35, GROUND - 1, "S")     # 落石区入口
    put(rows, 47, GROUND - 1, "S")     # UFO 区

    # ---- 蝙蝠：两段巡逻线由连续的 B 决定 ----
    # 第一段在高台正上方 2 格：玩家站着不会被撞，跳起来才会——
    # 这是"别在这儿乱跳"的第一课。
    for c in range(19, 24):
        put(rows, c, 7, "B")
    # 第二段贴着地面高度：必须跳过去，或者等它飞远。
    for c in range(29, 33):
        put(rows, c, 8, "B")

    # ---- UFO ----
    put(rows, 51, 6, "U")

    # ---- 金币 ----
    for c, r in [(4, GROUND - 1), (8, 9), (13, GROUND - 1),
                 (20, 6), (24, 6), (30, 7), (31, 7),
                 (38, GROUND - 1), (41, GROUND - 1),
                 (48, GROUND - 1), (53, GROUND - 1)]:
        put(rows, c, r, "c")

    return rows


def render(rows):
    return HEADER + "\n".join("".join(r) for r in rows) + "\n"


def _cell(rows, c, r):
    if 0 <= c < W and 0 <= r < H:
        return rows[r][c]
    return " "


def check(rows):
    """硬约束检查。改一格就能立刻发现问题，不用等跑图才发现过不去。"""
    problems = []

    # 1) 坑宽：普通跳跃射程约 263px，1 格 64px 太送、3 格 192px 也行但没难度，
    #    统一 2 格（128px）——够有威胁，失手了也知道是自己起跳早了。
    def pit_widths(ch="~"):
        out = []
        for r in range(H):
            c = 0
            while c < W:
                if rows[r][c] != ch:
                    c += 1
                    continue
                start = c
                while c < W and rows[r][c] == ch:
                    c += 1
                out.append((start, c - start, r))
        return out

    for start, width, r in pit_widths():
        if width > PIT_W:
            problems.append(u"第 %d 行 %d 列的水坑宽 %d 格，超过 %d 格"
                            % (r + 1, start + 1, width, PIT_W))

    # 2) 台阶高差：跳跃能上 121px，1 格 64px 稳，2 格 128px 跳不上去。
    #    只比较"落到地面的柱子"的顶面：悬空的天花板板子和右端封口墙也有
    #    顶面，但它们是屋顶/墙，不是台阶，混进来会天天误报。
    tops = {}
    for c in range(W):
        for r in range(H - 1, -1, -1):
            if rows[r][c] != "#":
                tops.pop(c, None)
                break
        for r in range(H):
            if rows[r][c] == "#" and all(rows[rr][c] == "#"
                                         for rr in range(r, H)):
                tops[c] = r
                break
    walkable = (9, 10, GROUND)
    for c in range(W - 1):
        a, b = tops.get(c), tops.get(c + 1)
        if a is None or b is None:
            continue
        if a not in walkable or b not in walkable:
            continue
        if a - b > 1:
            problems.append(u"第 %d 列到第 %d 列台阶抬了 %d 格，跳不上去"
                            % (c + 1, c + 2, a - b))

    # 3) 蝙蝠必须飞在空气里，且巡逻段左右 1 格也要是空气
    for r in range(H):
        for c in range(W):
            if rows[r][c] == "B":
                for dc in (-1, 0, 1):
                    if _cell(rows, c + dc, r) == "#":
                        problems.append(u"(%d,%d) 的蝙蝠会撞墙" % (c, r))

    # 4) 牌子/NPC 要站在地面上，且上方有 2 格空间
    for ch, name in (("S", u"告示牌"), ("N", u"NPC")):
        for r in range(H):
            for c in range(W):
                if rows[r][c] != ch:
                    continue
                below = _cell(rows, c, r + 1)
                if below != "#":
                    problems.append(u"(%d,%d) 的%s脚下不是地面（是 %r）"
                                    % (c, r, name, below))
                if _cell(rows, c, r - 1) != ".":
                    problems.append(u"(%d,%d) 的%s头顶被挡住" % (c, r, name))

    # 5) 落石点上方必须是实心天花板，下方要能落到地面
    for r in range(H):
        for c in range(W):
            if rows[r][c] != "R":
                continue
            if _cell(rows, c, r - 1) != "#":
                problems.append(u"(%d,%d) 的落石点上方没有天花板" % (c, r))
            if all(_cell(rows, c, rr) != "#" for rr in range(r + 1, H)):
                problems.append(u"(%d,%d) 的落石点下方没有地面" % (c, r))

    # 6) 出生点/终点/篝火必须在地面上
    for ch, name in (("P", u"出生点"), ("F", u"终点"), ("C", u"篝火")):
        hits = [(c, r) for r in range(H) for c in range(W) if rows[r][c] == ch]
        if not hits:
            problems.append(u"缺少%s %s" % (name, ch))
        for c, r in hits:
            if _cell(rows, c, r + 1) != "#":
                problems.append(u"(%d,%d) 的%s脚下是空的" % (c, r, name))

    # 7) 文本条数与牌子数量必须一一对应（解析器也会查，这里先查一遍，
    #    免得生成完才发现打不开）
    signs = sum(1 for r in rows for ch in r if ch == "S")
    npcs = sum(1 for r in rows for ch in r if ch == "N")
    n_sign = HEADER.count(u";!sign")
    n_npc = HEADER.count(u";!npc")
    if signs != n_sign:
        problems.append(u"牌子 %d 个，文本 %d 条" % (signs, n_sign))
    if npcs != n_npc:
        problems.append(u"NPC %d 个，文本 %d 条" % (npcs, n_npc))

    return problems


def main():
    rows = build()
    text = render(rows)

    lines = text.splitlines()
    map_lines = [l for l in lines if l and not l.startswith(";")]
    widths = set(len(l) for l in map_lines)
    print(u"地图 %d 行 x %d 列" % (len(map_lines), widths.pop()))

    problems = check(rows)
    for p in problems:
        print(u" [错误] %s" % p)

    if "--check" in sys.argv:
        return 1 if problems else 0

    out = os.path.join(config.LEVEL_DIR, "l4.txt")
    io.open(out, "w", encoding="utf-8", newline="\n").write(text)
    print(u" 写入：%s" % out)
    print("")
    for i, l in enumerate(lines):
        print(u"%2d |%s|" % (i + 1, l))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
