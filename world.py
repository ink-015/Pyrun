# -*- coding: utf-8 -*-
"""地图解析、静态地形、相机与地图绘制。

本模块只做四件事，不碰玩家状态、不写存档：

  1. 把 levels/*.txt 解析成格子（解析错误必须报出**文件名 + 行号 + 列号**）
  2. 把实心格合并成少量矩形，供玩家碰撞使用
  3. 相机跟随与边界钳制（不显示地图外的空白，地图小于屏幕时居中）
  4. 地图绘制（地形在加载期烘焙成一张大图，运行时只 blit）

坐标约定与世界坐标一致：y 向下为正，一格 = config.TILE 像素。
"""

import math
import os

import pygame

import assets
import compat
import config
import enemy
import io_utils

# ---------------------------------------------------------------- 图例
# 与 README §11.2 完全一致。M3 只实现前四类，其余先解析出来占位，
# 等 M4/M5 接机关时直接用，不必回头改解析器。

TILE_SOLID = "#"
TILE_ONEWAY = "="
TILE_SPAWN = "P"
TILE_GOAL = "F"
TILE_COIN = "c"
TILE_BOUNCE = "J"
TILE_CHECK = "C"
TILE_GLIDER = "G"
TILE_SIGN = "S"
TILE_NPC = "N"
TILE_BAT = "B"
TILE_UFO = "U"
TILE_ROCK = "R"
TILE_WALKER = "Z"
TILE_ROTOR = "X"
TILE_HAMMER = "H"
TILE_BRICK = "?"          # M8 伪装砖
TILE_WALLSPIKE = "W"      # M8 天花板落刺
TILE_RISER = "!"          # M8 突墙
TILE_TWIN = "T"           # M8 二连落石

LEGEND = {
    ".": u"空气",
    "#": u"实心地形",
    "=": u"单向平台",
    "^": u"地刺",
    "v": u"天花板刺",
    "~": u"水（死亡）",
    "c": u"金币",
    "C": u"存档点（篝火）",
    "F": u"终点旗",
    "P": u"玩家出生点",
    "J": u"弹跳板",
    "S": u"告示牌",
    "N": u"NPC",
    "G": u"滑翔伞",
    "D": u"冲刺道具",
    "B": u"蝙蝠",
    "U": u"UFO",
    "M": u"水平移动平台",
    "m": u"垂直移动平台",
    "R": u"落石点",
    "Z": u"走地怪（可踩）",
    "X": u"旋转刺轮",
    "H": u"荡锤",
    "?": u"伪装砖",
    "W": u"天花板落刺",
    "!": u"突墙",
    "T": u"二连落石",
    "K": u"钥匙",
    "E": u"门",
}

# 危险格：M4 起真正生效
HAZARD_CHARS = ("^", "v", "~")


class LevelError(Exception):
    """地图解析错误。必须带文件名与行号，玩家改图时才知道改哪。

    ``line_no`` 为 0 表示与具体行无关（文件不存在、没有任何地图行等）。
    """

    def __init__(self, path, line_no, message, line=None, col=None):
        self.path = path
        self.line_no = line_no
        self.col = col
        self.line = line
        self.message = message
        Exception.__init__(self, self.describe())

    def describe(self):
        name = os.path.basename(self.path) if self.path else u"<地图>"
        if self.line_no:
            head = u"%s:%d" % (name, self.line_no)
        else:
            head = name
        if self.col:
            head += u":%d" % self.col
        text = u"%s  %s" % (head, self.message)
        # 把出错那行列出来并指到具体列，比只说"第 5 行错了"好查得多
        if self.line is not None and self.col:
            text += u"\n    %s\n    %s^" % (self.line, " " * (self.col - 1))
        return text


def _is_skippable(line):
    """空行与 ';' 注释行跳过。注释不影响行号，报错仍按真实文件行号。"""
    stripped = line.strip()
    return (not stripped) or stripped.startswith(";")


# ---------------------------------------------------------------- 解析

class _Parsed(object):
    """解析中间结果，别把字典到处传。"""

    def __init__(self):
        self.rows = []            # [(文件行号, 字符串)]
        self.spawn = []           # [(col, row)]
        self.goal = []            # [(col, row)]
        self.coins = []           # [(col, row)]
        self.hazards = []         # [(col, row, ch)]
        self.oneways = []         # [(col, row)]
        self.checkpoints = []     # [(col, row)]
        self.bouncers = []        # [(col, row)]
        self.gliders = []         # [(col, row)]  M5 道具
        self.signs = []           # [(col, row)]  M6 告示牌
        self.npcs = []            # [(col, row)]  M6 NPC
        self.bats = []            # [(col, row)]  M6 蝙蝠（连续段稍后合并）
        self.ufos = []            # [(col, row)]
        self.rock_spawns = []     # [(col, row)]  天花板裂缝
        self.walkers = []         # [(col, row)]  M7 走地怪（连续段稍后合并）
        self.rotors = []          # [(col, row)]  M7 旋转刺轮（轴心）
        self.hammers = []         # [(col, row)]  M7 荡锤（吊点所在格）
        self.bricks = []          # [(col, row)]  M8 伪装砖（就是地面那一格）
        self.wall_spikes = []     # [(col, row)]  M8 天花板落刺（空中那格）
        self.risers = []          # [(col, row)]  M8 突墙（地面正上方那格）
        self.twins = []           # [(col, row)]  M8 二连落石（第一块的位置）
        self.platforms = []       # [(col, row, ch)]  同字符连续段稍后合并
        self.others = []          # [(col, row, ch)]  已识别但暂未实现
        # M6 文本：按文件出现顺序排队，与地图里 S / N 的出现顺序一一配对
        self.sign_pages = []      # [(file_line, [页...])]
        self.npc_pages = []       # [(file_line, 名字, [页...])]


def _directive(text):
    """识别 ``;!sign ...`` / ``;!npc ...`` 这类数据指令行。

    为什么用注释行存文本：地图必须是严格矩形，把整段中文塞进格子里会
    直接把列宽搞崩；而注释行天生"不参与地图"，又有真实行号可以报错。
    代价是文本与牌子靠**出现顺序**配对（不是坐标），所以数量不一致时
    必须报错，不能默默错位。
    """
    body = text.strip()
    if not body.startswith(";!"):
        return None
    body = body[2:].strip()
    if not body:
        return None
    parts = body.split(None, 1)
    name = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    return name, rest


def _split_pages(text):
    """把 ``第一页|第二页`` 拆成页列表，丢掉空页。"""
    return [p.strip() for p in text.split("|") if p.strip()]


