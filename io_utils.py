# -*- coding: utf-8 -*-
"""文件读写统一入口。

**为什么必须有这个文件**：Windows 版 Python 3.6 的 ``open()`` 默认使用
``locale.getpreferredencoding()``，实测本机是 **cp936（GBK）**。项目的关卡
文件、存档、文案全部是 UTF-8，直接 ``open(path)`` 会抛：

    UnicodeDecodeError: 'gbk' codec can't decode byte 0xac in position 2

因此项目内**禁止**直接调用 ``open()`` 读写文本，一律走这里。
（二进制读写不受影响，可以继续用 ``open(path, 'rb')``。）

另外 Python 3.6 的 ``json.dump`` 也需要显式 ``encoding='utf-8'``。
"""

import io
import json
import os
import tempfile

ENCODING = "utf-8"


def read_text(path):
    """读 UTF-8 文本，自动吞掉 BOM（记事本存过的文件常带 BOM）。"""
    with io.open(path, "r", encoding=ENCODING, errors="strict") as f:
        text = f.read()
    if text and text[0] == u"\ufeff":
        text = text[1:]
    return text


def read_lines(path):
    """按行读取，返回不含行尾的列表。"""
    return read_text(path).splitlines()


def write_text(path, text):
    """写 UTF-8 文本，父目录不存在时自动创建。"""
    ensure_dir(os.path.dirname(path))
    with io.open(path, "w", encoding=ENCODING, newline="\n") as f:
        f.write(text)


def read_json(path, default=None):
    """读 JSON；文件不存在或内容损坏时返回 default，不抛异常。

    存档必须"坏得能起"，不能因为一次写到一半就让玩家进不去游戏。
    """
    if not os.path.isfile(path):
        return default
    try:
        return json.loads(read_text(path))
    except Exception:
        return default


def write_json(path, data):
    """原子写入 JSON：先写临时文件再 rename，避免断电留下半个文件。"""
    ensure_dir(os.path.dirname(path))
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=folder)
    os.close(fd)
    with io.open(tmp, "w", encoding=ENCODING, newline="\n") as f:
        f.write(text)
    # os.replace 在 Windows 上也会覆盖已有文件，是原子的
    os.replace(tmp, path)


def ensure_dir(path):
    """递归建目录；空路径直接忽略。"""
    if path and not os.path.isdir(path):
        os.makedirs(path)
