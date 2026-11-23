# -*- coding: utf-8 -*-
"""玩家：输入快照、状态机、像素级物理。

设计要点（README §5 手感参数 / §19 M2 验收）：
  - **物理与渲染分离**：本模块不画任何东西，只维护位置与速度
  - **输入与 pygame 解耦**：InputState 是纯数据对象，测试可注入任意按键序列，
    这是"土狼时间和跳跃缓冲各有专门测试"能成立的前提
  - **固定步长**：update(dt) 的 dt 恒为 config.FIXED_DT，所有积分都按它算

坐标约定：y 向下为正，因此向上为负速度（JUMP_SPEED 是负数）。
"""

import pygame

import config


def _approach(value, target, delta):
    """把 value 以 delta 的步长逼近 target，不越过。"""
    if value < target:
        return min(value + delta, target)
    if value > target:
        return max(value - delta, target)
    return value


class InputState(object):
    """一帧的输入快照。

    jump_pressed / jump_released 是**边沿**，被 Player 消费一次后置 False，
    所以同一帧跑多步 update 也只会触发一次跳跃。
    """

    def __init__(self):
        self.axis = 0.0          # -1 左 / 0 静止 / +1 右
        self.jump_held = False   # 当前是否按住
        self.jump_pressed = False
        self.jump_released = False
        self.dash_pressed = False

    def release_edges(self):
        self.jump_pressed = False
        self.jump_released = False
        self.dash_pressed = False