def _parse(path):
    if not os.path.isfile(path):
        raise LevelError(path, 0, u"地图文件不存在")
    try:
        raw_lines = io_utils.read_lines(path)
    except UnicodeDecodeError as exc:
        raise LevelError(path, 0, u"不是合法的 UTF-8 文本：%s" % exc)

    out = _Parsed()
    width = None

    for i, text in enumerate(raw_lines, 1):
        if _is_skippable(text):
            # 注释行里可能藏着告示牌/NPC 的文本，先过一遍指令
            cmd = _directive(text)
            if cmd is not None:
                name, rest = cmd
                if name == "sign":
                    pages = _split_pages(rest)
                    if not pages:
                        raise LevelError(path, i, u";!sign 后面没有文字")
                    out.sign_pages.append((i, pages))
                elif name == "npc":
                    # 第一段是名字，其余是页
                    chunks = [c.strip() for c in rest.split("|")]
                    who = chunks[0] if chunks else u""
                    pages = [c for c in chunks[1:] if c]
                    if not who or not pages:
                        raise LevelError(
                            path, i,
                            u";!npc 格式是「;!npc 名字|第一页|第二页」")
                    out.npc_pages.append((i, who, pages))
                else:
                    raise LevelError(
                        path, i, u"未知指令 ;!%s（只认识 sign / npc）" % name)
            continue
        line = text.rstrip("\r\n")
        if width is None:
            width = len(line)
            if width == 0:
                raise LevelError(path, i, u"第一行是空地图")
        elif len(line) != width:
            raise LevelError(
                path, i,
                u"行宽不一致：本行 %d 列，第一行 %d 列（地图必须是矩形）"
                % (len(line), width), line=line)
        out.rows.append((i, line))

    if not out.rows:
        raise LevelError(path, 0, u"没有任何地图行")

    for row, (file_line, line) in enumerate(out.rows):
        for col, ch in enumerate(line):
            if ch not in LEGEND:
                raise LevelError(
                    path, file_line,
                    u"未知字符 %r（不在图例里，见 README §11.2）" % ch,
                    line=line, col=col + 1)
            if ch == TILE_SPAWN:
                out.spawn.append((col, row))
            elif ch == TILE_GOAL:
                out.goal.append((col, row))
            elif ch == TILE_COIN:
                out.coins.append((col, row))
            elif ch == TILE_ONEWAY:
                out.oneways.append((col, row))
            elif ch == TILE_CHECK:
                out.checkpoints.append((col, row))
            elif ch == TILE_BOUNCE:
                out.bouncers.append((col, row))
            elif ch == TILE_GLIDER:
                out.gliders.append((col, row))
            elif ch == TILE_SIGN:
                out.signs.append((col, row))
            elif ch == TILE_NPC:
                out.npcs.append((col, row))
            elif ch == TILE_BAT:
                out.bats.append((col, row))
            elif ch == TILE_UFO:
                out.ufos.append((col, row))
            elif ch == TILE_ROCK:
                out.rock_spawns.append((col, row))
            elif ch == TILE_WALKER:
                out.walkers.append((col, row))
            elif ch == TILE_ROTOR:
                out.rotors.append((col, row))
            elif ch == TILE_HAMMER:
                out.hammers.append((col, row))
            elif ch == TILE_BRICK:
                out.bricks.append((col, row))
            elif ch == TILE_WALLSPIKE:
                out.wall_spikes.append((col, row))
            elif ch == TILE_RISER:
                out.risers.append((col, row))
            elif ch == TILE_TWIN:
                out.twins.append((col, row))
            elif ch in ("M", "m"):
                out.platforms.append((col, row, ch))
            elif ch in HAZARD_CHARS:
                out.hazards.append((col, row, ch))
            elif ch not in (".", TILE_SOLID):
                out.others.append((col, row, ch))

    # 牌子必须配文本，文本也不能多出来。数量对不上就直接报，
    # 否则"第 3 块牌子显示第 4 段话"这种错要靠玩家读起来才发现。
    if len(out.signs) != len(out.sign_pages):
        raise LevelError(
            path, 0,
            u"告示牌数量对不上：地图里 %d 个 S，文本 %d 条 ;!sign"
            % (len(out.signs), len(out.sign_pages)))
    if len(out.npcs) != len(out.npc_pages):
        raise LevelError(
            path, 0,
            u"NPC 数量对不上：地图里 %d 个 N，文本 %d 条 ;!npc"
            % (len(out.npcs), len(out.npc_pages)))

    if not out.spawn:
        raise LevelError(path, 0, u"缺少出生点 P（每关必须且只能有一个）")
    if len(out.spawn) > 1:
        raise LevelError(path, out.rows[out.spawn[1][1]][0],
                         u"出生点 P 有 %d 个，必须且只能有一个" % len(out.spawn))
    if not out.goal:
        raise LevelError(path, 0, u"缺少终点旗 F（M3 起每关必须有终点）")
    return out


# ---------------------------------------------------------------- 合并

def _merge_cells(cells):
    """把格子集合合并成尽量少的矩形，供碰撞使用。

    先按行合并连续格，再把上下相邻且左右范围完全相同的段竖向合并。
    第 1 关 44x9 合并后只剩 6 个矩形，碰撞循环代价可以忽略。
    """
    if not cells:
        return []

    # 1) 横向：每行连续段
    runs = []                       # [(row, col_start, length)]
    by_row = {}
    for col, row in cells:
        by_row.setdefault(row, []).append(col)
    for row in sorted(by_row):
        cols = sorted(by_row[row])
        start = prev = cols[0]
        for c in cols[1:]:
            if c == prev + 1:
                prev = c
                continue
            runs.append((row, start, prev - start + 1))
            start = prev = c
        runs.append((row, start, prev - start + 1))

    # 2) 竖向：同 x、同宽、行号连续则合并
    grouped = {}
    for row, start, length in runs:
        grouped.setdefault((start, length), []).append(row)

    rects = []
    tile = config.TILE
    for (start, length), rows in grouped.items():
        rows.sort()
        begin = prev = rows[0]
        for r in rows[1:]:
            if r == prev + 1:
                prev = r
                continue
            rects.append(pygame.Rect(start * tile, begin * tile,
                                     length * tile, (prev - begin + 1) * tile))
            begin = prev = r
        rects.append(pygame.Rect(start * tile, begin * tile,
                                 length * tile, (prev - begin + 1) * tile))
    rects.sort(key=lambda r: (r.y, r.x))
    return rects


# ---------------------------------------------------------------- 移动平台

class MovingPlatform(object):
    """一格一格的机关平台。

    为什么用线性往返而不是正弦：正弦在端点会减速到 0，玩家站在上面时
    "平台突然不走了"很难判断是不是卡住了；线性往返每一帧的位移恒定，
    配合"到端点立刻反向"的规则，玩家能背下节奏。

    ``rect`` 始终是整数矩形（碰撞与 blit 都要整数），浮点位移存在
    ``offset`` 里，每帧取整后比较得出 ``delta``——带动玩家时用的是
    这个整数差，而不是速度乘以 dt，这样平台和玩家永远不会差半个像素。
    """

    def __init__(self, rect, axis, speed=None, travel=None):
        self.rect = pygame.Rect(rect)
        self.origin = (self.rect.x, self.rect.y)
        self.axis = axis
        self.speed = config.PLATFORM_SPEED if speed is None else float(speed)
        self.travel = config.PLATFORM_TRAVEL if travel is None else float(travel)
        self.offset = 0.0          # 0..travel
        self.dir = 1               # +1 向行程末端（水平向右 / 垂直向上）
        self.delta = (0, 0)
        self.dwell = 0.0           # 到端点后的停留倒计时

    def update(self, dt):
        old = (self.rect.x, self.rect.y)
        if self.dwell > 0.0:
            # 停在端点让人上下，delta 保持 0，站上面的玩家不会被抖
            self.dwell = max(0.0, self.dwell - dt)
            self.delta = (0, 0)
            return
        self.offset += self.speed * dt * self.dir
        if self.offset >= self.travel:
            self.offset = self.travel
            self.dir = -1
            self.dwell = config.PLATFORM_DWELL
        elif self.offset <= 0.0:
            self.offset = 0.0
            self.dir = 1
            self.dwell = config.PLATFORM_DWELL

        if self.axis == "x":
            self.rect.x = int(round(self.origin[0] + self.offset))
        else:
            # 竖直平台写在地图上时是"最低点"，往上走 2 格再回来
            self.rect.y = int(round(self.origin[1] - self.offset))
        self.delta = (self.rect.x - old[0], self.rect.y - old[1])

    def touch_rect(self):
        """带动玩家用的判定面：整块矩形。玩家站在顶面上就该被带走。"""
        return self.rect

    def arrow(self):
        """当前移动方向（屏幕坐标下的 dx, dy），画箭头用。"""
        if self.axis == "x":
            return (self.dir, 0)
        return (0, -self.dir)


