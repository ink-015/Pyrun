# -*- coding: utf-8 -*-
"""存档：每关的最佳成绩与解锁进度。

四条硬规矩（都吃过教训）：

1. **坏了也要能启动。**`io_utils.read_json` 读失败返回 None，这里把它当成
   新玩家，而不是弹一个错误框让人进不去游戏。存档是辅助品，不是前置条件。
2. **写入必须原子。** 用 `io_utils.write_json`（临时文件 + os.replace）。
   直接 open('w') 时按 Alt+F4，留下的半个 json 会让下次启动丢全部进度。
3. **只存"最好的一次"，不存历史。** 跑酷的乐趣是刷新自己的记录；存一堆
   历史局反而让人不知道该跟哪个比。三项分开记：最快、最多金币、最少死。
4. **金币记录跟总数绑定。** 关卡加了几枚金币之后，旧的 "11/11" 不能
   直接跟新的 "12 枚" 比大小，所以 total 一变就作废重记。

存档结构（version 1）：

    {
      "version": 1,
      "all_unlocked": false,
      "settings": {"sfx": 7, "show_debug": false, "shake": true},
      "levels": {
        "l1": {"cleared": true, "time": 37.0, "coins": 10,
               "total": 12, "deaths": 0}
      }
    }

设置与进度放在同一个文件里：它们都是"这台机器上这个人的偏好"。
分成两个文件的话，清档时很容易只清了进度、留下"音量 0"，
下次进游戏以为音效坏了。
"""

import levels_catalog
import config
import io_utils

VERSION = 1

# 设置的默认值与合法范围。新增设置项必须在这里登记，否则 load 时会被
# 丢掉（玩家改过的值下次启动就没了，而这类 bug 极难复现）。
SETTINGS_SPEC = {
    "sfx": (7, 0, 10),        # 音效音量 0~10 档
    "music": (6, 0, 10),      # 背景音乐音量 0~10 档（默认比音效低一档）
    "show_debug": (False,),   # 进关是否默认显示调试面板
    "shake": (True,),         # 画面震动
}


def _default_settings():
    return dict((k, v[0]) for k, v in SETTINGS_SPEC.items())


def _blank_entry():
    return {"cleared": False, "time": None, "coins": -1,
            "total": -1, "deaths": None}


