# -*- coding: utf-8 -*-
"""生成 levels/l2.txt（机关演示关）。

关卡里有位置约束（坑宽 ≤2 格、台阶 ≤1 格、平台行程 2 格），手写 12x56
的字符矩阵很容易错一格导致不可通。用脚本按"每列地面行 + 点状物件"描述，
再由脚本铺成字符矩阵，改一个数就能重新生成，也能顺便打印一遍核对。
"""

import os
import sys

W, H = 56, 12


def blank():
    return [["." for _ in range(W)] for _ in range(H)]


def fill(rows, col_from, col_to, row_from, row_to, ch="#"):
    for c in range(col_from, col_to + 1):
        for r in range(row_from, row_to + 1):
            rows[r][c] = ch


def put(rows, col, row, ch):
    rows[row][col] = ch


def build():
    rows = blank()

    # ---- 地面段（列区间, 顶行, 底行）----
    # 顶行 10 → 行走面 y=640；顶行 7 → 高位平台面 y=448
    # 高位平台写 7..8：只有两格厚的悬浮板，下面留空，玩家从底下穿过去
    ground = [
        (0, 7, 10, H - 1), (10, 18, 10, H - 1), (21, 24, 10, H - 1),
        (25, 30, 10, H - 1), (25, 30, 7, 8),      # 弹跳板上去的高台
        (31, 36, 10, H - 1), (42, 52, 10, H - 1),
        (46, 50, 7, 8),                           # 升降台上去的藏币台
        (53, 55, 9, H - 1),                       # 终点前抬高一格
    ]
    for c0, c1, top, bottom in ground:
        fill(rows, c0, c1, top, bottom)

    # ---- 水坑（掉下去就死，视觉上也说明"这里不能踩"）----
    fill(rows, 8, 9, 10, H - 1, "~")
    fill(rows, 19, 20, 10, H - 1, "~")
    # 37-41 是 5 格宽的坑，跳不过去，只能坐移动平台。
    # 这里的水只铺最底下一行：平台在 row 10，水面低一行才不会和平台判定打架。
    fill(rows, 37, 41, H - 1, H - 1, "~")


    # ---- 出生点与终点 ----
    put(rows, 2, 9, "P")
    put(rows, 54, 8, "F")

    # ---- 篝火 ----
    put(rows, 11, 9, "C")
    put(rows, 43, 9, "C")

    # ---- 单向平台：架在地刺上方的薄板，演示"从下能穿、从上方能站"----
    fill(rows, 13, 15, 9, 9, "=")

    # ---- 地刺 ----
    put(rows, 17, 9, "^")

    # ---- 弹跳板（col 23 在地面上，往右上弹到 col 25 的高台）----
    put(rows, 23, 9, "J")

    # ---- 水平移动平台：4 格坑的摆渡 ----
    # 平台写成 3 格：1 格缺口留给助跑起跳，后面 2 格是落点缓冲。
    # 2 格宽时"从岸边起跳"正好落在平台左缘，差 9px 就掉坑，太吃操作。
    fill(rows, 38, 40, 10, 10, "M")

    # ---- 垂直移动平台：从地面升到藏币台 ----
    put(rows, 45, 9, "m")

    # ---- 金币 ----
    # 高度分三档：
    #   row 9（贴地）、row 8（离地 96px）：跑着跳就吃得到，顺路；
    #   row 7（离地 160px）：要"人正好在金币正下方、原地满跳"才碰得到，
    #                        属于**支线**奖励（实测可吃，但别指望跑动中顺带捞）；
    #   row 6（高台顶上）：靠弹跳板 / 升降台上高台才吃得到。
    # 也就是说这关的金币不全是必经路径上的——12 枚里有一半要特意去拿，
    # 这是有意的收集目标，不是"画在拿不到的地方"。
    for c, r in [(3, 8), (5, 8), (10, 8), (12, 7), (22, 7),
                 (26, 6), (28, 6), (38, 9), (40, 9),
                 (47, 6), (48, 6), (49, 6)]:
        put(rows, c, r, "c")

    return rows


HEADER = [
    "; 第二关 · 机关试炼（M4）",
    "; 目的：把 M4 的四类机关摆在一关里，方便一次走完验证。",
    ";   坑宽最多 2 格（跨越约 2.9 格）；台阶高最多 1 格（跳高约 121px）。",
    ";   J 弹跳板：踩上去弹起约 3.9 格，用来上 2 格以上的高台。",
    ";   M 水平平台 / m 升降平台：行程都是 2 格，站上去会被带着走。",
    ";   = 单向平台：从下往上能穿过，从上面落下才站得住。",
    ";   ^ 地刺 / ~ 水：碰到就死，回到最近点亮的篝火。",
    "",
]


def main():
    rows = build()
    lines = [u"".join(r) for r in rows]
    width = set(len(s) for s in lines)
    if width != {W}:
        print(u"行宽不一致：%s" % sorted(width))
        return 1
    text = u"\n".join(HEADER + lines) + u"\n"

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "levels", "l2.txt")
    with open(out, "wb") as f:
        f.write(text.encode("utf-8"))
    print(u"已写入 %s（%d 列 x %d 行）" % (out, W, H))

    # 打印列号标尺，方便人工核对每个机关落在第几列
    print("    " + "".join(str(c // 10 % 10) for c in range(W)))
    print("    " + "".join(str(c % 10) for c in range(W)))
    for i, line in enumerate(lines):
        print("%2d  %s" % (i, line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