def _platform_runs(cells):
    """把同一行里连续的同类平台格合成一条平台。

    `MMM` = 3 格宽的水平平台；`mmm` = 3 格宽的升降平台。
    分段规则和 _merge_cells 的横向部分一致，只是不做竖向合并——
    竖直方向的两串平台是两条独立轨道，合起来会变成一堵移动的墙。
    """
    by_key = {}
    for col, row, ch in cells:
        by_key.setdefault((row, ch), []).append(col)

    out = []
    tile = config.TILE
    for (row, ch), cols in sorted(by_key.items()):
        cols.sort()
        start = prev = cols[0]
        for c in cols[1:]:
            if c == prev + 1:
                prev = c
                continue
            out.append(MovingPlatform(
                (start * tile, row * tile, (prev - start + 1) * tile, tile // 2),
                "x" if ch == "M" else "y"))
            start = prev = c
        out.append(MovingPlatform(
            (start * tile, row * tile, (prev - start + 1) * tile, tile // 2),
            "x" if ch == "M" else "y"))
    return out


# ---------------------------------------------------------------- 蝙蝠巡逻段

def _bat_runs(cells):
    """把同一行里连续的 'B' 合成一条巡逻线，返回 [(左像素, 右像素, 中心y)]。

    巡逻区间取"首格中心 → 末格中心"，而不是格子边界：蝙蝠的判定框只有
    30px 宽，贴着格子边缘折返时会有一小段完全悬在墙里。
    """
    by_row = {}
    for col, row in cells:
        by_row.setdefault(row, []).append(col)

    tile = config.TILE
    out = []
    for row in sorted(by_row):
        cols = sorted(by_row[row])
        start = prev = cols[0]
        runs = []
        for c in cols[1:]:
            if c == prev + 1:
                prev = c
                continue
            runs.append((start, prev))
            start = prev = c
        runs.append((start, prev))
        for a, b in runs:
            # 超长段拆成几段短巡逻，而不是拉一屏长线：一张图画错了不该让
            # 整关打不开，但也不能让蝙蝠横穿半个屏幕、玩家只能干等。
            step = config.BAT_PATROL_MAX
            while a <= b:
                tail = min(b, a + step - 1)
                out.append((a * tile + tile // 2, tail * tile + tile // 2,
                            row * tile + tile // 2))
                a = tail + 1
    return out


# ---------------------------------------------------------------- 走地怪巡逻段

def _walker_runs(cells):
    """把同一行里连续的 'Z' 合成一条巡逻线，返回 [(左px, 右px, 行号)]。

    和蝙蝠同一个思路，但范围取**格子边界**而不是中心：走地怪的宽度是
    36px，按中心算会让它在两端的半个身位悬空，看起来像踩在空气上。
    超长段直接截断成几段（和蝙蝠一样），不让一张画错的图把整关堵死。
    """
    by_row = {}
    for col, row in cells:
        by_row.setdefault(row, []).append(col)

    tile = config.TILE
    out = []
    for row in sorted(by_row):
        cols = sorted(by_row[row])
        start = prev = cols[0]
        runs = []
        for c in cols[1:]:
            if c == prev + 1:
                prev = c
                continue
            runs.append((start, prev))
            start = prev = c
        runs.append((start, prev))
        for a, b in runs:
            step = config.WALKER_RUN_MAX
            while a <= b:
                tail = min(b, a + step - 1)
                out.append((a * tile + config.WALKER_BODY_W // 2,
                            (tail + 1) * tile - config.WALKER_BODY_W // 2,
                            row))
                a = tail + 1
    return out


# ---------------------------------------------------------------- 伞面

def draw_canopy(surface, cx, base_y, half_w=20, height=16,
                fill=None, outline=None, sway=0.0):
    """画一片伞面（上半圆弧），道具图标与角色头顶的滑翔伞共用。

    为什么不用 pygame.draw.arc：它只能描边，画不出"实心弧面"；用椭圆上半圈
    的多边形拟合，既能填色又能描边，顶点数与 draw.arc 一致，看不出区别。
    ``sway`` 让伞面整体左右歪一点，滑翔时伞会轻轻摆，静止图标则不歪。
    """
    fill = config.COLOR_GLIDE if fill is None else fill
    outline = config.COLOR_INK if outline is None else outline
    steps = 10
    pts = []
    for i in range(steps + 1):
        a = math.pi * i / steps
        pts.append((int(round(cx + half_w * math.cos(a) + sway * math.sin(a))),
                    int(round(base_y - height * math.sin(a)))))
    pygame.draw.polygon(surface, fill, pts)
    pygame.draw.lines(surface, outline, False, pts, 2)
    pygame.draw.line(surface, outline, pts[0], pts[-1], 2)
    return pts


# ---------------------------------------------------------------- 相机

class Camera(object):
    """跟随相机。钳制在 world_rect 内部，绝不显示地图外的空白。

    地图比视口小时（比如以后的短测试关）水平居中，两边露出纸底——
    这是 README §19 M3 明确允许的例外。
    """

    def __init__(self, view_size, world_rect):
        self.vw, self.vh = int(view_size[0]), int(view_size[1])
        self.world = pygame.Rect(world_rect)
        self.x = 0.0
        self.y = 0.0
        self.clamp()

    # ---- 边界 ----
    @staticmethod
    def _clamp_axis(value, world_size, view_size):
        if world_size <= view_size:
            return (world_size - view_size) * 0.5    # 居中，两边留白
        return min(max(value, 0.0), float(world_size - view_size))

    def clamp(self):
        self.x = self._clamp_axis(self.x, self.world.width, self.vw)
        self.y = self._clamp_axis(self.y, self.world.height, self.vh)

    # ---- 跟随 ----
    def snap_to(self, target):
        """瞬间对准目标，进关时用，避免开场镜头从左上角滑过来。"""
        self.x = target.centerx - self.vw * 0.5
        self.y = target.centery - self.vh * 0.5
        self.clamp()

    def update(self, dt, target):
        """指数平滑跟随。

        用 1-exp(-k*dt) 而不是每帧乘固定系数：帧率变化时收敛速度一致，
        固定步长下就是常数，测起来也可预期。
        """
        k = 1.0 - math.exp(-config.CAMERA_LERP * dt)

        des_x = target.centerx - self.vw * 0.5
        self.x += (des_x - self.x) * k

        # 竖直方向加死区：小幅跳跃不带着整个画面上下晃
        half = self.vh * 0.5
        dy = target.centery - (self.y + half)
        dead = config.CAMERA_DEADZONE_Y
        if dy > dead:
            des_y = self.y + (dy - dead)
        elif dy < -dead:
            des_y = self.y + (dy + dead)
        else:
            des_y = self.y
        self.y += (des_y - self.y) * k

        self.clamp()

    # ---- 换算 ----
    @property
    def offset(self):
        """世界坐标 -> 屏幕坐标的整数偏移。整数化避免像素抖动。"""
        return (-int(round(self.x)), -int(round(self.y)))

    def apply(self, rect):
        ox, oy = self.offset
        return pygame.Rect(rect.x + ox, rect.y + oy, rect.width, rect.height)

    @property
    def view_rect(self):
        return pygame.Rect(int(round(self.x)), int(round(self.y)),
                           self.vw, self.vh)


# ---------------------------------------------------------------- 世界

class World(object):
    """一张已解析、已烘焙好的地图。"""

    def __init__(self, path, parsed):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.width_tiles = len(parsed.rows[0][1])
        self.height_tiles = len(parsed.rows)
        self.lines = [line for _, line in parsed.rows]

        self.solid_cells = set()
        for row, line in enumerate(self.lines):
            for col, ch in enumerate(line):
                if ch == TILE_SOLID:
                    self.solid_cells.add((col, row))

        self.oneway_cells = set(parsed.oneways)
        self.hazards = list(parsed.hazards)
        self.others = list(parsed.others)

        # 碰撞用矩形（合并过）。单向平台单独一组：它只在"从上方落下"时挡人，
        # 混进 solids 会把玩家从下面顶住，跳不上去。
        self.solids = _merge_cells(self.solid_cells)
        # 单向平台的矩形只保留顶面那一薄层：判定与绘制都需要"板子"而不是
        # 一个 64px 的实心方块，否则站在上面时画面会空出一整格。
        self.oneways = [pygame.Rect(r.x, r.y, r.width, config.ONEWAY_THICK)
                        for r in _merge_cells(list(self.oneway_cells))]
        self.platforms = _platform_runs(parsed.platforms)
        # 每帧给玩家的实心列表：地形 + 当前帧的移动平台。
        # 预分配同一个 list，用切片赋值原地更新，避免每帧新建对象。
        self._dynamic_solids = list(self.solids)

        tile = config.TILE
        self.bounds = pygame.Rect(0, 0, self.width_tiles * tile,
                                  self.height_tiles * tile)

        # 出生点：格子底部对齐，脚正好站在格子下沿
        col, row = parsed.spawn[0]
        self.spawn = (col * tile + (tile - 26) // 2, (row + 1) * tile - 70)
        self.spawn_cell = (col, row)

        self.goal_cells = list(parsed.goal)
        gc, gr = parsed.goal[0]
        self.goal_rect = pygame.Rect(gc * tile, gr * tile, tile, tile)
        # 终点判定区比旗子那一格高：旗子是一根杆，从杆的任意高度经过都算到。
        # 只看脚下那一格的话，一路蹦着过去的玩家会从旗子头顶飞过去，
        # 然后在关底外面掉出地图——这不是"技术好"，是判定不合理。
        self.goal_zone = pygame.Rect(gc * tile,
                                     (gr + 1 - config.GOAL_ZONE_ROWS) * tile,
                                     tile, config.GOAL_ZONE_ROWS * tile)
        self.goal_reached = False

        # 金币：格子中心 24x24 的拾取框，比贴图小，避免"擦边就算吃到"
        self.coins = []
        for i, (c, r) in enumerate(parsed.coins):
            self.coins.append({
                "col": c, "row": r,
                "rect": pygame.Rect(c * tile + tile // 2 - 12,
                                    r * tile + tile // 2 - 12, 24, 24),
                "phase": i * 0.7,
                "taken": False,
            })
        self.total_coins = len(self.coins)
        self.taken_coins = 0

        # ---- 危险格（M4）----
        # 判定框贴着实物的那一侧，不占满整格：地刺长在格子底部，水位整格。
        # 满格判定会让玩家在刺尖上方半个身位就死，看起来像碰瓷。
        self.hazard_boxes = []
        inset = config.HAZARD_INSET
        for c, r, ch in parsed.hazards:
            box = pygame.Rect(c * tile, r * tile, tile, tile)
            if ch == "^":
                box = pygame.Rect(box.x + inset, box.bottom - 30, tile - 2 * inset, 24)
            elif ch == "v":
                box = pygame.Rect(box.x + inset, box.y, tile - 2 * inset, 30)
            else:
                box = pygame.Rect(box.x + inset, box.y + inset,
                                  tile - 2 * inset, tile - 2 * inset)
            self.hazard_boxes.append((box, ch))

        # ---- 弹跳板 ----
        # 判定面贴在格子底部（也就是脚下地面的上表面），玩家走过、落下都会弹。
        # 高度只有 8px：太厚会挡住自己的碰撞，太薄又会在 18px/帧 的下落里被跳过。
        self.bouncer_cells = list(parsed.bouncers)
        self.bouncers = []
        for c, r in parsed.bouncers:
            self.bouncers.append(pygame.Rect(c * tile + 4, (r + 1) * tile - 8,
                                             tile - 8, 8))

        # ---- 篝火检查点 ----
        # 必须按"跑到它的先后"（列坐标）排，不能按地图文件的行序。
        # 解析器是自上而下扫地图的：第 5 关水池前那盏在天空开阔的第 8 行，
        # 荡锤前那盏在贴地的第 10 行，于是列表里右边那盏排在左边那盏前面。
        # 而点亮规则是"只允许往关卡后面走"（idx > checkpoint_index），
        # 索引一颠倒，点亮荡锤前那盏之后，水池前那盏就永远点不亮了——
        # 玩家要等死了才发现自己没存上档。
        bw, bh = config.CHECKPOINT_BOX
        self.checkpoints = []
        for c, r in sorted(parsed.checkpoints):
            self.checkpoints.append({
                "col": c, "row": r,
                "rect": pygame.Rect(c * tile + (tile - bw) // 2,
                                    (r + 1) * tile - bh, bw, bh),
                "spawn": (c * tile + (tile - 26) // 2, (r + 1) * tile - 70),
                "active": False,
                "phase": (c * 0.37) % 6.28,
            })

        # ---- 道具：滑翔伞（M5）----
        # 判定区是整格宽、往上 3 格高的竖条（见 config.ITEM_CATCH_ROWS）：
        # 玩家从道具上方跳过去也算拿到。滑翔伞是通关必需道具，不能因为
        # "跑的时候顺手跳了一下"就漏捡，然后在坑边才发现自己过不去。
        rows = config.ITEM_CATCH_ROWS
        self.gliders = []
        for c, r in parsed.gliders:
            self.gliders.append({
                "col": c, "row": r,
                "rect": pygame.Rect(c * tile, (r + 1 - rows) * tile,
                                    tile, rows * tile),
                # 画图仍然按格子中心，判定区比图标大得多
                "pos": (c * tile + tile // 2, r * tile + tile // 2),
                "taken": False,
                "phase": (c * 0.9) % 6.28,
            })
        self.glider_total = len(self.gliders)
        self.glider_taken = 0

        # ---- 告示牌与 NPC（M6）----
        # 文本来自地图注释里的 ;!sign / ;!npc，解析器已保证数量一一对应。
        self.signs = []
        for (c, r), (line_no, pages) in zip(parsed.signs, parsed.sign_pages):
            self.signs.append(self._make_talker("sign", c, r, u"告示牌",
                                                pages, line_no))
        self.npcs = []
        for (c, r), (line_no, who, pages) in zip(parsed.npcs, parsed.npc_pages):
            self.npcs.append(self._make_talker("npc", c, r, who, pages, line_no))
        self.focus = None          # {"kind", "obj"}：当前可交互目标
        self.talked = set()        # 已经读过的对象下标集合（(kind, i)）

        # ---- 敌人（M6）----
        self.bats = [enemy.Bat(a, b, y) for a, b, y in _bat_runs(parsed.bats)]
        self.ufos = [enemy.Ufo(c * tile + tile // 2, r * tile + tile // 2)
                     for c, r in parsed.ufos]
        self.rock_spawners = []
        for i, (c, r) in enumerate(parsed.rock_spawns):
            ground = self.ground_y_below(c * tile + tile // 2,
                                         (r + 1) * tile)
            if ground is None:
                ground = self.bounds.bottom
            # 裂缝画在格子顶边（也就是天花板的底面），石头从那儿掉
            self.rock_spawners.append(
                enemy.RockSpawner(c * tile + tile // 2, r * tile,
                                  ground, (0.35 + 0.27 * i) % 1.0))
        self.rock_spawners.sort(key=lambda s: s.cx)
        # M7：走地怪。落地点取"脚下第一块实心"，找不到就退回本格底边——
        # 悬空的走地怪看着像bug，但仍然让它站在某个高度上，不要掉进虚空里。
        self.walkers = []
        for i, (left, right, row) in enumerate(_walker_runs(parsed.walkers)):
            mid = (left + right) * 0.5
            ground = self.ground_y_below(mid, (row + 1) * tile)
            if ground is None:
                ground = (row + 1) * tile
            self.walkers.append(
                enemy.Walker(left, right, ground, phase=(0.37 * i) % 1.0))
        # M7：旋转刺轮与荡锤。相位按列号错开，免得一排机关同步得像节拍器。
        # 刺轮轴心取 X 格的**顶边**（和荡锤一样吊在梁底）：只有把轴心抬到
        # 头顶以上，臂才能短到"站着扫不到、跳起来才挨"。
        self.rotors = [enemy.Rotor(c * tile + tile // 2, r * tile,
                                   phase=((c * 0.53 + r * 0.29) % 2.0))
                       for c, r in parsed.rotors]
        # 荡锤的吊点取 H 格的**顶边**：地图里 H 必须写在横梁正下方，
        # 吊点贴着梁底，锤子看起来才是吊在梁上的。
        self.hammers = [enemy.Pendulum(c * tile + tile // 2, r * tile,
                                       phase=((c * 0.41) % 2.0))
                        for c, r in parsed.hammers]
        # ---- 隐形机关（M8）----
        # 伪装砖：写在**地面那一格**（`?` 本身就当地板用），所以它的矩形
        # 顶边就是行走面，不需要再对齐到"脚下第一块实心"。
        self.bricks = [enemy.CrumbleBrick(c, r) for c, r in parsed.bricks]
        # 天花板落刺：`W` 写在空中那格，它头顶那格必须是实心——刺是从天花板
        # 里扎下来的，没有天花板就没有安装点（生成器会先报这个错）。
        self.drop_spikes = []
        for c, r in parsed.wall_spikes:
            ground = self.ground_y_below(c * tile + tile // 2, (r + 1) * tile)
            if ground is None:
                # 底下是坑或水：刺照样掉到底图底部，玩家本来也会死在那里
                ground = self.bounds.bottom
            self.drop_spikes.append(
                enemy.DropSpike(c * tile + tile // 2, r * tile, ground))
        # 突墙：`!` 写在地面**正上方那一格**（不能写进地面，否则地上就破了个
        # 洞），墙从这格的底边往上长，也就是从地板面往上长。
        self.risers = [enemy.RisingWall(c * tile + tile // 2, (r + 1) * tile)
                       for c, r in parsed.risers]
        # 二连落石：`T` 是**近的那一块**，远的那块固定往右偏 TWIN_GAP。
        self.twins = [enemy.TwinRock(c * tile + tile // 2, r * tile,
                                     config.TWIN_GAP)
                      for c, r in parsed.twins]
        # 更新顺序：会发石头的（UFO/裂缝/二连石）在前，之后统一推进已有的石头
        self.enemies = (list(self.ufos) + list(self.rock_spawners)
                        + list(self.twins) + list(self.bats)
                        + list(self.walkers)
                        + list(self.rotors) + list(self.hammers)
                        + list(self.bricks) + list(self.drop_spikes)
                        + list(self.risers))
        self.rocks = []            # 场上的落石，碎完自动回收
        self.rock_count = 0        # 累计投下多少块，调试与自检用
        self._prompt_font = None   # 惰性取字体，避免每帧查缓存表

        self.time = 0.0
        self.flag_img = None
        self.coin_img = None
        self.camp_img = None
        self.camp_dim_img = None
        self._load_images()
        self.bg = self._bake()
    # ---- 加载 ----
    @classmethod
    def load(cls, path):
        return cls(path, _parse(path))

    def _load_images(self):
        """终点旗、金币与篝火贴图。缺失不影响能玩，绘制层会退回代码画。

        路径一律相对 assets/（和 assets.hero_anim_specs 的 "images/hero/..."
        保持同一套约定）。M3 写成了相对 images/，结果三张图一直没加载成功，
        画面全靠兜底绘制——真图缺了不会报错，这种错最隐蔽。
        """
        tile = config.TILE
        try:
            flag = assets.image("images/collectibles/tile_flag.png")
            scale = float(tile) / flag.get_height()
            # 素材是黑线条白底，直接贴会是一片白。染成旗子的暖色才认得出是终点
            self.flag_img = compat.tint(
                assets.smooth_scaled(flag, scale, "flag"), config.COLOR_CAMP)
        except assets.AssetMissing:
            self.flag_img = None
        try:
            coin = assets.image_scaled("images/collectibles/tile_coin.png", 0.62)
            self.coin_img = compat.tint(coin, config.COLOR_COIN)
        except assets.AssetMissing:
            self.coin_img = None
        # 篝火两张：点亮的是暖橙，熄灭的是灰调。都用同一张图染色，
        # 省掉一套美术资源，也让"亮没亮"一眼就能看出来。
        try:
            camp = assets.image("images/checkpoints/campfire.png")
        except assets.AssetMissing:
            camp = None
        if camp is not None:
            self.camp_img = compat.tint(camp, config.COLOR_CAMP)
            self.camp_dim_img = compat.tint(camp, (176, 172, 164))

    # ---- 查询 ----
    def cell_at_px(self, x, y):
        col = int(x // config.TILE)
        row = int(y // config.TILE)
        if col < 0 or row < 0 or col >= self.width_tiles or row >= self.height_tiles:
            return "."
        return self.lines[row][col]

    def is_solid_px(self, x, y):
        return self.cell_at_px(x, y) == TILE_SOLID

    def ground_y_below(self, x, y, limit=None):
        """从 y 往下找第一个实心面的 y；找不到返回 None。自动巡航测试用。"""
        limit = limit if limit is not None else self.bounds.bottom
        step = config.TILE // 4
        probe = y
        while probe <= limit:
            if self.is_solid_px(x, probe):
                return int(probe // config.TILE) * config.TILE
            probe += step
        return None

    # ---- 更新 ----
    def update(self, dt, player=None):
        """推进一帧。

        ``player`` 可以为 None（加载后先画一帧、脱机测试），这时敌人照样动，
        但不会投石、也不刷新可交互目标——没有玩家就没有"射程"和"靠近"。
        """
        self.time += dt
        if self.platforms:
            for p in self.platforms:
                p.update(dt)

        if self.enemies:
            for e in self.enemies:
                req = e.update(dt, player)
                if req:
                    self._spawn_rock(req)
        if self.rocks:
            for r in self.rocks:
                r.update(dt, player)
            if any(r.dead for r in self.rocks):
                # 只在真的有石头碎完时才重建列表，避免每帧新建对象
                self.rocks = [r for r in self.rocks if not r.dead]

        self._update_focus(player)

    def collision_solids(self):
        """本帧玩家要撞的实心矩形：地形 + 移动平台 + 还没塌的伪装砖 + 升起的突墙。

        伪装砖和突墙必须进这张表：它们**就是地面和墙本身**，只是会变。
        把"会消失的地板"做成危险格是另一种做法，但那意味着玩家站在上面
        的那 0.3 秒里仍在"踩空判定"里——看起来站着，其实已经死了。

        返回的是内部复用的同一个 list，调用方不要保存或修改它。
        没有动态物件时直接返回地形表，连拼一遍都省了。
        """
        if not (self.platforms or self.bricks or self.risers):
            return self.solids
        lst = self._dynamic_solids
        lst[:] = self.solids
        for p in self.platforms:
            lst.append(p.rect)
        for b in self.bricks:
            r = b.solid()
            if r is not None:
                lst.append(r)
        for w in self.risers:
            r = w.solid()
            if r is not None:
                lst.append(r)
        return lst

    def carrying_platform(self, player):
        """玩家正站在哪块移动平台上，没有则 None。"""
        for p in self.platforms:
            if player.stands_on(p.rect):
                return p
        return None

    def hazard_at(self, rect):
        """与 rect 相交的危险格，返回字符（'^' / 'v' / '~'）或 None。"""
        for box, ch in self.hazard_boxes:
            if rect.colliderect(box):
                return ch
        return None

    def checkpoint_hit(self, rect):
        """碰到还没点亮的篝火时返回它的下标，否则 -1。

        已经亮着的篝火不再重复触发：一是没必要，二是"回检查点"时
        玩家就站在篝火上，不排除掉会每帧都报一次。
        """
        for i, cp in enumerate(self.checkpoints):
            if cp["active"]:
                continue
            if rect.colliderect(cp["rect"]):
                return i
        return -1

    # ---- 重置 ----
    def reset_runtime(self):
        """重开本关时把运行期状态清干净（地形与烘焙图保留）。

        为什么不直接重新 load：烘焙一张 2816x576 的地形要几十毫秒，
        按 R 重开时会有明显卡顿。地形是不变的，只有金币、篝火、旗子要复位。
        """
        for coin in self.coins:
            coin["taken"] = False
        self.taken_coins = 0
        for it in self.gliders:
            it["taken"] = False
        self.glider_taken = 0
        for cp in self.checkpoints:
            cp["active"] = False
        for p in self.platforms:
            p.offset = 0.0
            p.dir = 1
            p.dwell = 0.0
            p.rect.x, p.rect.y = p.origin
            p.delta = (0, 0)
        for e in self.enemies:
            e.reset()
        self.rocks = []
        self.rock_count = 0
        self.focus = None
        self.goal_reached = False
        self.time = 0.0
        self.talked = set()

    # ---- 交互：告示牌与 NPC（M6）----
    def _make_talker(self, kind, col, row, name, pages, line_no):
        """一块牌子或一个 NPC。zone 是"能触发对话"的范围。

        zone 比格子高一倍（含上方那格），因为玩家是站在牌子脚下那格读的，
        眼睛却在牌子那一格。只按格子算，会出现"明明脸贴着脸却没反应"。
        """
        tile = config.TILE
        cell = pygame.Rect(col * tile, row * tile, tile, tile)
        return {
            "kind": kind,
            "col": col, "row": row,
            "name": name,
            "pages": list(pages),
            "line": line_no,
            "cell": cell,
            "zone": pygame.Rect(cell.x - 12, cell.y - tile,
                                tile + 24, tile * 2),
        }

    def _update_focus(self, player):
        """算出离玩家最近的可交互对象。每帧算一次，绘制与按键共用。"""
        self.focus = None
        if player is None or not (self.signs or self.npcs):
            return
        best = None
        best_d = None
        for obj in self.signs + self.npcs:
            if not obj["zone"].colliderect(player.rect):
                continue
            rng = (config.NPC_RANGE if obj["kind"] == "npc"
                   else config.SIGN_RANGE)
            d = abs(obj["cell"].centerx - player.rect.centerx)
            if d > rng:
                continue
            if best_d is None or d < best_d:
                best, best_d = obj, d
        self.focus = best

    def interact(self):
        """返回 (说话人, 页列表, 类型)；没有可交互对象时返回 None。

        类型是 "npc" / "sign"，画面层据此决定画不画名字——牌子没人说话。
        """
        obj = self.focus
        if obj is None:
            return None
        self.talked.add((obj["kind"], obj["col"], obj["row"]))
        return (obj["name"], list(obj["pages"]), obj["kind"])

    # ---- 敌人（M6）----
    def enemy_hit(self, rect):
        """玩家判定盒是否撞上敌人，返回死亡原因或 None。

        只查蝙蝠、走地怪和正在下落的石头。UFO 与天花板裂缝本身不带判定：
        "头顶有个碰不得的东西"在跑酷里是纯噪音。
        """
        for b in self.bats:
            box = b.hitbox()
            if box is not None and rect.colliderect(box):
                return u"被蝙蝠撞到"
        for w in self.walkers:
            box = w.hitbox()
            if box is not None and rect.colliderect(box):
                return u"被走地怪撞到"
        for r in self.rocks:
            box = r.hitbox()
            if box is not None and rect.colliderect(box):
                return u"被落石砸中"
        return None

    def stomp(self, player):
        """判断这一帧是不是踩中了走地怪的头顶。

        三个条件缺一不可：
          - 正在下落（vy > 0）：站着碰到怪物的头顶不该是"踩死"而是"撞上"；
          - 玩家判定盒与怪物相交；
          - 脚底落在怪物判定框的上 70%（STOMP_TOP_RATIO）以内。
        最后一条是关键。只判相交的话，从侧面擦上去也会被算成踩踏，
        表现为"人贴着怪死了一半又被弹起来"，比直接死更让人困惑。
        """
        if player.vy <= 0.0:
            return None
        for w in self.walkers:
            zone = w.stomp_zone()
            if zone is None:
                continue
            if player.rect.colliderect(w.hitbox()) \
                    and player.rect.bottom <= zone.bottom:
                return w
        return None

    # ---- 机关（M7 / M8）----
    def mechanism_hit(self, rect):
        """会动的致死机关：刺轮 / 荡锤 / 天花板落刺 / 突墙的刺。返回死因或 None。

        它们和"危险格"分开：危险格是静态的、烘焙在地形上的，这些会动，
        而且判定是"沿臂采样"、"圆心距离"、"只判刺头"，不是矩形相交。
        合并到 hazard_at 里会让那张表看不出哪些格是常驻危险。

        伪装砖**不在这里**：它不杀人，只改地形（变没），走碰撞表那条路，
        见 collision_solids()。
        """
        for r in self.rotors:
            if r.hits(rect):
                return u"被旋转刀片绞到"
        for h in self.hammers:
            if h.hits(rect):
                return u"被荡锤砸中"
        for s in self.drop_spikes:
            if s.hits(rect):
                return u"被天花板落刺扎到"
        for w in self.risers:
            if w.hits(rect):
                return u"撞在突墙的刺上"
        return None

    def _spawn_rock(self, req):
        if req[0] == "twin":
            # 二连石：两块同一帧"预订"，但预警长短不同。远的那块影子收得
            # 更快，于是玩家会先看见它要落——这正是这一招的提示。
            _, (xa, ya), (xb, yb) = req
            for x, y, warn in ((xa, ya, config.TWIN_WARN_A),
                               (xb, yb, config.TWIN_WARN_B)):
                ground = self.ground_y_below(x, y)
                if ground is None:
                    ground = self.bounds.bottom
                self.rocks.append(enemy.FallingRock(x, y, ground, warn))
                self.rock_count += 1
            return
        _, x, y = req
        ground = self.ground_y_below(x, y)
        if ground is None:
            # 落点下面是水或深渊：石头一路掉到地图底再碎，玩家本来也会死
            ground = self.bounds.bottom
        self.rocks.append(enemy.FallingRock(x, y, ground))
        self.rock_count += 1

    def reset_traps(self):
        """把机关复位。**每次重生/回检查点都要调**。

        伪装砖和突墙是会"留在场上"的机关：砖踩塌之后如果不复位，玩家在
        篝火重生、跑回坑边时会发现桥已经没了——那不是难，是卡死。
        落石也一并清掉：重生那一刻头顶还挂着半块石头，最没道理。
        """
        for b in self.bricks:
            b.reset()
        for s in self.drop_spikes:
            s.reset()
        for w in self.risers:
            w.reset()
        for t in self.twins:
            t.reset()
        self.rocks = []

    def collect(self, player_rect):
        """拾取与玩家碰撞盒相交的金币，返回本次吃到的个数。"""
        got = 0
        for coin in self.coins:
            if coin["taken"]:
                continue
            if player_rect.colliderect(coin["rect"]):
                coin["taken"] = True
                self.taken_coins += 1
                got += 1
        return got

    def collect_items(self, player_rect):
        """拾取道具，返回本次拿到的道具名列表（目前只有 "glider"）。

        和金币分开算：金币是"收集度"，道具是"能力解锁"，混在一起会让
        HUD 上的金币数被道具干扰。
        """
        got = []
        for it in self.gliders:
            if it["taken"]:
                continue
            if player_rect.colliderect(it["rect"]):
                it["taken"] = True
                self.glider_taken += 1
                got.append("glider")
        return got

    # ---- 绘制 ----
    def _bake(self):
        """把整张地形画到一个大表面，运行时只 blit。

        逐帧按格绘制的代价随地图面积线性增长；烘焙一次后，每帧成本只和
        屏幕大小有关。第 1 关烘焙约 2816x576，耗时几十毫秒，只发生一次。
        """
        surface = pygame.Surface(self.bounds.size)
        surface.fill(config.COLOR_PAPER)

        tile = config.TILE
        # 极淡方格底，和菜单保持同一套纸面风格
        for x in range(0, self.bounds.width, tile):
            pygame.draw.line(surface, config.COLOR_PAPER_LINE, (x, 0),
                             (x, self.bounds.height))
        for y in range(0, self.bounds.height, tile):
            pygame.draw.line(surface, config.COLOR_PAPER_LINE, (0, y),
                             (self.bounds.width, y))

        # 先铺土体，再画表层细节，避免后铺的方块盖住前一块的顶线
        for col, row in self.solid_cells:
            pygame.draw.rect(surface, config.COLOR_GROUND,
                             pygame.Rect(col * tile, row * tile, tile, tile))

        for col, row in sorted(self.solid_cells):
            self._draw_cell(surface, col, row)

        # 机关也烘焙进静态地形：它们不会动，每帧重画的唯一效果是把帧预算
        # 花在画同样的三角形和波浪线上。
        for rect in self.oneways:
            self._draw_plank(surface, rect)
        for c, r, ch in self.hazards:
            self._draw_hazard(surface, c, r, ch)
        for c, r in self.bouncer_cells:
            self._draw_bouncer(surface, c, r)

        if pygame.display.get_surface() is not None:
            try:
                surface = surface.convert()
            except pygame.error:
                pass
        return surface

    def _hash(self, col, row, k=0):
        """确定性伪随机，用来做手绘抖动。

        必须确定性：同一格每帧抖动不同的话，画面会像在沸腾。
        """
        h = (col * 73856093) ^ (row * 19349663) ^ (k * 83492791)
        return (h & 0xFFFF) / 65535.0

    def _draw_cell(self, surface, col, row):
        tile = config.TILE
        x, y = col * tile, row * tile
        above_air = (col, row - 1) not in self.solid_cells
        below_air = (col, row + 1) not in self.solid_cells
        left_air = (col - 1, row) not in self.solid_cells
        right_air = (col + 1, row) not in self.solid_cells

        # 表层短竖纹，暗示"泥土"，只画在最上面一层，深处留白
        if above_air:
            hatch = (228, 224, 213)
            step = 11
            for i in range(1, tile // step + 1):
                hx = x + i * step - 3 + int(self._hash(col, row, i) * 3)
                top = y + 16 + int(self._hash(col, row, i + 40) * 4)
                pygame.draw.line(surface, hatch, (hx, top), (hx, top + 14), 1)
        elif below_air:
            # 悬空岩板：纹理画在**底边**上方，像石头的茬口。
            # 画在顶上会和"地面草地"撞衫——天花板顶上长草很出戏。
            hatch = (232, 228, 218)
            step = 13
            for i in range(1, tile // step + 1):
                hx = x + i * step - 4 + int(self._hash(col, row, i + 7) * 3)
                bottom = y + tile - 8 - int(self._hash(col, row, i + 60) * 4)
                pygame.draw.line(surface, hatch, (hx, bottom), (hx, bottom - 16), 1)

        # 顶线：分段微抖，看起来像手画的
        if above_air:
            pts = []
            for seg in range(0, tile + 1, 8):
                jitter = int(self._hash(col * 8 + seg, row, 7) * 3) - 1
                pts.append((x + seg, y + 1 + jitter))
            pygame.draw.lines(surface, config.COLOR_INK, False, pts, 3)

        # 底边线：只画"脚下是空的"那些格子——悬空岩板的底面。
        # 不画的话，天花板就是一大片没有边界的浅色，玩家看不出那是一块
        # 会掉石头的岩板。（M6 加天花板时发现的：原本只画顶面与侧面。）
        if below_air:
            pts = []
            for seg in range(0, tile + 1, 8):
                jitter = int(self._hash(col * 8 + seg, row, 11) * 3) - 1
                pts.append((x + seg, y + tile - 2 + jitter))
            pygame.draw.lines(surface, config.COLOR_INK, False, pts, 3)

        # 侧边线：只有临空一侧才画，避免内部出现多余竖线
        if left_air:
            pygame.draw.line(surface, config.COLOR_INK, (x + 1, y + 2),
                             (x + 1, y + tile), 2)
        if right_air:
            pygame.draw.line(surface, config.COLOR_INK, (x + tile - 1, y + 2),
                             (x + tile - 1, y + tile), 2)

    def draw(self, surface, camera, show_prompt=True):
        """画地图：地形整块 blit，会动的部分单独画。"""
        ox, oy = camera.offset
        surface.blit(self.bg, (ox, oy))

        for coin in self.coins:
            if coin["taken"]:
                continue
            bob = int(round(math.sin(self.time * 3.0 + coin["phase"]) * 3))
            cx = coin["rect"].centerx + ox
            cy = coin["rect"].centery + oy + bob
            self._draw_coin(surface, cx, cy)

        for cp in self.checkpoints:
            self._draw_checkpoint(surface, cp, ox, oy)
        for it in self.gliders:
            if not it["taken"]:
                self._draw_glider_item(surface, it, ox, oy)
        for p in self.platforms:
            self._draw_platform(surface, p, ox, oy)
        # 伪装砖就是地板，紧跟平台之后画；塌掉的位置画虚线，让"会再长回来"
        # 这件事在画面上说清楚
        for b in self.bricks:
            b.draw(surface, ox, oy)

        for s in self.signs:
            self._draw_sign(surface, s, ox, oy)
        for n in self.npcs:
            self._draw_npc(surface, n, ox, oy)
        for b in self.bats:
            b.draw(surface, ox, oy)
        for u in self.ufos:
            u.draw(surface, ox, oy)
        for s in self.rock_spawners:
            s.draw(surface, ox, oy)
        for t in self.twins:
            t.draw(surface, ox, oy)
        for r in self.rotors:
            r.draw(surface, ox, oy)
        for h in self.hammers:
            h.draw(surface, ox, oy)
        for s in self.drop_spikes:
            s.draw(surface, ox, oy)
        # 突墙画在角色之前（world 整体先于玩家绘制）：墙"从地里长出来"时
        # 应该是把角色挡住，而不是糊在角色脸上。
        for w in self.risers:
            w.draw(surface, ox, oy)
        for w in self.walkers:
            w.draw(surface, ox, oy)
        for r in self.rocks:
            r.draw(surface, ox, oy)

        self._draw_goal(surface, ox, oy)
        if show_prompt:
            self._draw_focus_prompt(surface, ox, oy)

    def _draw_plank(self, surface, rect):
        """单向平台：一块薄板。顶面加粗线，让"能站"这件事一眼可见。

        板面用比纸底略深的米色而不是白色：纯白贴在纸底上看不出厚度，
        只剩两条线飘在空中，玩家会以为是背景装饰。
        """
        pygame.draw.rect(surface, (238, 233, 220), rect)
        pygame.draw.line(surface, config.COLOR_INK,
                         (rect.left, rect.top + 1), (rect.right, rect.top + 1), 3)
        pygame.draw.line(surface, (168, 164, 154),
                         (rect.left, rect.bottom), (rect.right, rect.bottom), 2)

    def _draw_hazard(self, surface, col, row, ch):
        """危险格：地刺 / 天花板刺 / 水。颜色用功能色，不参与美术配色。"""
        tile = config.TILE
        x, y = col * tile, row * tile
        if ch == "~":
            # 整格铺满而不是内缩：内缩 2px 会让相邻两格之间留下纸色细缝，
            # 一片水坑看起来像一排独立的小方块。
            rect = pygame.Rect(x, y, tile, tile)
            pygame.draw.rect(surface, config.COLOR_WATER, rect)
            for k in (0, 1):
                pts = []
                # 取到 tile 为止（含右边界）：只画到 56 的话，每格末尾空 8px，
                # 整片水会变成一排虚线。
                for seg in range(0, tile + 1, 8):
                    yy = y + 18 + k * 22 + int(2.4 * math.sin((x + seg) / 9.0))
                    pts.append((x + seg, yy))
                pygame.draw.lines(surface, (140, 176, 196), False, pts, 2)
            # 只在"邻格不是水"的一侧描边。每格都描边的话，一片水坑会变成
            # 一排蓝色方格，看着像瓷砖而不是水。
            edges = (((rect.left, rect.top), (rect.left, rect.bottom)),
                     ((rect.right, rect.top), (rect.right, rect.bottom)),
                     ((rect.left, rect.top), (rect.right, rect.top)),
                     ((rect.left, rect.bottom), (rect.right, rect.bottom)))
            neighbours = ((-1, 0), (1, 0), (0, -1), (0, 1))
            for (a, b), (dc, dr) in zip(edges, neighbours):
                if self.cell_at_px(x + dc * tile + tile // 2,
                                   y + dr * tile + tile // 2) != "~":
                    pygame.draw.line(surface, (140, 176, 196), a, b, 2)
            return

        # 尖刺：四颗齿，齿高 24px，贴着格子下沿（'^'）或上沿（'v'）
        base = y + tile - 2 if ch == "^" else y + 2
        tip = base - 24 if ch == "^" else base + 24
        for i in range(4):
            x0 = x + i * 16
            pts = [(x0 + 1, base), (x0 + 8, tip), (x0 + 15, base)]
            pygame.draw.polygon(surface, config.COLOR_DANGER, pts)
            pygame.draw.polygon(surface, config.COLOR_INK, pts, 2)

    def _draw_bouncer(self, surface, col, row):
        """弹跳板：底板 + 弹簧 + 三个朝上的箭头。

        物理判定面就在底板顶面（格子底部往上 8px），所以底板必须画在
        玩家脚下那一层，不能悬空——否则"明明站在地上却被弹飞"很怪。
        """
        tile = config.TILE
        x = col * tile
        foot = (row + 1) * tile          # 脚下地面的上表面
        board = pygame.Rect(x + 4, foot - 10, tile - 8, 10)
        pygame.draw.rect(surface, (255, 255, 255), board)
        pygame.draw.rect(surface, config.COLOR_INK, board, 2)
        pygame.draw.line(surface, config.COLOR_INK, (board.left, board.top + 1),
                         (board.right, board.top + 1), 3)

        # 弹簧：一格来回的折线，从底板往下塞进地面一点，暗示"被压住"
        pts = []
        for i in range(5):
            pts.append((x + 14 + i * 9, board.top - 6 + (i % 2) * 8))
        pygame.draw.lines(surface, config.COLOR_INK, False, pts, 2)

        for i in (0, 1, 2):
            ax = x + 16 + i * 16
            ay = board.top - 18
            pygame.draw.line(surface, config.COLOR_CAMP, (ax, ay + 6), (ax, ay), 2)
            pygame.draw.lines(surface, config.COLOR_CAMP, False,
                              [(ax - 3, ay + 3), (ax, ay), (ax + 3, ay + 3)], 2)

    def _draw_checkpoint(self, surface, cp, ox, oy):
        """篝火：熄灭是灰的，点亮后暖橙 + 一圈跳动的小火苗。"""
        r = cp["rect"].move(ox, oy)
        img = self.camp_img if cp["active"] else self.camp_dim_img
        if img is not None:
            surface.blit(img, (r.centerx - img.get_width() // 2,
                               r.bottom - img.get_height()))
        else:
            # 兜底：手绘木堆
            color = config.COLOR_CAMP if cp["active"] else (196, 192, 184)
            pygame.draw.line(surface, config.COLOR_INK, (r.left + 4, r.bottom - 6),
                             (r.right - 4, r.bottom - 20), 3)
            pygame.draw.line(surface, config.COLOR_INK, (r.left + 4, r.bottom - 20),
                             (r.right - 4, r.bottom - 6), 3)
            pygame.draw.polygon(surface, color,
                                [(r.centerx, r.bottom - 26),
                                 (r.centerx + 9, r.bottom - 40),
                                 (r.centerx, r.bottom - 52),
                                 (r.centerx - 9, r.bottom - 40)])

        if not cp["active"]:
            return
        # 点亮后往上飘三颗火星。为什么不画"火苗"：素材本身的火焰已经画在
        # 贴图里了，再叠几笔只会糊成一团；火星在贴图上方的空白处，看得清
        # 又不需要额外贴图，还能让静态的篝火有点生气。
        for k in range(3):
            t = (self.time * 0.8 + cp["phase"] * 0.3 + k * 0.34) % 1.0
            sx = r.centerx + int(5.0 * math.sin((self.time + k) * 2.6))
            sy = r.bottom - 54 - int(t * 30)
            rad = max(1, int(3.0 * (1.0 - t)))
            pygame.draw.circle(surface, config.COLOR_CAMP, (sx, sy), rad)

    def _draw_glider_item(self, surface, it, ox, oy):
        """地上的滑翔伞道具：小伞面 + 两条绳 + 握把，上下轻轻浮动。

        素材包里没有道具图，代码画反而更统一——和篝火的兜底绘制是同一套语言。
        """
        bob = int(round(math.sin(self.time * 2.6 + it["phase"]) * 3))
        cx = it["pos"][0] + ox
        cy = it["pos"][1] + oy + bob
        pts = draw_canopy(surface, cx, cy - 2, half_w=18, height=13)
        grip = (cx, cy + 12)
        pygame.draw.line(surface, config.COLOR_INK, pts[0], grip, 1)
        pygame.draw.line(surface, config.COLOR_INK, pts[-1], grip, 1)
        pygame.draw.circle(surface, config.COLOR_INK, grip, 2)

    def _draw_platform(self, surface, p, ox, oy):
        """移动平台：白底墨框的浮板 + 两个方向箭头。

        不用 super-sampled 圆角（compat.panel 的 smooth=True）：一次要 0.75ms，
        两块平台每帧就是 3ms，为了几条圆角吃掉十分之一帧预算不值。
        """
        r = p.rect.move(ox, oy)
        compat.rounded_rect(surface, (255, 255, 255), r, radius=6, width=0)
        compat.rounded_rect(surface, config.COLOR_INK, r, radius=6, width=2)
        pygame.draw.line(surface, config.COLOR_INK, (r.left + 6, r.top + 1),
                         (r.right - 6, r.top + 1), 3)

        dx, dy = p.arrow()
        cx, cy = r.centerx, r.centery
        px, py = -dy, dx           # 与移动方向垂直的单位向量
        for along in (-13, 13):    # 两个 V 形箭头，像 » 一样指向移动方向
            tipx, tipy = cx + along * dx, cy + along * dy
            for side in (-5, 5):
                pygame.draw.line(
                    surface, config.COLOR_MUTED,
                    (tipx + px * side - dx * 5, tipy + py * side - dy * 5),
                    (tipx, tipy), 2)

    # ---- 告示牌 / NPC（M6）----
    def _draw_sign(self, surface, sign, ox, oy):
        """木牌：一根柱子 + 一块歪一点的板子 + 三行示意文字。

        板子上的"字"是三根短横线而不是真文字：64px 宽的板子上写中文既看不清
        也读不完，玩家真正要读的内容在按 E 之后的面板里。横线只承担
        "这是一块写着东西的牌子"这一个信息。
        """
        cell = sign["cell"].move(ox, oy)
        cx = cell.centerx
        base = cell.bottom - 2
        top = cell.top + 14
        pygame.draw.line(surface, config.COLOR_INK, (cx, base), (cx, top + 20), 3)

        board = pygame.Rect(cx - 25, top, 50, 34)
        pygame.draw.rect(surface, (252, 246, 232), board)
        pygame.draw.rect(surface, config.COLOR_SIGN, board, 3)
        for i, w in enumerate((30, 26, 18)):
            y = board.top + 8 + i * 9
            pygame.draw.line(surface, config.COLOR_SIGN,
                             (board.left + 10, y), (board.left + 10 + w, y), 2)

    def _draw_npc(self, surface, npc, ox, oy):
        """NPC：比主角矮一点、戴草帽、拄拐的火柴人。

        为什么要戴帽子、拿拐：素材里的角色全是同一副火柴人骨架，只靠动作
        区分"这是谁"根本不成立。帽子和拐是两笔成本最低的"身份标记"。
        """
        cell = npc["cell"].move(ox, oy)
        cx = cell.centerx
        base = cell.bottom - 2
        breathe = math.sin(self.time * 1.9 + npc["col"]) * 1.5
        head_y = base - 52 + breathe
        body_y = head_y + 18

        pygame.draw.circle(surface, config.COLOR_INK, (cx, int(head_y)), 8, 2)
        pygame.draw.line(surface, config.COLOR_INK, (cx, head_y + 8),
                         (cx, body_y + 16), 3)
        pygame.draw.line(surface, config.COLOR_INK, (cx, body_y + 2),
                         (cx - 11, body_y + 12), 3)
        pygame.draw.line(surface, config.COLOR_INK, (cx, body_y + 2),
                         (cx + 11, body_y + 6), 3)
        pygame.draw.line(surface, config.COLOR_INK, (cx, body_y + 16),
                         (cx - 9, base), 3)
        pygame.draw.line(surface, config.COLOR_INK, (cx, body_y + 16),
                         (cx + 9, base), 3)
        # 草帽：一条帽檐 + 一个帽顶三角形
        pygame.draw.line(surface, config.COLOR_NPC, (cx - 14, head_y - 7),
                         (cx + 14, head_y - 7), 3)
        pygame.draw.polygon(surface, config.COLOR_NPC,
                            [(cx - 9, head_y - 7), (cx, head_y - 20),
                             (cx + 9, head_y - 7)])
        # 拐杖
        pygame.draw.line(surface, config.COLOR_SIGN, (cx + 15, base),
                         (cx + 15, body_y + 2), 2)

    def _draw_focus_prompt(self, surface, ox, oy):
        """可交互目标头顶的小气泡：一个白底墨框的 E。

        只在真正进圈时出现。常驻的 "E" 会让画面到处是标签，玩家反而不知道该
        按哪个；出现即意味着"现在按有用"。
        """
        obj = self.focus
        if obj is None:
            return
        cell = obj["cell"].move(ox, oy)
        cx = cell.centerx
        y = cell.top - config.PROMPT_LIFT - 8
        bob = int(round(math.sin(self.time * 4.0) * 2))
        y += bob
        box = pygame.Rect(cx - 13, y - 14, 26, 24)
        compat.rounded_rect(surface, (255, 255, 255), box, radius=7, width=0)
        compat.rounded_rect(surface, config.COLOR_INK, box, radius=7, width=2)
        pygame.draw.polygon(surface, (255, 255, 255),
                            [(cx - 4, box.bottom - 1), (cx + 4, box.bottom - 1),
                             (cx, box.bottom + 6)])
        pygame.draw.line(surface, config.COLOR_INK,
                         (cx - 4, box.bottom), (cx, box.bottom + 6), 2)
        pygame.draw.line(surface, config.COLOR_INK,
                         (cx, box.bottom + 6), (cx + 4, box.bottom), 2)
        if self._prompt_font is None:
            self._prompt_font, _ = assets.font(15, True)
        img = self._prompt_font.render(u"E", True, config.COLOR_INK)
        surface.blit(img, (cx - img.get_width() // 2,
                           box.centery - img.get_height() // 2 - 1))

    def _draw_coin(self, surface, cx, cy):
        if self.coin_img is not None:
            rect = self.coin_img.get_rect(center=(cx, cy))
            surface.blit(self.coin_img, rect)
            return
        # 素材缺失兜底：墨线圆 + 亮黄填充
        pygame.draw.circle(surface, config.COLOR_COIN, (cx, cy), 11)
        pygame.draw.circle(surface, config.COLOR_INK, (cx, cy), 11, 2)

    def _draw_goal(self, surface, ox, oy):
        r = self.goal_rect.move(ox, oy)
        if self.flag_img is not None:
            surface.blit(self.flag_img, (r.x, r.bottom - self.flag_img.get_height()))
            return
        # 兜底：手绘旗杆 + 三角旗
        pygame.draw.line(surface, config.COLOR_INK, (r.centerx, r.top + 4),
                         (r.centerx, r.bottom), 3)
        pygame.draw.polygon(surface, config.COLOR_CAMP,
                            [(r.centerx, r.top + 4), (r.centerx + 26, r.top + 14),
                             (r.centerx, r.top + 24)])
        pygame.draw.polygon(surface, config.COLOR_INK,
                            [(r.centerx, r.top + 4), (r.centerx + 26, r.top + 14),
                             (r.centerx, r.top + 24)], 2)

    # ---- 调试 ----
    def describe(self):
        extra = []
        if self.checkpoints:
            extra.append(u"篝火 %d" % len(self.checkpoints))
        if self.platforms:
            extra.append(u"移动平台 %d" % len(self.platforms))
        if self.bouncers:
            extra.append(u"弹跳板 %d" % len(self.bouncers))
        if self.oneways:
            extra.append(u"单向平台 %d" % len(self.oneways))
        if self.hazard_boxes:
            extra.append(u"危险格 %d" % len(self.hazard_boxes))
        if self.gliders:
            extra.append(u"滑翔伞 %d" % len(self.gliders))
        if self.bats:
            extra.append(u"蝙蝠 %d" % len(self.bats))
        if self.ufos:
            extra.append(u"UFO %d" % len(self.ufos))
        if self.rock_spawners:
            extra.append(u"落石点 %d" % len(self.rock_spawners))
        if self.walkers:
            extra.append(u"走地怪 %d" % len(self.walkers))
        if self.rotors:
            extra.append(u"旋转刺轮 %d" % len(self.rotors))
        if self.hammers:
            extra.append(u"荡锤 %d" % len(self.hammers))
        if self.bricks:
            extra.append(u"伪装砖 %d" % len(self.bricks))
        if self.drop_spikes:
            extra.append(u"天花板落刺 %d" % len(self.drop_spikes))
        if self.risers:
            extra.append(u"突墙 %d" % len(self.risers))
        if self.twins:
            extra.append(u"二连落石 %d" % len(self.twins))
        if self.signs:
            extra.append(u"告示牌 %d" % len(self.signs))
        if self.npcs:
            extra.append(u"NPC %d" % len(self.npcs))
        tail = (u"，" + u"、".join(extra)) if extra else u""
        return (u"%s：%d x %d 格（%d x %d px），实心 %d 格合成 %d 个碰撞矩形，"
                u"金币 %d 枚，终点 1 个%s" % (
                    os.path.basename(self.path), self.width_tiles,
                    self.height_tiles, self.bounds.width, self.bounds.height,
                    len(self.solid_cells), len(self.solids), self.total_coins,
                    tail))
