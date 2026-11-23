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
import config
import io_utils

# ---------------------------------------------------------------- 图例
# 与 README §11.2 完全一致。M3 只实现前四类，其余先解析出来占位，
# 等 M4/M5 接机关时直接用，不必回头改解析器。

TILE_SOLID = "#"
TILE_ONEWAY = "="
TILE_SPAWN = "P"
TILE_GOAL = "F"
TILE_COIN = "c"

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
    "S": u"告示牌",
    "N": u"NPC",
    "G": u"滑翔伞",
    "D": u"冲刺道具",
    "B": u"蝙蝠",
    "U": u"UFO",
    "M": u"水平移动平台",
    "m": u"垂直移动平台",
    "R": u"落石点",
    "?": u"伪装砖",
    "W": u"墙刺机关",
    "K": u"钥匙",
    "E": u"门",
}

# 危险格：M4 接死亡流程后生效，现在只解析出来
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
        self.others = []          # [(col, row, ch)]  已识别但暂未实现


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
            elif ch in HAZARD_CHARS:
                out.hazards.append((col, row, ch))
            elif ch not in (".", TILE_SOLID):
                out.others.append((col, row, ch))

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

        # 碰撞用矩形（合并过）；单向平台 M3 不参与碰撞，
        # 等 M4 做机关时按 vy>0 + 上一帧脚底在上方 的规则接进来。
        self.solids = _merge_cells(self.solid_cells)

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

        self.time = 0.0
        self.flag_img = None
        self.coin_img = None
        self._load_images()
        self.bg = self._bake()

    # ---- 加载 ----
    @classmethod
    def load(cls, path):
        return cls(path, _parse(path))

    def _load_images(self):
        """终点旗与金币贴图。缺失不影响能玩，绘制层会退回代码画。"""
        tile = config.TILE
        try:
            flag = assets.image("collectibles/tile_flag.png")
            scale = float(tile) / flag.get_height()
            self.flag_img = assets.smooth_scaled(flag, scale, "flag")
        except assets.AssetMissing:
            self.flag_img = None
        try:
            self.coin_img = assets.image_scaled("collectibles/tile_coin.png", 0.62)
        except assets.AssetMissing:
            self.coin_img = None

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
    def update(self, dt):
        self.time += dt

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

        # 顶线：分段微抖，看起来像手画的
        if above_air:
            pts = []
            for seg in range(0, tile + 1, 8):
                jitter = int(self._hash(col * 8 + seg, row, 7) * 3) - 1
                pts.append((x + seg, y + 1 + jitter))
            pygame.draw.lines(surface, config.COLOR_INK, False, pts, 3)

        # 侧边线：只有临空一侧才画，避免内部出现多余竖线
        if left_air:
            pygame.draw.line(surface, config.COLOR_INK, (x + 1, y + 2),
                             (x + 1, y + tile), 2)
        if right_air:
            pygame.draw.line(surface, config.COLOR_INK, (x + tile - 1, y + 2),
                             (x + tile - 1, y + tile), 2)

    def draw(self, surface, camera):
        """画地图：地形整块 blit，金币与终点单独画（要动）。"""
        ox, oy = camera.offset
        surface.blit(self.bg, (ox, oy))

        for coin in self.coins:
            if coin["taken"]:
                continue
            bob = int(round(math.sin(self.time * 3.0 + coin["phase"]) * 3))
            cx = coin["rect"].centerx + ox
            cy = coin["rect"].centery + oy + bob
            self._draw_coin(surface, cx, cy)

        self._draw_goal(surface, ox, oy)

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
        return (u"%s：%d x %d 格（%d x %d px），实心 %d 格合成 %d 个碰撞矩形，"
                u"金币 %d 枚，终点 1 个" % (
                    os.path.basename(self.path), self.width_tiles,
                    self.height_tiles, self.bounds.width, self.bounds.height,
                    len(self.solid_cells), len(self.solids), self.total_coins))
