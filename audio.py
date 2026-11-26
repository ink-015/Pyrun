# -*- coding: utf-8 -*-
"""音效：运行时合成，不读文件。

为什么不用 wav：`assets/audio/` 从 M0 起就是空目录，一直没往里放东西。
一个 0.2 秒的 22050Hz 单声道 wav 大约 9KB，九个音效就近 100KB，而合成
只要几十行。更要紧的是——一旦音效变成文件，就有了"文件丢了/路径错了/
海龟环境里没打包进去"这一整类问题，而它们全都表现为"没声音"，很难分清
是素材没找到还是音频设备没打开。

三条硬约束（都吃过教训）：

1. **没有音频设备也必须能玩。** 海龟环境、远程桌面、CI 机器上
   `pygame.mixer.init()` 会失败。这里把失败吸收成 ``available = False``，
   之后每次 ``play()`` 直接返回 False，调用方不需要 try。
2. **合成不能拖慢启动。** 每个音效在**第一次播放时**才生成并缓存。
   九个音效全在启动时算要 40~80ms，正好卡在"按下开始游戏"的体感上。
3. **同一个音效不能叠成噪音。** 连着吃五枚金币时五个音同时响会爆音，
   所以同名音效有 40ms 的节流；不同音效之间不节流（跳跃与金币要同时响）。

音色是"纸面手绘"的：以正弦为主，少量方波做撞击，全部短促（最长 0.4s）。
不做背景音乐——程序合成的循环旋律在这个画风里只会显得廉价。
"""

import array
import math
import time

import pygame

import config

# 22050 单声道足够了：音效最高才 1.5kHz，采样率翻倍只增加合成时间。
SAMPLE_RATE = 22050
CHANNELS = 12
# 同名音效的最小间隔。金币连吃时 40ms 大约相当于"三个音叠在一起"，
# 再多就听不出个数了，会糊成一段噪音。
SAME_SFX_GAP = 0.040

# 音效表：名字 -> 生成函数。函数在首次播放时才调用，返回值是 array('h')。
# 每个函数保持"纯计算"，不碰 pygame，方便自检直接验样本长度与峰值。
_SYNTH = {}


def _synth(name):
    def deco(fn):
        _SYNTH[name] = fn
        return fn
    return deco


def _envelope(t, dur, attack=0.004, decay=6.0, release=0.010):
    """指数衰减包络，带 4ms 淡入 + 10ms 淡出。

    没有淡入的话，波形从 0 突然跳到峰值，扬声器会"啪"一声——这是所有
    程序合成音效最常见也最烦人的问题。淡出同样必须有：指数衰减到
    0.25 秒时还剩三成幅度，直接截断就是第二个"啪"。

    琶音（_seq）里每个音各自做一遍淡出，接缝处才是干净的。
    """
    a = 1.0 if attack <= 0.0 else min(1.0, t / attack)
    r = 1.0
    if release > 0.0:
        r = min(1.0, max(0.0, (dur - t) / release))
    return a * r * math.exp(-decay * t)


def _sweep(f0, f1, dur, amp=0.5, decay=8.0, wave="sine", attack=0.004,
           noise=0.0):
    """扫频音：频率从 f0 线性走到 f1。

    用相位累加而不是 sin(2*pi*f*t)：后者在频率变化时相位会跳，
    听起来是"咔"的一下断成两截。
    """
    n = int(SAMPLE_RATE * dur)
    out = array.array("h", [0]) * n
    phase = 0.0
    rnd = 1103515245
    for i in range(n):
        t = i / float(SAMPLE_RATE)
        f = f0 + (f1 - f0) * (t / dur if dur > 0 else 1.0)
        phase += 2.0 * math.pi * f / SAMPLE_RATE
        if wave == "square":
            v = 1.0 if math.sin(phase) >= 0.0 else -1.0
        elif wave == "tri":
            v = 2.0 / math.pi * math.asin(math.sin(phase))
        else:
            v = math.sin(phase)
        if noise > 0.0:
            rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
            v = (1.0 - noise) * v + noise * ((rnd / 1073741823.0) - 1.0)
        out[i] = int(max(-1.0, min(1.0, v * amp * _envelope(t, dur, attack, decay))) * 32767)
    return out


