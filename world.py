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
    "?": u"伪装砖",
    "W": u"墙刺机关",
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
        self.platforms = []       # [(col, row, ch)]  同字符连续段稍后合并
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
            elif ch == TILE_CHECK:
                out.checkpoints.append((col, row))
            elif ch == TILE_BOUNCE:
                out.bouncers.append((col, row))
            elif ch in ("M", "m"):
                out.platforms.append((col, row, ch))
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
        bw, bh = config.CHECKPOINT_BOX
        self.checkpoints = []
        for c, r in parsed.checkpoints:
            self.checkpoints.append({
                "col": c, "row": r,
                "rect": pygame.Rect(c * tile + (tile - bw) // 2,
                                    (r + 1) * tile - bh, bw, bh),
                "spawn": (c * tile + (tile - 26) // 2, (r + 1) * tile - 70),
                "active": False,
                "phase": (c * 0.37) % 6.28,
            })

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
    def update(self, dt):
        self.time += dt
        if self.platforms:
            for p in self.platforms:
                p.update(dt)

    def collision_solids(self):
        """本帧玩家要撞的实心矩形：地形 + 移动平台。

        返回的是内部复用的同一个 list，调用方不要保存或修改它。
        没有平台时直接返回地形表，连拼一遍都省了。
        """
        if not self.platforms:
            return self.solids
        self._dynamic_solids[:] = self.solids
        for p in self.platforms:
            self._dynamic_solids.append(p.rect)
        return self._dynamic_solids

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
        for cp in self.checkpoints:
            cp["active"] = False
        for p in self.platforms:
            p.offset = 0.0
            p.dir = 1
            p.dwell = 0.0
            p.rect.x, p.rect.y = p.origin
            p.delta = (0, 0)
        self.goal_reached = False
        self.time = 0.0

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
        for p in self.platforms:
            self._draw_platform(surface, p, ox, oy)

        self._draw_goal(surface, ox, oy)

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
            rect = pygame.Rect(x + 2, y + 2, tile - 4, tile - 4)
            pygame.draw.rect(surface, config.COLOR_WATER, rect)
            for k in (0, 1):
                pts = []
                for seg in range(0, tile, 8):
                    yy = y + 18 + k * 22 + int(2.4 * math.sin((x + seg) / 9.0))
                    pts.append((x + seg, yy))
                pygame.draw.lines(surface, (140, 176, 196), False, pts, 2)
            pygame.draw.rect(surface, (140, 176, 196), rect, 2)
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
        tail = (u"，" + u"、".join(extra)) if extra else u""
        return (u"%s：%d x %d 格（%d x %d px），实心 %d 格合成 %d 个碰撞矩形，"
                u"金币 %d 枚，终点 1 个%s" % (
                    os.path.basename(self.path), self.width_tiles,
                    self.height_tiles, self.bounds.width, self.bounds.height,
                    len(self.solid_cells), len(self.solids), self.total_coins,
                    tail))
