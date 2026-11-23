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

    def release_edges(self):
        self.jump_pressed = False
        self.jump_released = False


class Player(object):
    """火柴人玩家。碰撞盒 26x70，比视觉略窄，避免"看着还有缝却卡住"。"""

    WIDTH = 26
    HEIGHT = 70

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
    def update(self, dt, inp, solids):
        # 记住"进来时是否在空中"。落地反馈必须靠这个差值判断，
        # 不能用 self.on_ground 现查：_move_vertical 内部已经把
        # on_ground 置 True 了，事后再判 if not on_ground 永远为假。
        was_grounded = self.on_ground

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

        # 4. 水平加速 / 减速
        if inp.axis != 0.0:
            self.facing = 1 if inp.axis > 0 else -1
            accel = config.GROUND_ACCEL if self.on_ground else config.AIR_ACCEL
            self.vx = _approach(self.vx, inp.axis * config.RUN_SPEED, accel * dt)
        else:
            decel = config.GROUND_DECEL if self.on_ground else config.AIR_ACCEL * 0.6
            self.vx = _approach(self.vx, 0.0, decel * dt)

        # 5. 水平移动与碰撞
        self._move_horizontal(self.vx * dt, solids)

        # 6. 起跳：有缓冲，且（在地面 或 还在土狼窗口内）
        if self.jump_buffer > 0.0 and (self.on_ground or self.coyote > 0.0):
            self.vy = config.JUMP_SPEED
            self.on_ground = False
            self.coyote = 0.0      # 起跳后清零，否则 0.1s 内会变成二段跳
            self.jump_buffer = 0.0
            self.jumping = True    # 标记"处于可被切短的上升段"
            self.jump_count += 1

        # 7. 松开切跳：只在上升段、且只切一次
        if inp.jump_released:
            inp.jump_released = False
            if self.vy < 0.0 and self.jumping:
                self.vy *= config.JUMP_CUT
                self.jumping = False

        # 8. 重力：上升用 GRAVITY_UP，按住时再乘 0.85，滞空更久
        if self.vy < 0.0:
            g = config.GRAVITY_UP
            if inp.jump_held and self.jumping:
                g *= config.JUMP_HOLD_GRAVITY_SCALE
        else:
            g = config.GRAVITY_DOWN
        self.vy = min(self.vy + g * dt, config.MAX_FALL_SPEED)

        # 9. 垂直移动与碰撞
        self._move_vertical(self.vy * dt, solids)

        # 10. 脚下贴合。
        #     静止站立时 vy 很小，位移不足 1 像素，矩形根本没动，
        #     光靠 colliderect 会漏判 → on_ground 每帧 True/False 闪烁，
        #     表现为站在边缘"抖"。这里用 2px 向下探测把状态钉死。
        if self.vy >= 0.0:
            top = self._ground_top_below(solids, probe=2.0)
            if top is not None:
                self.y = top - self.HEIGHT
                self.vy = 0.0
                if not was_grounded:
                    self.land_timer = config.LAND_SQUASH_TIME
                self.on_ground = True
                self.jumping = False
            else:
                self.on_ground = False

        if self.land_timer > 0.0:
            self.land_timer = max(0.0, self.land_timer - dt)

        # 11. 动画状态：只算「处于什么动作」和「第几帧」，不碰任何贴图
        self._update_anim(dt)

    # ---------------------------------------------------------------- 动画
    def _update_anim(self, dt):
        """推进动画相位。

        这里刻意不知道素材有几帧：anim_frame 只是累加出来的整数相位，
        由渲染层对它取模。替换素材（帧数变化）不需要改物理代码。

        跑步帧按**水平位移**推进而不是按时间，这样：
          - 速度越快步频越快，看着不会"滑步"
          - 减速时脚步自然变慢，而不是保持匀速迈腿
        """
        if not self.on_ground:
            state = "jump"
        elif abs(self.vx) > config.RUN_ANIM_MIN_SPEED:
            state = "run"
        else:
            state = "idle"

        if state != self.anim_state:
            if state == "run":
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
        self.x += dx
        r = self.rect
        for s in solids:
            if not r.colliderect(s):
                continue
            if dx > 0:
                self.x = s.left - self.WIDTH
            else:
                self.x = s.right
            self.vx = 0.0
            r = self.rect

    def _move_vertical(self, dy, solids):
        if dy == 0.0:
            return
        # 单步最多 8px：下落极限速度 1100px/s 约合 18px/帧，
        # 一次走完会直接穿过 20px 厚的薄平台。
        steps = int(abs(dy) / 8.0) + 1
        part = dy / steps
        for _ in range(steps):
            self.y += part
            r = self.rect
            blocked = False
            for s in solids:
                if not r.colliderect(s):
                    continue
                if dy > 0:
                    self.y = s.top - self.HEIGHT
                    self.on_ground = True
                else:
                    self.y = s.bottom
                self.vy = 0.0
                blocked = True
                r = self.rect
            if blocked:
                return

    def _ground_top_below(self, solids, probe=2.0):
        """返回脚下 probe 像素内最近的实体顶面 y，没有则 None。"""
        bottom = self.y + self.HEIGHT
        best = None
        for s in solids:
            # 水平必须有重叠，否则站边缘也会被判成踩到
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
            "anim %s #%d  phase %.2f"
            % (self.anim_state, self.anim_frame, self.anim_phase),
        ]