def _seq(notes, dur_each, amp=0.4, decay=9.0, wave="sine"):
    """把几个音高首尾接起来（琶音）。notes 是频率列表。"""
    out = array.array("h")
    for f in notes:
        out.extend(_sweep(f, f, dur_each, amp=amp, decay=decay, wave=wave))
    return out


# ---------------------------------------------------------------- 音效定义
# 音量都留了余量（amp 0.35~0.5）：mixer 的全局音量再乘一次，
# 单个音效就顶到 1.0 的话，玩家把音量拉满会削波。

@_synth("jump")
def _s_jump():
    # 上扫 380→620：向上跳的音高走向要跟着动作，往下扫会听成"掉下去"。
    return _sweep(380.0, 620.0, 0.10, amp=0.34, decay=13.0)


@_synth("land")
def _s_land():
    # 低频短促 + 一点噪声：落地是"闷响"，不是"叮"。
    return _sweep(190.0, 78.0, 0.075, amp=0.40, decay=20.0, noise=0.25)


@_synth("coin")
def _s_coin():
    # 两段高音（B5→E6）：这是所有游戏里金币音的通用语言，改了就认不出。
    return _seq([988.0, 1319.0], 0.052, amp=0.26, decay=11.0)


@_synth("dash")
def _s_dash():
    # 纯噪声快速衰减 = 一阵风。不掺音高，冲刺是"位移"不是"音阶"。
    return _sweep(900.0, 900.0, 0.13, amp=0.30, decay=18.0, noise=1.0)


@_synth("stomp")
def _s_stomp():
    # 方波低扫：踩在怪头上的"噗"。
    return _sweep(240.0, 90.0, 0.10, amp=0.36, decay=17.0, wave="square")


@_synth("bounce")
def _s_bounce():
    # 三角波上扫：弹跳板是"被弹上去"，音高必须向上。
    # 用三角波而不是方波，是因为它比跳跃音更"厚"一点，听得出是机关弹的。
    return _sweep(260.0, 760.0, 0.12, amp=0.32, decay=13.0, wave="tri")


@_synth("glide")
def _s_glide():
    # 噪声 + 轻微下扫 = 布面张开的一阵风。音量压得比别的低：
    # 滑翔会持续几秒，开场音太响会盖住落点判断。
    return _sweep(760.0, 420.0, 0.18, amp=0.20, decay=9.0, noise=0.6)


@_synth("death")
def _s_death():
    # 长一点的下扫（0.38s），压得比死亡定格（0.45s）短一点点：
    # 音效还没放完人就重生了，会显得很赶；完全盖住又太吵。
    return _sweep(430.0, 72.0, 0.38, amp=0.42, decay=4.2, wave="square",
                  noise=0.15)


@_synth("camp")
def _s_camp():
    # 大三和弦上行：C5-E5-G5。点篝火是"存档"，要给一个明确的"完成"感。
    return _seq([523.0, 659.0, 784.0], 0.085, amp=0.30, decay=9.0)


@_synth("goal")
def _s_goal():
    # 四个音，最后落在高八度 C：结束感来自"回到主音"。
    return _seq([523.0, 659.0, 784.0, 1046.0], 0.115, amp=0.32, decay=6.5)


@_synth("ui")
def _s_ui():
    # 界面点击/移动光标。极短，不能抢戏。
    return _sweep(1400.0, 1400.0, 0.035, amp=0.18, decay=30.0)


