# -*- coding: utf-8 -*-
"""生成第 3 关（滑翔伞关）：levels/l3.txt

手写 54x13 的文本关卡太容易错列，这里用脚本按格子填，改完重新生成。
本关只教一件事：**拿到伞，空中按住空格，飘过大坑**。

关卡结构（从右往左读）：
    0..17   起步平地，第 4 列放滑翔伞
    12..20  四级台阶，最高一层是起跳台（顶面 y=384）
    21..28  8 格宽的水坑，普通跳跃（约 263px）够不到对岸（512px）
    29..42  对岸平台，第 31 列篝火
    43..44  2 格小水坑，普通跳跃就能过（和前面的大坑形成对比）
    45..53  终点段

用法：python tools/gen_l3.py            # 打印到屏幕并写文件
      python tools/gen_l3.py --check    # 只检查不写
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

W, H = 54, 13
GROUND_TOP = 10          # 行走面所在行（顶面 y = 640）
LAUNCH_TOP = 6           # 起跳台顶面行（y = 384）

HEADER = u"""; 第 3 关 · 滑翔伞
; 图例见 README §11.2。列宽必须一致，改地图请保持矩形。
"""


def blank():
    return [["." for _ in range(W)] for _ in range(H)]


def fill(rows, c0, c1, r0, r1, ch="#"):
    """按列区间 [c0, c1]、行区间 [r0, r1] 填充（闭区间）。"""
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            rows[r][c] = ch


def put(rows, c, r, ch):
    rows[r][c] = ch


def build():
    rows = blank()

    # ---- 地面：三段平地，中间各夹一个坑 ----
    fill(rows, 0, 17, GROUND_TOP, H - 1)
    fill(rows, 29, 42, GROUND_TOP, H - 1)
    fill(rows, 45, W - 1, GROUND_TOP, H - 1)

    # ---- 四级台阶 -> 起跳台 ----
    # 每级只抬 1 格（64px），而跳跃能上 121px，所以每一级都跳得上去；
    # 抬 2 格（128px）就跳不上去了——这是 README §5 里的硬约束。
    fill(rows, 12, 13, 9, H - 1)
    fill(rows, 14, 15, 8, H - 1)
    fill(rows, 16, 17, 7, H - 1)
    fill(rows, 18, 20, LAUNCH_TOP, H - 1)

    # ---- 8 格宽的大坑（水）----
    # 512px：普通跳跃的水平射程约 263px，差得远；滑翔从 384 落到 640
    # 有 2.1 秒，按 330px/s 能飞 700px，够过。
    fill(rows, 21, 28, GROUND_TOP, H - 1, "~")
    # 小坑：只有 2 格（128px），正常跳就能过，用来对比"大坑必须滑翔"
    fill(rows, 43, 44, GROUND_TOP, H - 1, "~")

    # ---- 右端封口墙 ----
    # 终点之后留一段地再断崖：不封口的话，一路蹦着跑的玩家会从旗子头顶
    # 飞过去、一路跑到地图外掉死（实测发生在 x=4249，超过地图右边界）。
    fill(rows, W - 1, W - 1, 6, GROUND_TOP - 1)

    # ---- 出生点 / 道具 / 篝火 / 终点 ----
    put(rows, 2, 9, "P")
    put(rows, 4, 9, "G")        # 滑翔伞，就在出生点前面，不会漏
    put(rows, 31, 9, "C")
    put(rows, 50, 9, "F")

    # ---- 金币 ----
    # 前四枚在台阶上，自然引导玩家往上走；19,4 是跳起来才够得到的
    # （站着的头顶在 314，金帀中心 288，不跳吃不到）
    #
    # 最后一枚**不能放在终点旗右边**：一脚踩进终点判定区，关卡就结算定格了，
    # 旗子后面的金币永远拿不到（试玩实测：跑到终点只拿到 8/9）。
    # 所以终点段的两枚都压在旗子左边，靠小水坑当节奏点。
    for c, r in [(8, 9), (10, 9), (13, 8), (15, 7), (19, 4),
                 (32, 9), (36, 9), (47, 9), (48, 9)]:
        put(rows, c, r, "c")

    return rows


def render(rows):
    return HEADER + "\n".join("".join(r) for r in rows) + "\n"


def check(rows):
    """几条硬约束，写错一格就能立刻发现。"""
    problems = []

    # 1) 坑宽必须让普通跳跃过不去、滑翔过得去
    glide_need = (29 - 21) * config.TILE          # 起跳边缘到对岸的像素距离
    drop = (GROUND_TOP - LAUNCH_TOP) * config.TILE
    glide_time = drop / config.GLIDE_FALL_SPEED
    glide_reach = glide_time * config.GLIDE_RUN_SPEED
    if glide_reach <= glide_need + 60:
        problems.append(u"滑翔余量不足：需要 %dpx，只能飞 %.0fpx"
                        % (glide_need, glide_reach))
    jump_reach = 263.0                             # M3 实测的普通跳跃射程
    if jump_reach >= glide_need:
        problems.append(u"大坑只有 %dpx，普通跳跃就过得去，失去教学意义"
                        % glide_need)

    # 2) 台阶每级只能抬 1 格
    prev = GROUND_TOP
    for top in (9, 8, 7, LAUNCH_TOP):
        if prev - top != 1:
            problems.append(u"台阶高度差 %d 格，必须正好 1 格" % (prev - top))
        prev = top

    # 3) 道具/出生点/篝火/终点不能被实心盖住，且必须在坑外
    for ch in ("P", "G", "C", "F"):
        hits = [(c, r) for r in range(H) for c in range(W) if rows[r][c] == ch]
        if not hits:
            problems.append(u"缺少 %s" % ch)
        for c, r in hits:
            if rows[r][c] == "#":
                problems.append(u"(%d,%d) 的 %s 被实心覆盖" % (c, r, ch))

    # 4) 金币不能埋在实心里
    for r in range(H):
        for c in range(W):
            if rows[r][c] == "c" and rows[r][c] == "#":
                problems.append(u"(%d,%d) 的金币在实心里" % (c, r))

    # 5) 金币不能落在终点旗的右边（含同一列）
    #    终点判定区一到就结算定格，旗子后面的金币是永远拿不到的：
    #    玩家会以为自己操作不够，其实是关卡画错了。
    flag_cols = [c for r in range(H) for c in range(W) if rows[r][c] == "F"]
    if flag_cols:
        goal_x = min(flag_cols) * config.TILE
        for r in range(H):
            for c in range(W):
                if rows[r][c] == "c" and c * config.TILE >= goal_x:
                    problems.append(u"(%d,%d) 的金币在终点（第 %d 列）右边或同一列"
                                    % (c, r, min(flag_cols)))

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

    out = os.path.join(config.LEVEL_DIR, "l3.txt")
    io.open(out, "w", encoding="utf-8", newline="\n").write(text)
    print(u" 写入：%s" % out)
    print("")
    for i, l in enumerate(lines):
        print(u"%2d |%s|" % (i + 1, l))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
