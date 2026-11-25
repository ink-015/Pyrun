# -*- coding: utf-8 -*-
"""生成第 6 关「暗算」并做硬性检查。

这一关只有四种机关，但它们互相矛盾：伪装砖和落刺要求**别停**，
突墙要求**必须停**，二连石要求**看影子**。矛盾是刻意的——玩家不能
一路按住右键，也不能一路站着等，只能读路。

每一处机关都必须有"触发之前就已经在画面上"的线索（README §6.3），
所以这里的检查大半是在查线索有没有被地形吃掉：落刺上方没天花板、
二连石的远处那块没有裂缝、篝火重生点正好落在某根刺的触发圈里……

用法：python tools/gen_l6.py [--write]
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

W, H = 72, 14
TILE = 64
FLOOR = 11              # 本关地面统一在 11 行（第 11 行及其下面是实心）

# 跳跃射程（与 config.py 同源，这里不 import，避免拉起 pygame）
JUMP_V = 640.0
G_UP = 1900.0
HOLD = 0.85
JUMP_RISE = JUMP_V * JUMP_V / (2 * G_UP * HOLD)      # ≈127px
RUN_SPEED = 300.0
PLAYER_W = 26
PLAYER_H = 70

# 机关参数（与 config.py 同步）
BRICK_CRACK_TIME = 0.30
BRICK_RUN_MAX = 8
SPIKE_WARN = 0.45
SPIKE_FALL_SPEED = 1300.0
SPIKE_TRIGGER = 102.0
SPIKE_HALF_W = 14
WALL_H = 140
WALL_TRIGGER = 128.0
WALL_THICK = 24
TWIN_GAP = 128
TWIN_TRIGGER = 166.0


def build():
    grid = [["."] * W for _ in range(H)]

    def solid(c, r):
        grid[r][c] = "#"

    def put(c, r, ch):
        grid[r][c] = ch

    # ---- 地面：本关几乎全平，机关靠"上面"和"下面"做文章 ----
    for c in range(W):
        for r in range(FLOOR, H):
            solid(c, r)

    # ---- 出生点 ----
    put(2, FLOOR - 1, "P")

    # ---- 第 1 段：伪装砖（4 格），下面是刺 ----
    # 4 格是"教学长度"：第一次见的人多半会犹豫半秒，这个长度犹豫也来得及
    # 把脚收回来，但站着不动一定掉下去。
    put(6, FLOOR - 1, "S")
    for c in range(7, 11):
        put(c, FLOOR, "?")
    for c in range(7, 11):
        for r in range(FLOOR + 1, H):
            grid[r][c] = "."
        put(c, H - 1, "^")

    # ---- 第 2 段：天花板落刺走廊（3 根）----
    put(14, FLOOR - 1, "C")
    put(15, FLOOR - 1, "S")
    for c in range(15, 28):
        solid(c, 8)
    for c in (18, 21, 24):
        put(c, 9, "W")

    # ---- 第 3 段：突墙 ----
    # 刺廊出口先给一个篝火：这一关死得快，重生点必须密（README §6.3）。
    put(28, FLOOR - 1, "C")
    put(31, FLOOR - 1, "S")
    put(35, FLOOR - 1, "!")

    # ---- 第 4 段：二连落石 ----
    put(39, FLOOR - 1, "S")
    for c in range(38, 48):
        solid(c, 6)
    put(42, 7, "T")

    # ---- 第 5 段：伪装砖长桥（7 格），下面整段是水 ----
    put(47, FLOOR - 1, "C")
    for c in range(48, 55):
        put(c, FLOOR, "?")
    for c in range(48, 55):
        for r in range(FLOOR + 1, H):
            put(c, r, "~")

    # ---- 终点与封口 ----
    put(65, FLOOR - 1, "F")
    for r in range(0, FLOOR + 1):
        solid(71, r)

    # ---- 金币 ----
    # 二连石中间那两枚是"安全位置的坐标"：想拿就得站进两块影子中间，
    # 而那正是唯一躲得开的站法。用金币指路，比写一句"站中间"有效。
    for c, r in ((4, FLOOR - 1), (8, FLOOR - 1), (9, FLOOR - 1),
                 (12, FLOOR - 1), (17, FLOOR - 1), (20, FLOOR - 1),
                 (23, FLOOR - 1), (26, FLOOR - 1), (30, FLOOR - 1),
                 (34, FLOOR - 1), (37, FLOOR - 1),
                 (43, FLOOR - 1), (43, FLOOR - 2),
                 (49, FLOOR - 1), (51, FLOOR - 1), (53, FLOOR - 1),
                 (58, FLOOR - 1), (62, FLOOR - 1)):
        put(c, r, "c")

    return grid


def to_rows(grid):
    return ["".join(row) for row in grid]


# ---------------------------------------------------------------- 检查

def check(grid):
    problems = []
    rows = to_rows(grid)

    # 1) 矩形
    widths = set(len(r) for r in rows)
    if widths != {W}:
        problems.append(u"行宽不一致：%s" % widths)

    # 2) 图例
    legend = set(".#=^v~cCFPJSNGDBUMmRZXH?W!TKE")
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch not in legend:
                problems.append(u"第 %d 行第 %d 列有未知字符 %r" % (r + 1, c + 1, ch))

    # 3) 出生点 / 终点各一个
    for ch, name in (("P", u"出生点"), ("F", u"终点")):
        n = sum(line.count(ch) for line in rows)
        if n != 1:
            problems.append(u"%s 应该有 1 个，实际 %d 个" % (name, n))

    # 4) 每列的"可行走面"：本关只有三种——实心地面 / 伪装砖 / 什么都没有
    def surface_row(c):
        for r in range(H):
            if grid[r][c] == "#":
                # 只看贴着地面的那段，悬空横梁不算
                if r == FLOOR:
                    return r
                continue
            if grid[r][c] == "?":
                return r
        return None

    surfaces = [surface_row(c) for c in range(W)]
    for c, s in enumerate(surfaces):
        if s is None:
            left = surfaces[c - 1] if c > 0 else None
            right = surfaces[c + 1] if c < W - 1 else None
            if left is not None and right is not None and c not in (W - 1,):
                problems.append(u"第 %d 列是一格孤立深坑" % (c + 1))

    # 5) 伪装砖
    def is_solid_floor(c):
        return 0 <= c < W and grid[FLOOR][c] == "#"

    runs = []
    run = []
    for c in range(W):
        if grid[FLOOR][c] == "?":
            run.append(c)
        else:
            if run:
                runs.append(run)
            run = []
    if run:
        runs.append(run)

    if not runs:
        problems.append(u"没有任何伪装砖：这一关的核心机关缺席")
    for g in runs:
        if len(g) > BRICK_RUN_MAX:
            problems.append(u"伪装砖 %d-%d 列共 %d 格，超过 %d 格上限"
                            % (g[0] + 1, g[-1] + 1, len(g), BRICK_RUN_MAX))
        if not is_solid_floor(g[0] - 1):
            problems.append(u"伪装砖 %d 列左边不是实心地面：进不去" % (g[0] + 1))
        if not is_solid_floor(g[-1] + 1):
            problems.append(u"伪装砖 %d 列右边不是实心地面：落不了地" % (g[-1] + 1))
        # 砖下面必须是空的：埋在土里的砖塌了也看不出，机关就白放了
        for c in g:
            if grid[FLOOR + 1][c] == "#":
                problems.append(u"伪装砖 %d 列下面是实心：它塌了也没意义" % (c + 1))
        # 掉下去得疼：两格内要有致死物，或者干脆掉出地图
        lethal = False
        for c in g:
            for r in range(FLOOR + 1, H):
                if grid[r][c] in ("^", "~"):
                    lethal = True
        if not lethal:
            problems.append(u"伪装砖 %d-%d 列下面没有刺也没有水：塌了也不疼"
                            % (g[0] + 1, g[-1] + 1))
    # 跑过一格的时间必须短于塌陷时间，否则"跑也来不及"
    if TILE / RUN_SPEED >= BRICK_CRACK_TIME:
        problems.append(u"跑过一格要 %.2f 秒，砖 %.2f 秒就塌：跑也来不及"
                        % (TILE / RUN_SPEED, BRICK_CRACK_TIME))

    # 6) 天花板落刺
    def floor_y_of(c):
        """这一列的地面高度（像素）。没有地面返回 None。"""
        s = surface_row(c)
        return None if s is None else s * TILE

    def ground_bottom(c):
        r = H - 1
        while r >= FLOOR:
            if grid[r][c] == "#":
                return r
            r -= 1
        return None

    spike_cols = []
    for r in range(H):
        for c in range(W):
            if grid[r][c] != "W":
                continue
            spike_cols.append(c)
            if r == 0 or grid[r - 1][c] != "#":
                problems.append(u"落刺 (%d,%d) 上方没有天花板，刺无处安放"
                                % (c + 1, r + 1))
            gy = floor_y_of(c)
            if gy is None:
                problems.append(u"落刺 (%d,%d) 下方没有地面：刺扎不到人，人会先掉下去"
                                % (c + 1, r + 1))
                continue
            clear = gy - r * TILE
            if clear < 2 * TILE:
                problems.append(u"落刺 (%d,%d) 净空只有 %dpx，刺还没加速就到了"
                                % (c + 1, r + 1, clear))
            # 通过性：从触发点跑到"整个人离开刺下方"要多久 vs 刺落地要多久
            t_cross = (SPIKE_TRIGGER + SPIKE_HALF_W + PLAYER_W) / RUN_SPEED
            t_land = SPIKE_WARN + (clear - 40) / SPIKE_FALL_SPEED
            if t_land < t_cross + 0.02:
                problems.append(
                    u"落刺 %d 列：全速跑过去要 %.2fs，刺 %.2fs 就落地——"
                    u"跑也躲不开（要么加预警，要么把刺挪高）"
                    % (c + 1, t_cross, t_land))
    for i in range(1, len(spike_cols)):
        gap = (spike_cols[i] - spike_cols[i - 1]) * TILE
        if gap < 2 * TILE:
            problems.append(u"落刺 %d 列和 %d 列挨得太近（%dpx）："
                            u"两枚一起下来，人夹在中间无处可躲"
                            % (spike_cols[i - 1] + 1, spike_cols[i] + 1, gap))

    # 7) 突墙
    for r in range(H):
        for c in range(W):
            if grid[r][c] != "!":
                continue
            if r + 1 >= H or grid[r + 1][c] != "#":
                problems.append(u"突墙 (%d,%d) 下面不是地面，墙是从哪儿长出来的"
                                % (c + 1, r + 1))
            if grid[r][c] == "#":
                problems.append(u"突墙 (%d,%d) 写在实心里" % (c + 1, r + 1))
            # 墙升起来要占 WALL_H 高度，上面必须是空的
            need = int(math.ceil(WALL_H / float(TILE))) + 1
            for k in range(1, need + 1):
                rr = r - k
                if rr < 0:
                    break
                if grid[rr][c] == "#":
                    problems.append(u"突墙 (%d,%d) 上方 %d 格有实心："
                                    u"墙升不起来" % (c + 1, r + 1, k))
                    break
            if WALL_H <= JUMP_RISE + 12:
                problems.append(u"突墙只有 %dpx，跳 %.0fpx 就过去了——"
                                u"那就不是机关，是个台阶" % (WALL_H, JUMP_RISE))

    # 8) 二连落石
    for r in range(H):
        for c in range(W):
            if grid[r][c] != "T":
                continue
            for dx, which in ((0, u"近"), (TWIN_GAP // TILE, u"远")):
                cc = c + dx
                if cc >= W:
                    problems.append(u"二连落石 (%d,%d) 的%s块跑出地图了"
                                    % (c + 1, r + 1, which))
                    continue
                if r == 0 or grid[r - 1][cc] != "#":
                    problems.append(u"二连落石 (%d,%d) 的%s块上方没有天花板："
                                    u"石头会凭空出现" % (c + 1, r + 1, which))
                if floor_y_of(cc) is None:
                    problems.append(u"二连落石 (%d,%d) 的%s块下面没有落点"
                                    % (c + 1, r + 1, which))
            # 中间那一格必须是能站人的地面，否则"站中间"这条解法不存在
            mid = c + TWIN_GAP // TILE // 2
            if floor_y_of(mid) is None:
                problems.append(u"二连落石 (%d,%d) 中间那格站不住人："
                                u"两块影子之间没有安全位，只能硬冲"
                                % (c + 1, r + 1))

    # 9) 篝火：站在地上，且重生点不在任何机关的"手边"
    def trap_zones():
        """[(中心 x, 半径, 名称)]：进入这个范围就会触发/被碰到的机关。"""
        out = []
        for r in range(H):
            for c in range(W):
                ch = grid[r][c]
                cx = c * TILE + TILE // 2
                if ch == "W":
                    out.append((cx, SPIKE_TRIGGER + TILE, u"落刺"))
                elif ch == "!":
                    out.append((cx, WALL_TRIGGER + TILE, u"突墙"))
                elif ch == "T":
                    out.append((cx + TILE, TWIN_TRIGGER + TILE, u"二连落石"))
                elif ch == "?":
                    # 半径只取半格：只有"重生点正好落在砖上"才算危险，
                    # 站在砖旁边（抬头就是桥）是正常位置。
                    out.append((cx, TILE // 2, u"伪装砖"))
        return out

    zones = trap_zones()
    for r in range(H):
        for c in range(W):
            if grid[r][c] != "C":
                continue
            if r + 1 >= H or grid[r + 1][c] != "#":
                problems.append(u"篝火 (%d,%d) 脚下不是地面" % (c + 1, r + 1))
            rx = c * TILE + (TILE - PLAYER_W) // 2
            for zx, zr, name in zones:
                if abs(rx + PLAYER_W // 2 - zx) <= zr:
                    problems.append(
                        u"篝火 %d 列重生点离%s %dpx：复活就落在机关手边"
                        % (c + 1, name,
                           abs(rx + PLAYER_W // 2 - zx)))

    # 10) 金币：不能埋在实心里，也不能悬在够不到的高度
    for r in range(H):
        for c in range(W):
            if grid[r][c] != "c":
                continue
            if r + 1 < H and grid[r + 1][c] == "#":
                continue
            # 悬空金币：脚下要有地面（伪装砖也算地面），且离地不超过跳高
            base = None
            for rr in range(r + 1, H):
                if grid[rr][c] in ("#", "?"):
                    base = rr
                    break
            if base is None:
                problems.append(u"金币 (%d,%d) 下面什么都没有" % (c + 1, r + 1))
            elif (base - r) * TILE - 70 > JUMP_RISE:
                problems.append(u"金币 (%d,%d) 离地 %d 格，跳不到"
                                % (c + 1, r + 1, base - r))

    # 11) 终点旗要立在地面上
    for r in range(H):
        for c in range(W):
            if grid[r][c] == "F" and (r + 1 >= H or grid[r + 1][c] != "#"):
                problems.append(u"终点旗 (%d,%d) 悬空" % (c + 1, r + 1))

    return problems


SIGNS = [
    u"这种地砖是空的：脚一踩就开始裂，半秒后就塌。|别停，一路跑过去——它塌得没你快。停下来看看风景，下面的刺可不等你。",
    u"头顶这三根刺是活的：你一走近它就抖，然后扎下来。|全速跑过去，它能擦着你的背落地；停在这条刺下面，就得挨一下。",
    u"地上那道槽里藏着一堵墙，人一近就顶出来。|两格多高，跳不过去——别抢，站着等它自己缩回去。|这关的规矩是反的：前面不许停，这里必须停。",
    u"这条横梁上有两道裂缝，一起掉石头。|远的那块影子收得更快：看见两道影子，就站到它们中间去——地上那两枚金币就是那个位置。",
]


def render(grid):
    rows = to_rows(grid)
    head = [
        u"; 第 6 关：「暗算」——四种「不能停 / 必须停」的机关（M8）",
        u"; 伪装砖 ? / 天花板落刺 W / 突墙 ! / 二连落石 T / 篝火 C",
        u"; 生成器：tools/gen_l6.py（改这一关请改生成器，不要手改本文件）",
        u";",
    ]
    for i, text in enumerate(SIGNS, 1):
        head.append(u";!sign " + text)
    head.append(u"")
    return u"\n".join(head + rows) + u"\n"


def main(argv):
    grid = build()
    problems = check(grid)
    if problems:
        print(u"检查未通过（%d 处）：" % len(problems))
        for p in problems:
            print(u"  ✗ " + p)
        return 1
    text = render(grid)
    print(u"检查全部通过：矩形、图例、出生/终点、伪装砖段与下方致死物、"
          u"落刺安装点与通过性、突墙净空与跳高、二连石天花板与安全位、"
          u"篝火重生点、金币可达性")
    print(u"尺寸 %dx%d 格（%dx%d px），伪装砖 %d 格，落刺 %d，突墙 %d，二连石 %d"
          % (W, H, W * TILE, H * TILE,
             sum(1 for r in range(H) for c in range(W) if grid[r][c] == "?"),
             sum(1 for r in range(H) for c in range(W) if grid[r][c] == "W"),
             sum(1 for r in range(H) for c in range(W) if grid[r][c] == "!"),
             sum(1 for r in range(H) for c in range(W) if grid[r][c] == "T")))
    if "--write" in argv:
        path = os.path.join(ROOT, "levels", "l6.txt")
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(u"已写入 %s" % path)
    else:
        print(u"（未写入，加 --write 才覆盖 levels/l6.txt）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