# ---------------------------------------------------------------- 运行时
class Audio(object):
    """音效播放器。App 持有一个，场景通过 app.audio 调用。

    构造永不抛异常：没有音频设备时 available=False，一切调用变成空操作。
    """

    def __init__(self, enabled=True, volume=None):
        self.available = False
        self.volume = 0.7 if volume is None else _clamp01(volume)
        self.muted = False
        # enabled 只表示"允许出声"，与音量无关：音量调到 0 再拉回来时，
        # 必须还允许重新初始化设备。把两者混在一起的话，"音量 0 时启动"
        # 会让 enabled=False，之后玩家怎么拉音量都没有声音。
        self.enabled = bool(enabled)
        self._sounds = {}
        self._last = {}
        self._error = ""
        if self.enabled and self.volume > 0.0:
            self._init_mixer()

    def _init_mixer(self):
        try:
            # pygame.init() 会顺手把 mixer 开成 44100 / 立体声。我们不接受
            # 那个格式：样本是按 22050 单声道合成的，混着播会快一倍、音高
            # 高八度（听起来像"音效坏了"，很难联想到采样率）。
            # 全项目只有这里用 mixer，所以可以直接 quit 再按自己的参数开。
            got = pygame.mixer.get_init()
            if got and (abs(got[0] - SAMPLE_RATE) > 1 or got[2] != 1):
                pygame.mixer.quit()
                got = None
            if not got:
                pygame.mixer.init(frequency=SAMPLE_RATE, size=-16,
                                  channels=1, buffer=512)
            got = pygame.mixer.get_init()
            if not got:
                self._error = u"mixer 未初始化"
                return
            # 走到这里格式仍可能不符：个别驱动会强制自己的采样率。
            # 这种情况宁可不播，也不要放出变调的怪声。
            # get_init() 返回 (频率, 位深, 声道)，频率在第 0 位。
            if abs(got[0] - SAMPLE_RATE) > 1:
                self._error = u"采样率 %d != %d" % (got[0], SAMPLE_RATE)
                return
            pygame.mixer.set_num_channels(CHANNELS)
            self.available = True
        except Exception as exc:          # 没有设备 / 驱动不支持 / 被独占
            self._error = u"%s" % exc
            self.available = False

    # ------------------------------------------------------------ 播放
    def play(self, name):
        """播放一个音效。返回是否真的响了（自检与调试用）。"""
        if not self.available or self.muted or self.volume <= 0.0:
            return False
        if name not in _SYNTH:
            return False
        now = time.time()
        if now - self._last.get(name, 0.0) < SAME_SFX_GAP:
            return False
        snd = self._sounds.get(name)
        if snd is None:
            snd = self._build(name)
            if snd is None:
                return False
        self._last[name] = now
        ch = snd.play()
        return ch is not None

    def _build(self, name):
        try:
            samples = _SYNTH[name]()
            snd = pygame.mixer.Sound(buffer=samples.tobytes())
            snd.set_volume(self.volume)
            self._sounds[name] = snd
            return snd
        except Exception as exc:
            # 合成失败就整体关掉：每个音效都失败一次会拖慢每一帧
            self._error = u"合成 %s 失败：%s" % (name, exc)
            self.available = False
            return None

    # ------------------------------------------------------------ 设置
    def set_volume(self, ratio):
        self.volume = _clamp01(ratio)
        # 音量拉到 0 等同于静音，但**不在这里改 muted**：muted 是 M 键的
        # 临时开关，两者相互独立。否则"把音量拉到 0 再拉回来"会顺手把
        # 玩家按 M 静音的状态也解开，下次进游戏突然有声音。
        for snd in self._sounds.values():
            snd.set_volume(self.volume)
        if self.volume > 0.0 and self.enabled and not self.available \
                and not self.muted:
            # 玩家从 0 拉回来：这时候才值得再试一次 init（可能刚插上耳机）
            self._init_mixer()

    def toggle_mute(self):
        """M 键：静音开关。返回静音后的状态，给 toast 用。"""
        self.muted = not self.muted
        return self.muted

    @property
    def status(self):
        if not self.enabled:
            return u"未启用（截图 / 自检 / --no-audio）"
        if self.volume <= 0.0:
            return u"音量为 0"
        if self.available:
            return u"可用，音量 %d%%" % int(round(self.volume * 100))
        return u"不可用（%s）" % (self._error or u"未知原因")


def _clamp01(v):
    return max(0.0, min(1.0, float(v)))


def synth_peek(name):
    """给自检用：直接合成一次并返回样本，不依赖音频设备。"""
    fn = _SYNTH.get(name)
    return None if fn is None else fn()


def synth_names():
    return sorted(_SYNTH.keys())