class Save(object):
    """单例式的存档对象，由 App 持有并传给各个场景。"""

    def __init__(self, path=None, readonly=False):
        self.path = path or config.SAVE_PATH
        # 只读模式：照常读真实存档（截图里该显示玩家的进度），但绝不落盘。
        # 截图脚本会把角色直接传送进终点，那 0.3 秒的假成绩要是写进去，
        # 玩家下次打开会看到"已通关 1/6"，而他从没跑过。
        self.readonly = readonly
        self.levels = {}
        self.all_unlocked = False
        self.settings = _default_settings()
        # 读取时丢弃了什么，用于启动日志。玩家看不到，但我需要知道
        # "为什么进度没了"是文件坏了还是读到旧版本。
        self.warnings = []
        self.dirty = False
        self.load()

    # ---------------------------------------------------------------- 读写
    def load(self):
        self.levels = {}
        self.all_unlocked = False
        self.settings = _default_settings()
        self.warnings = []
        data = io_utils.read_json(self.path, default=None)
        if data is None:
            return False              # 没有存档 = 新玩家，不是错误
        if not isinstance(data, dict):
            self.warnings.append(u"存档顶层不是对象，按新存档处理")
            return False

        ver = data.get("version")
        if ver != VERSION:
            # 只警告不拒绝：多出来的字段忽略、缺的字段补默认。
            # 因为丢进度比读到一个不认识的版本难受得多。
            self.warnings.append(u"存档版本 %r，当前 %r" % (ver, VERSION))

        self.all_unlocked = bool(data.get("all_unlocked", False))
        self._load_settings(data.get("settings"))
        raw = data.get("levels")
        if not isinstance(raw, dict):
            if raw is not None:
                self.warnings.append(u"levels 字段不是对象，已忽略")
            return True

        for key, item in raw.items():
            lv = levels_catalog.get(key)
            if lv is None or not isinstance(item, dict):
                self.warnings.append(u"丢掉无法识别的关卡记录：%r" % (key,))
                continue
            self.levels[key] = self._clean(item)
        return True

    def _load_settings(self, raw):
        """逐项校验设置。**不能整块丢弃**：存档里多一个不认识的键
        （旧版本、手改过）不该把音效音量也一起还原成默认。"""
        if raw is None:
            return
        if not isinstance(raw, dict):
            self.warnings.append(u"settings 不是对象，已用默认值")
            return
        for key, spec in SETTINGS_SPEC.items():
            if key not in raw:
                continue
            val = raw[key]
            if len(spec) == 3:                 # 数值项：默认, 下限, 上限
                lo, hi = spec[1], spec[2]
                # bool 是 int 的子类，True 会把音量变成 1 档——先排掉
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self.warnings.append(u"设置 %s 不是数字，已用默认值" % key)
                    continue
                self.settings[key] = max(lo, min(hi, int(round(val))))
            else:                              # 开关项
                self.settings[key] = bool(val)

    def _clean(self, item):
        """逐字段校验：一个坏字段不能带走整条记录。"""
        e = _blank_entry()
        e["cleared"] = bool(item.get("cleared", False))
        t = item.get("time")
        if isinstance(t, (int, float)) and t >= 0:
            e["time"] = float(t)
        elif t is not None:
            self.warnings.append(u"时间字段不是数字，已丢弃")
        c = item.get("coins")
        if isinstance(c, int) and c >= 0:
            e["coins"] = c
        tot = item.get("total")
        if isinstance(tot, int) and tot > 0:
            e["total"] = tot
        d = item.get("deaths")
        if isinstance(d, int) and d >= 0:
            e["deaths"] = d
        return e

    def write(self):
        """落盘。没有变化就不写——避免每次启动都改文件时间。"""
        if self.readonly or not self.dirty:
            return False
        data = {"version": VERSION,
                "all_unlocked": self.all_unlocked,
                "settings": self.settings,
                "levels": self.levels}
        try:
            io_utils.write_json(self.path, data)
        except Exception as exc:      # 磁盘满 / 只读目录，不该让游戏崩掉
            self.warnings.append(u"存档写入失败：%s" % exc)
            print(u" 存档     : 写入失败（%s）" % exc)
            return False
        self.dirty = False
        return True

    # ---------------------------------------------------------------- 查询
    def entry(self, key):
        return self.levels.get(key) or _blank_entry()

    def is_cleared(self, key):
        e = self.levels.get(key)
        return bool(e and e.get("cleared"))

    def best_time(self, key):
        return self.entry(key).get("time")

    def best_coins(self, key):
        return self.entry(key).get("coins")

    def best_deaths(self, key):
        return self.entry(key).get("deaths")

    def perfect(self, key):
        """满金币通关。选关界面用它画一颗星。"""
        e = self.entry(key)
        return bool(e.get("cleared") and e.get("coins", -1) >= 0
                    and e.get("coins") == e.get("total"))

    def unlocked(self, key):
        """第一关永远开放；其余要前一关通关。

        `all_unlocked` 是给"我已经通关了但想回去挑关玩"的兜底开关，
        也给试玩留了条不打断的路（见 scenes 里的 F2）。
        """
        if self.all_unlocked:
            return True
        idx = levels_catalog.index_of(key)
        if idx < 0:
            return False
        if idx == 0:
            return True
        prev = levels_catalog.at(idx - 1)
        return self.is_cleared(prev["key"])

    def cleared_count(self):
        return sum(1 for lv in levels_catalog.LEVELS
                   if self.is_cleared(lv["key"]))

    def first_uncleared(self):
        """"继续游戏"进哪一关：第一个没通关的；全通则回第一关。"""
        for lv in levels_catalog.LEVELS:
            if not self.is_cleared(lv["key"]):
                return lv
        return levels_catalog.first()

    def all_cleared(self):
        return self.cleared_count() >= levels_catalog.count()

    # ---------------------------------------------------------------- 写入
    def record(self, key, seconds, coins, total, deaths):
        """记一次**通关**。返回这次破了哪些纪录（用于结算面板）。

        返回形如 {"time": True, "coins": False, "deaths": True, "first": False}
        "new" 为 True 表示这是本关第一次通关。
        """
        if levels_catalog.get(key) is None:
            return {}
        e = self.levels.get(key)
        first = e is None or not e.get("cleared")
        if e is None:
            e = _blank_entry()
            self.levels[key] = e

        rec = {"first": first,
               "time": False, "coins": False, "deaths": False}

        # 金币总数变了（关卡改过）就作废旧的金币记录：11/11 跟 14 枚
        # 不可比，硬比会让玩家看到"退步"。
        if e.get("total") != total:
            e["coins"] = -1
            e["total"] = total

        if e.get("time") is None or seconds < e["time"]:
            e["time"] = round(float(seconds), 2)
            rec["time"] = True
        coins = max(0, int(coins))
        if coins > e.get("coins", -1):
            e["coins"] = coins
            rec["coins"] = True
        deaths = max(0, int(deaths))
        if e.get("deaths") is None or deaths < e["deaths"]:
            e["deaths"] = deaths
            rec["deaths"] = True

        e["cleared"] = True
        self.dirty = True
        # 第一次通关时顺手把"下一关"的状态刷新一下没有意义——
        # 解锁是算出来的（看前一关有没有 cleared），不需要存。
        self.write()
        return rec

    def set_all_unlocked(self, flag=True):
        self.all_unlocked = bool(flag)
        self.dirty = True
        self.write()

    # ---------------------------------------------------------------- 设置
    def get_setting(self, key):
        if key in self.settings:
            return self.settings[key]
        spec = SETTINGS_SPEC.get(key)
        return spec[0] if spec else None

    def set_setting(self, key, value):
        """改一项设置并立刻落盘。

        设置的写入频率是"按一下方向键一次"，不是每帧一次，直接写盘最简单；
        攒着不写会出现"调完音量直接关窗口，下次还是老的"。
        """
        spec = SETTINGS_SPEC.get(key)
        if spec is None:
            return False
        if len(spec) == 3:
            lo, hi = spec[1], spec[2]
            val = max(lo, min(hi, int(value)))
        else:
            val = bool(value)
        if self.get_setting(key) == val:
            return False
        self.settings[key] = val
        self.dirty = True
        self.write()
        return True

    def clear(self):
        """清空进度。只在调试入口里调用，界面上不给按钮——误触代价太大。"""
        self.levels = {}
        self.all_unlocked = False
        self.dirty = True
        self.write()

    # ---------------------------------------------------------------- 展示
    def summary(self):
        return u"已通关 %d / %d" % (self.cleared_count(),
                                    levels_catalog.count())
