# -*- coding: utf-8 -*-
"""背景音乐：循环播放 assets/audio/music/ 下的两首 CC0 曲目。

为什么 BGM 用文件、音效却用合成
--------------------------------
音效是"一次性、几十毫秒、只要能听出是什么"的声音，合成最划算；BGM 是
几十秒、要有和声走向和段落的，用代码堆出来只能是无调性噪音。两件事的
性价比完全不同，所以这里不硬套音效那套做法。

为什么是 ogg
------------
一段 70 秒的 22050 单声道 wav 要 3MB，ogg 只要 1.2MB。海龟环境的
pygame 1.9.6（SDL_mixer 带 vorbis）实测能播：music 流式播与 Sound 整段
读入两条路都验过，用的是前一条——流式不占内存，只是不能精确 seek。

播放器不抛异常
--------------
没有声卡、文件缺失、格式不支持，都只让 available 变成 False 并记下原因，
游戏照常能玩。和 Audio 一个口径：调用方不需要 try/except。
"""

import os

import pygame

import config

SAMPLE_RATE = 22050
AUDIO_DIR = os.path.join(config.ASSET_DIR, "audio")

# 曲目名 -> (相对 assets 的路径, 增益)
# 增益不是"音量"：两首曲子的响度不在一个水平上（菜单那首混得更满），
# 单独乘一个系数，切场景时不会突然变响。
TRACKS = {
    "menu": ("music/bgm_menu.ogg", 0.55),
    "game": ("music/bgm_game.ogg", 0.50),
}


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


def track_names():
    return sorted(TRACKS.keys())


def track_path(name):
    rel = TRACKS[name][0]
    return os.path.join(AUDIO_DIR, rel.replace("/", os.sep))


class Music(object):
    """BGM 播放器。App 持有一个，场景通过 app.music 调用。"""

    def __init__(self, enabled=True, volume=0.6):
        self.available = False
        self.volume = _clamp01(volume)
        self.muted = False
        self.enabled = bool(enabled)
        # track 是"想播哪一首"，_playing 是"现在真的在响"。
        # 两者分开，是为了让"静音 / 音量 0 时切关"也能记住该放哪首：
        # 把音量拉回来的那一刻直接补上，而不是停在无声的关卡里。
        self.track = None
        self._playing = False
        self._paused = False
        self._error = ""
        if self.enabled and self.volume > 0.0:
            self._init()

    # ------------------------------------------------------------ 设备
    def _init(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=SAMPLE_RATE, size=-16,
                                  channels=1, buffer=512)
            if not pygame.mixer.get_init():
                self._error = u"mixer 未初始化"
                return
            self.available = True
        except Exception as exc:          # 没有设备 / 驱动不支持 / 被独占
            self._error = u"%s" % exc
            self.available = False

    @property
    def status(self):
        if not self.enabled:
            return u"设置里已关闭"
        if not self.available:
            return u"不可用（%s）" % (self._error or u"未知原因")
        now = self.track or u"无"
        return u"可用，音量 %d%%（当前 %s）" % (
            int(round(self.volume * 100)), now)

    # ------------------------------------------------------------ 播放
    def play(self, name):
        """切到某一首并循环。同一首正在播时什么都不做。

        返回是否真的在响（自检与调试用）。
        """
        if name not in TRACKS:
            return False
        if name == self.track and self._playing:
            return True
        if not self.available or self.muted or self.volume <= 0.0:
            # 记住想播哪首：音量拉回来 / 取消静音时补播，见 set_volume。
            self.track = name
            return False
        path = track_path(name)
        if not os.path.exists(path):
            self._error = u"缺文件 %s" % TRACKS[name][0]
            self.available = False
            return False
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self._effective_volume(name))
            pygame.mixer.music.play(-1)
        except Exception as exc:
            self._error = u"%s" % exc
            self.available = False
            return False
        self.track = name
        self._playing = True
        self._paused = False
        return True

    def stop(self, fade_ms=320):
        """淡出并停。切场景时不用——直接换曲更自然；这里给"游戏结束"用。"""
        if self.available and self._playing:
            try:
                if fade_ms:
                    pygame.mixer.music.fadeout(fade_ms)
                else:
                    pygame.mixer.music.stop()
            except Exception:
                pass
        self._playing = False
        self._paused = False
        self.track = None

    def pause(self):
        if self.available and self._playing and not self._paused:
            try:
                pygame.mixer.music.pause()
                self._paused = True
            except Exception:
                pass

    def resume(self):
        if self.available and self._playing and self._paused:
            try:
                pygame.mixer.music.unpause()
                self._paused = False
            except Exception:
                pass

    # ------------------------------------------------------------ 音量
    def _effective_volume(self, name=None):
        name = name or self.track
        if name not in TRACKS:
            return 0.0
        if self.muted:
            return 0.0
        return _clamp01(self.volume * TRACKS[name][1])

    def set_volume(self, ratio):
        self.volume = _clamp01(ratio)
        if self.available:
            try:
                pygame.mixer.music.set_volume(self._effective_volume())
            except Exception:
                pass
        # 之前是"因为音量 0 / 静音"没播上的，现在补上。
        if self.track and not self._playing and self.volume > 0.0 \
                and not self.muted:
            self.play(self.track)

    def toggle_mute(self):
        """静音开关。静音时保留播放进度，只是把音量降到 0。"""
        self.muted = not self.muted
        if self.available:
            try:
                pygame.mixer.music.set_volume(self._effective_volume())
            except Exception:
                pass
        if not self.muted and self.track and not self._playing:
            self.play(self.track)
        return self.muted