class Player(object):
    """火柴人玩家。碰撞盒 26x70，比视觉略窄，避免"看着还有缝却卡住"。"""

    WIDTH = 26
    HEIGHT = 70
    # 竖直方向只擦到这么多像素，就当作"没碰上"放过去。
    # 移动平台会主动扫过玩家的头顶/脚底，这个阈值以下做任何位置修正都会
    # 变成一次看得见的瞬移（或被按进地面），而放着不管玩家自己察觉不到。
    SKIM_PX = 6.0
    # 横向那一步的容差要更紧：这里是"算不算撞墙"，放宽到 6px 就允许人
    # 侧身滑进墙里半个身子（实测穿模帧数从 0 涨到几十）。4px 只够吃掉
    # 平台边缘扫过来的那点重叠。
    SIDE_SKIM_PX = 4.0

    def __init__(self, x, y):
        self.spawn = (float(x), float(y))
        self.reset()

    def reset(self):
        self.x, self.y = self.spawn
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = False
        self.coyote = 0.0
        self.jump_buffer = 0.0
        self.jumping = False
        self.facing = 1
        self.land_timer = 0.0
        self.jump_count = 0

        # ---- 冲刺（README §5，原排 M5，按需求提前到 M2.6）----
        self.dash_time = 0.0      # 剩余冲刺时间，>0 表示正在冲刺
        self.dash_cd = 0.0        # 冷却剩余
        self.dash_dir = 1
        self.dash_count = 0

        # ---- 机关（M4）----
        # 弹跳板只改 vy，不改位置；bounce_count 给自检用来验证"一次落下只弹一次"
        self.bounce_cd = 0.0
        self.bounce_count = 0

        # ---- 动画状态（纯逻辑，不持有任何 Surface）----
        self.anim_state = "idle"    # idle / run / jump
        self.anim_frame = 0
        self.anim_phase = 0.0       # 跑步用位移累加，避免速度变化时打滑
        self.anim_time = 0.0
        

    # ---------------------------------------------------------------- 几何
    @property
    def rect(self):
        return pygame.Rect(int(round(self.x)), int(round(self.y)),
                           self.WIDTH, self.HEIGHT)

    # ---------------------------------------------------------------- 主更新
    def update(self, dt, inp, solids, oneways=None, bouncers=None):
        """一步物理。

        ``solids``   实心矩形（含地图地形与移动平台）
        ``oneways``  单向平台：只在下落且出发时脚底不低于顶面时挡住
        ``bouncers`` 弹跳板：踩到就把 vy 换成向上初速，本身不算地面

        三个参数都允许 None，M2 起的旧调用（只传 solids）继续有效。
        """
        # 记住"进来时是否在空中"。落地反馈必须靠这个差值判断，
        # 不能用 self.on_ground 现查：_move_vertical 内部已经把
        # on_ground 置 True 了，事后再判 if not on_ground 永远为假。
        was_grounded = self.on_ground

        self.bounce_cd = max(0.0, self.bounce_cd - dt)

        # 1. 土狼时间：在地面时恒为满，离地后开始倒计时
        if self.on_ground:
            self.coyote = config.COYOTE_TIME
        else:
            self.coyote = max(0.0, self.coyote - dt)

        # 2. 跳跃缓冲倒计时
        self.jump_buffer = max(0.0, self.jump_buffer - dt)

        # 3. 按下边沿写入缓冲（无条件消费，保证一次按键只记一次）
        if inp.jump_pressed:
            self.jump_buffer = config.JUMP_BUFFER_TIME
            inp.jump_pressed = False

        # 4. 冲刺：冷却计时 + 触发。
        #    边沿在这里就消费掉，保证一帧（含多步 update）只可能冲一次。
        self.dash_cd = max(0.0, self.dash_cd - dt)
        if inp.dash_pressed:
            inp.dash_pressed = False
            if self.dash_cd <= 0.0 and self.dash_time <= 0.0:
                self._start_dash(inp.axis)
        dashing = self.dash_time > 0.0

        # 5. 水平速度：冲刺期间接管，否则正常加速 / 减速
        if dashing:
            self.dash_time = max(0.0, self.dash_time - dt)
            self.vx = self.dash_dir * config.DASH_SPEED
            # 冻结竖直速度：地面冲刺贴地直冲，空中冲刺走直线不会往下沉
            self.vy = 0.0
            self.jumping = False
        elif inp.axis != 0.0:
            self.facing = 1 if inp.axis > 0 else -1
            accel = config.GROUND_ACCEL if self.on_ground else config.AIR_ACCEL
            self.vx = _approach(self.vx, inp.axis * config.RUN_SPEED, accel * dt)
        else:
            decel = config.GROUND_DECEL if self.on_ground else config.AIR_ACCEL * 0.6
            self.vx = _approach(self.vx, 0.0, decel * dt)

        # 6. 水平移动与碰撞
        self._move_horizontal(self.vx * dt, solids)

        # 撞墙立刻收招，否则会贴着墙把剩余冲刺时间白白耗完
        if dashing and self.vx == 0.0:
            self.dash_time = 0.0
            dashing = False

        # 7. 起跳：有缓冲，且（在地面 或 还在土狼窗口内）。冲刺中不接受起跳
        if (not dashing) and self.jump_buffer > 0.0 \
                and (self.on_ground or self.coyote > 0.0):
            self.vy = config.JUMP_SPEED
            self.on_ground = False
            self.coyote = 0.0      # 起跳后清零，否则 0.1s 内会变成二段跳
            self.jump_buffer = 0.0
            self.jumping = True    # 标记"处于可被切短的上升段"
            self.jump_count += 1

        # 8. 松开切跳：只在上升段、且只切一次
        if inp.jump_released:
            inp.jump_released = False
            if self.vy < 0.0 and self.jumping:
                self.vy *= config.JUMP_CUT
                self.jumping = False

        # 9. 重力：上升用 GRAVITY_UP，按住时再乘 0.85，滞空更久。
        #    冲刺期间跳过——否则 vy 每帧又被拉回正值，冻结就没意义了。
        if not dashing:
            if self.vy < 0.0:
                g = config.GRAVITY_UP
                if inp.jump_held and self.jumping:
                    g *= config.JUMP_HOLD_GRAVITY_SCALE
            else:
                g = config.GRAVITY_DOWN
            self.vy = min(self.vy + g * dt, config.MAX_FALL_SPEED)

        # 10. 垂直移动与碰撞
        self._move_vertical(self.vy * dt, solids, oneways, bouncers)

        # 11. 脚下贴合。
        #     静止站立时 vy 很小，位移不足 1 像素，矩形根本没动，
        #     光靠 colliderect 会漏判 → on_ground 每帧 True/False 闪烁，
        #     表现为站在边缘"抖"。这里用 2px 向下探测把状态钉死。
        if self.vy >= 0.0:
            top = self._ground_top_below(solids, probe=2.0, oneways=oneways)
            if top is not None:
                self.y = top - self.HEIGHT
                self.vy = 0.0
                if not was_grounded:
                    self.land_timer = config.LAND_SQUASH_TIME
                self.on_ground = True
                self.jumping = False
            else:
                self.on_ground = False

        # 11.5 弹跳板：放在贴地之后，因为它要把刚被钉住的 vy 重新掀起来。
        #      判定条件要求 vy >= 0 —— 弹起后速度立刻为负，同一段下落不可能
        #      触发第二次，这是"不会每帧重复触发"的主要保证，冷却只是双保险。
        if self.vy >= 0.0 and bouncers:
            for pad in bouncers:
                if self._touch_top(pad):
                    self.bounce()
                    break

        if self.land_timer > 0.0:
            self.land_timer = max(0.0, self.land_timer - dt)

        # 12. 动画状态：只算「处于什么动作」和「第几帧」，不碰任何贴图
        self._update_anim(dt)

    # ---------------------------------------------------------------- 冲刺
    def _start_dash(self, axis):
        """起手冲刺。方向优先取当前输入，没有输入就沿用朝向。"""
        d = 1 if axis > 0 else (-1 if axis < 0 else self.facing)
        self.dash_dir = d
        self.facing = d
        self.dash_time = config.DASH_TIME
        # 冷却从起手就开始算，不是冲刺结束才算——否则连按会越冲越密
        self.dash_cd = config.DASH_COOLDOWN
        self.dash_count += 1
        self.vy = 0.0
        self.jumping = False

    @property
    def dashing(self):
        return self.dash_time > 0.0

    def can_dash(self):
        return self.dash_cd <= 0.0 and self.dash_time <= 0.0

    # ---------------------------------------------------------------- 机关与重生
    def bounce(self, speed=None):
        """被弹跳板顶起。返回是否真的弹了（冷却中返回 False）。"""
        if self.bounce_cd > 0.0:
            return False
        speed = config.BOUNCE_SPEED if speed is None else speed
        self.vy = -abs(float(speed))
        self.on_ground = False
        self.jumping = False
        self.coyote = 0.0
        self.jump_buffer = 0.0
        self.bounce_cd = config.BOUNCE_COOLDOWN
        self.bounce_count += 1
        return True

    def stands_on(self, rect, tol=2.0):
        """是否站在 rect 的顶面上。移动平台靠它判断该不该带动玩家。"""
        if self.vy < 0.0:
            return False
        bottom = self.y + self.HEIGHT
        if self.x + self.WIDTH <= rect.left + 0.5 or self.x >= rect.right - 0.5:
            return False
        return abs(bottom - rect.top) <= tol

    def carry(self, dx, dy, solids):
        """被移动平台带动。

        刻意不复用 update 里的速度积分：这里只是"整体挪一格"，玩家自身的
        速度不该被平台改写。垂直方向走 _move_vertical，被天花板挡住时不会
        穿进平台，代价是会掉下去——比穿模好。
        """
        if dy:
            self._move_vertical(float(dy), solids)
            self.on_ground = True     # 随平台移动后仍贴在同一块板上
        if dx:
            self._move_horizontal(float(dx), solids)

    def teleport(self, x, y):
        """直接把角色挪到某处并清空速度，用于死亡重生与回检查点。

        不重置 jump_count / bounce_count / dash_count 之类的统计量：
        那些是"整关累计"，重生不该抹掉。
        """
        self.x, self.y = float(x), float(y)
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = False
        self.coyote = 0.0
        self.jump_buffer = 0.0
        self.jumping = False
        self.dash_time = 0.0
        self.land_timer = 0.0
        self.anim_state = "idle"
        self.anim_frame = 0
        self.anim_phase = 0.0

    def _touch_top(self, pad, slack=10.0):
        """脚底是否踩在 pad 顶面上（含"刚好掠过"的少量余量）。"""
        if self.x + self.WIDTH <= pad.left + 0.5 or self.x >= pad.right - 0.5:
            return False
        bottom = self.y + self.HEIGHT
        return pad.top - 4.0 <= bottom <= pad.top + slack

    # ---------------------------------------------------------------- 动画
    def _update_anim(self, dt):
        """推进动画相位。

        这里刻意不知道素材有几帧：anim_frame 只是累加出来的整数相位，
        由渲染层对它取模。替换素材（帧数变化）不需要改物理代码。

        跑步帧按**水平位移**推进而不是按时间，这样：
          - 速度越快步频越快，看着不会"滑步"
          - 减速时脚步自然变慢，而不是保持匀速迈腿
        """
        if self.dashing:
            # 冲刺用跑步帧快速播放：素材里没有专门的冲刺姿态，
            # 让腿"转得比平时快"比换成跳跃的举手姿势更像一回事
            state = "run"
        elif not self.on_ground:
            state = "jump"
        elif abs(self.vx) > config.RUN_ANIM_MIN_SPEED:
            state = "run"
        else:
            state = "idle"

        if state != self.anim_state:
            if state == "run" and not self.dashing:
                self.anim_phase = 0.0   # 重新起跑从第一帧开始，不接着上次相位
            self.anim_state = state

        if state == "run":
            self.anim_phase += abs(self.vx) * dt / config.RUN_STRIDE_PX
            self.anim_frame = int(self.anim_phase)
        else:
            self.anim_frame = 0

    @property
    def land_sink(self):
        """落地瞬间的下沉量（像素），用于纯 blit 偏移的落地反馈。

        素材里没有落地帧，`land.png` 实测是块地砖，不能当角色用。
        这里改用"整体下沉再回弹"，不需要额外贴图也不改缩放尺寸。
        """
        if self.land_timer <= 0.0 or config.LAND_SQUASH_TIME <= 0.0:
            return 0.0
        t = self.land_timer / config.LAND_SQUASH_TIME     # 1 -> 0
        return config.LAND_SINK_PX * t * t

    # ---------------------------------------------------------------- 碰撞
    def _move_horizontal(self, dx, solids):
        if dx == 0.0:
            return
        start_x = self.x
        self.x += dx
        r = self.rect
        for s in solids:
            if not r.colliderect(s):
                continue
            # 竖直方向只擦到一条边（升降台升起来压到头顶、或从下面兜住
            # 脚底）不算"撞墙"。不排除掉的话，横向那一步会把人从平台边上
            # 整块弹出去，直接弹进旁边的实心地形里。
            if self._v_overlap(r, s) <= self.SIDE_SKIM_PX:
                continue
            if start_x + self.WIDTH <= s.left + 1.0:
                self.x = float(s.left) - self.WIDTH
            elif start_x >= s.right - 1.0:
                self.x = float(s.right)
            else:
                # 从侧向挤进来（移动平台横向顶过来）：往穿透浅的一侧让。
                # 让出去的位置如果会压进别的实心（比如贴墙那一格），就换另
                # 一侧；两侧都不行就原地不动，绝不把人生塞进墙里。
                pen_left = (self.x + self.WIDTH) - s.left
                pen_right = s.right - self.x
                left_x = float(s.left) - self.WIDTH
                right_x = float(s.right)
                if pen_left < pen_right:
                    first, second = left_x, right_x
                else:
                    first, second = right_x, left_x
                if self._fits(first, self.y, solids, s):
                    self.x = first
                elif self._fits(second, self.y, solids, s):
                    self.x = second
                else:
                    self.x = start_x
            self.vx = 0.0
            r = self.rect

    def _v_overlap(self, rect, s):
        """两个矩形在竖直方向上的重叠厚度。"""
        return min(rect.bottom, s.bottom) - max(rect.top, s.top)

    def _fits(self, x, y, solids, ignore=None):
        """把玩家摆到 (x, y) 上会不会压进实心。

        原本就只擦着边的接触不算压进去——那种重叠是移动平台从头顶扫过去
        造成的，不该用来否掉所有候选位置。否则解算会一路往下试，最后挑中
        "落到地面底边"，人直接被塞到地图底下掉出去。判据是"新位置没有比
        原位置压得更深"，压深了照样不合格。
        """
        cand = pygame.Rect(int(round(x)), int(round(y)),
                           self.WIDTH, self.HEIGHT)
        old = self.rect
        for s in solids:
            if s is ignore:
                continue
            if not cand.colliderect(s):
                continue
            if old.colliderect(s):
                if self._v_overlap(old, s) <= self.SKIM_PX \
                        and self._v_overlap(cand, s) <= self.SKIM_PX:
                    continue
            return False
        return True

    def _eject_sideways(self, s, y, solids):
        """把玩家从 s 的横向范围里推出去，推得动返回 True。

        站在地面上被平台从头顶压下来时用：平台行程固定，早晚会压到底，
        竖向解算只能把人顶到平台顶面（一次 60px 以上的瞬移）或者按进地面
        （直接穿地掉出地图）。横向推出去是唯一既安全又符合直觉的解。
        """
        left_x = float(s.left) - self.WIDTH
        right_x = float(s.right)
        if abs(self.x - left_x) <= abs(self.x - right_x):
            order = (left_x, right_x)
        else:
            order = (right_x, left_x)
        for cand in order:
            if self._fits(cand, y, solids, s):
                self.x = cand
                return True
        return False

    def _resolve_down(self, s, start_bottom, before, solids):
        """下落撞到实体时，人该停在哪一条 y 上。

        老实现无条件按"落在顶面"解算。地形不动时这是对的，但移动平台会
        自己顶进玩家身体：升降台从上方压到头顶时，那颗 0.8px 的浅重叠会被
        当成"从上面落下来"，人被整块吸到台面上——从台底吸到台顶，实测一次
        101px，看起来就是"瞬移"。

        所以按"从哪一侧进来"分三种：
          脚底出发时就在顶面之上 → 正常落地；
          从底面进来（头顶被压）→ 站着就让到旁边，空中就擦过去；
          其余（平台升起来顶到脚底）→ 站回顶面，这就是电梯托人。
        """
        top = float(s.top) - self.HEIGHT
        if start_bottom <= s.top + 1.0:
            return top
        pen_top = (self.y + self.HEIGHT) - s.top      # 从顶面陷进去多深
        pen_bottom = s.bottom - self.y                # 从底面陷进去多深
        if pen_bottom < pen_top:
            # 从下面进来的
            if pen_bottom > self.SKIM_PX and self.on_ground:
                if self._eject_sideways(s, before, solids):
                    return before
            # 空中擦头，或者旁边根本让不出去：不做位置修正，擦着过去。
            # 真按最小穿透推，人会被按进脚下地面（实测穿地掉出地图）。
            # 返回 None 而不是当前 y：这一下不算"撞上"，下面那块地面还得
            # 照常解算，否则人会一直嵌在地面里。
            return None
        if self._fits(self.x, top, solids, s):
            return top
        return before

    def _move_vertical(self, dy, solids, oneways=None, bouncers=None):
        if dy == 0.0:
            return
        # 单步最多 8px：下落极限速度 1100px/s 约合 18px/帧，
        # 一次走完会直接穿过 20px 厚的薄平台。
        steps = int(abs(dy) / 8.0) + 1
        part = dy / steps
        # 出发时的脚底位置决定单向平台这次是否该挡人：从下往上穿时
        # 脚底在平台下方，此时不能挡；从上方落下来才挡。
        start_bottom = self.y + self.HEIGHT
        start_y = self.y
        for _ in range(steps):
            before = self.y
            self.y += part
            r = self.rect
            blocked = False
            for s in solids:
                if not r.colliderect(s):
                    continue
                if dy > 0:
                    new_y = self._resolve_down(s, start_bottom, before, solids)
                    if new_y is None:
                        # 擦边放过：不算撞上，继续检查剩下的实心
                        continue
                    self.y = new_y
                    # 只有真的停在顶面上才算落地；被从下方推出来不算
                    if abs(self.y + self.HEIGHT - s.top) < 0.51:
                        self.on_ground = True
                else:
                    # 向上：只有"从下往上顶到 s 的底边"才算撞天花板。
                    # 不加这个前提的话，被别的东西顶进地板里的人会被解算成
                    # "落到地板底面"——直接掉出地图。已经嵌在里面的情况也
                    # 一律不推，玩家自己往下走就能出来。
                    if start_y >= s.bottom - 1.0:
                        self.y = float(s.bottom)
                    else:
                        continue
                self.vy = 0.0
                blocked = True
                r = self.rect
            if not blocked and dy > 0:
                blocked = self._land_on_thin(r, start_bottom, oneways, bouncers)
            if blocked:
                return

    def _land_on_thin(self, rect, start_bottom, oneways, bouncers):
        """薄平台（单向平台 / 弹跳板）的落地判定。返回是否停住。"""
        if oneways:
            for s in oneways:
                if rect.colliderect(s) and start_bottom <= s.top + 1.0:
                    self.y = s.top - self.HEIGHT
                    self.vy = 0.0
                    self.on_ground = True
                    return True
        if bouncers:
            for s in bouncers:
                if rect.colliderect(s) and start_bottom <= s.top + 1.0:
                    self.y = s.top - self.HEIGHT
                    self.bounce()
                    return True
        return False

    def _ground_top_below(self, solids, probe=2.0, oneways=None):
        """返回脚下 probe 像素内最近的实体顶面 y，没有则 None。

        单向平台也算"脚下能站的面"：站在上面时与实心地面没有区别，
        区别只体现在从下方穿过时挡不挡人。
        """
        bottom = self.y + self.HEIGHT
        best = None
        for s in solids:
            # 水平必须有重叠，否则站边缘也会被判成踩到
            if self.x + self.WIDTH <= s.left + 0.01 or self.x >= s.right - 0.01:
                continue
            if bottom - 0.5 <= s.top <= bottom + probe:
                if best is None or s.top < best:
                    best = float(s.top)
        if oneways:
            for s in oneways:
                if self.x + self.WIDTH <= s.left + 0.01 or self.x >= s.right - 0.01:
                    continue
                if bottom - 0.5 <= s.top <= bottom + probe:
                    if best is None or s.top < best:
                        best = float(s.top)
        return best

    # ---------------------------------------------------------------- 调试
    def debug_lines(self):
        return [
            "pos  %.1f, %.1f" % (self.x, self.y),
            "vel  %.1f, %.1f" % (self.vx, self.vy),
            "state %s  coyote %.3f  buf %.3f"
            % ("GROUND" if self.on_ground else "AIR", self.coyote, self.jump_buffer),
            "jumps %d  facing %+d" % (self.jump_count, self.facing),
            "dash  %s  cd %.2f  n=%d"
            % ("ON" if self.dashing else "  ", self.dash_cd, self.dash_count),
            "bounce %d  cd %.2f" % (self.bounce_count, self.bounce_cd),
            "anim %s #%d  phase %.2f"
            % (self.anim_state, self.anim_frame, self.anim_phase),
        ]

    @property
    def dash_ready_ratio(self):
        """冷却进度 0..1（1 表示可用），HUD 画冷却弧用。"""
        if config.DASH_COOLDOWN <= 0.0:
            return 1.0
        return max(0.0, min(1.0, 1.0 - self.dash_cd / config.DASH_COOLDOWN))
