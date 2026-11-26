# -*- coding: utf-8 -*-
"""关卡目录：**关于关卡的元信息只有这一份**。

为什么单独一个文件：选关界面、连续挑战、存档解锁、README 表格都要知道
"一共有几关、按什么顺序、叫什么名字"。这些信息以前只存在于
`os.listdir(LEVEL_DIR)` 和三个不同的地方，加一关就要改三处，而且
目录扫描的顺序依赖文件名，`l10` 会排在 `l2` 前面。

这里的表是**权威顺序**：谁想遍历关卡就去问这里，不要自己 listdir。
文件不存在时会由 selftest / envcheck 报出来，不会在这里静默跳过——
少一关要看得见。
"""

import os

import config


# name   : 选关卡片上的名字（短，三到五个字）
# blurb  : 卡片下方一句话，说明这关在教什么
# 顺序就是通关顺序，也是解锁顺序。
LEVELS = [
    {"key": "l1", "file": "l1.txt", "name": u"热身跑",
     "blurb": u"跑、跳、冲刺，没有会动的东西"},
    {"key": "l2", "file": "l2.txt", "name": u"机关试炼",
     "blurb": u"地刺、弹跳板、移动平台"},
    {"key": "l3", "file": "l3.txt", "name": u"滑翔伞",
     "blurb": u"坑太宽，得从空中过去"},
    {"key": "l4", "file": "l4.txt", "name": u"夜路",
     "blurb": u"蝙蝠、落石，还有人在说话"},
    {"key": "l5", "file": "l5.txt", "name": u"机关实验室",
     "blurb": u"能踩的怪、旋转刀片、荡锤"},
    {"key": "l6", "file": "l6.txt", "name": u"暗算",
     "blurb": u"什么时候不能停，什么时候必须停"},
]

# 名字查表，避免每次线性找
_BY_KEY = dict((lv["key"], lv) for lv in LEVELS)


def count():
    return len(LEVELS)


def at(index):
    """按下标取关卡；越界返回 None（连续挑战跑到最后一关之后要用）。"""
    if 0 <= index < len(LEVELS):
        return LEVELS[index]
    return None


def get(key):
    return _BY_KEY.get(key)


def index_of(key):
    for i, lv in enumerate(LEVELS):
        if lv["key"] == key:
            return i
    return -1


def first():
    return LEVELS[0]


def next_of(key):
    """下一关；已经是最后一关则返回 None。

    刻意不循环：循环会让人"通关之后又回到第一关"，分不清自己是
    打完了还是被踢回去了。到终点就该有个终点。
    """
    return at(index_of(key) + 1)


def path_of(key_or_level):
    """把 key 或目录项转成绝对路径。"""
    lv = key_or_level if isinstance(key_or_level, dict) else get(key_or_level)
    if lv is None:
        return config.DEFAULT_LEVEL
    return os.path.join(config.LEVEL_DIR, lv["file"])


def path_to_key(path):
    """从路径反查 key；认不出来时返回 ""。"""
    if not path:
        return ""
    base = os.path.basename(path)
    for lv in LEVELS:
        if lv["file"] == base:
            return lv["key"]
    return ""


def missing_files():
    """磁盘上缺了哪些关卡文件。envcheck 与 selftest 用。"""
    return [lv["file"] for lv in LEVELS
            if not os.path.isfile(os.path.join(config.LEVEL_DIR, lv["file"]))]
