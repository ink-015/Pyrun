# -*- coding: utf-8 -*-
"""推送兜底：本地起一个只做一件事的代理，把 github.com 接到真实 IP。

为什么需要它（2026-11-25 实测）：
    这台机器所在网络的 DNS 把 `github.com` 解析成 `20.6.7.17`，那个地址
    的 443 直接超时；而真实 IP（140.82.113.4 / 20.205.243.166 …）能够
    正常握手，`api.github.com`、`codeload.github.com` 也都通。
    于是 `git push` 表现为诡异的一幕：网络明明是好的，代理却一直回
    `CONNECT tunnel failed, response 502`——因为代理也是按 DNS 去连的。

做法：
    在 127.0.0.1 上起一个临时的 HTTP 代理，只拦截 `CONNECT github.com:443`，
    把它改接到一个**真实 IP**上，其余请求原样转发。TLS 仍然是端到端的
    （证书按 github.com 校验），不需要关 sslVerify，也没有中间人。

    一次推送的生命周期内线程 + socket 都活着，推完就退，不留后台进程。

用法：
    python tools/git_push.py              推送当前分支（等价于 git push origin HEAD）
    python tools/git_push.py ls-remote    只读一次远端，先确认这条路通不通
    python tools/git_push.py --dry        只启动代理并自检，不跑 git
"""

from __future__ import print_function

import os
import socket
import subprocess
import sys
import threading
import time

# 2026-11-25 实测可用的 GitHub 入口。按延迟手动排过序，前两个基本都在 100ms 内。
GITHUB_IPS = [
    "140.82.113.4",
    "140.82.112.4",
    "20.205.243.166",
    "140.82.114.4",
    "140.82.116.4",
]
# 只改写这几个主机：它们的 DNS 结果是脏的，或者必须和 github.com 同一条链路。
REWRITE_HOSTS = ("github.com",)

TIMEOUT = 12.0


def pick_ip():
    """挑一个真能连上的 IP。不能用 DNS，这就是本脚本存在的理由。"""
    for ip in GITHUB_IPS:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        try:
            s.connect((ip, 443))
            return ip
        except (socket.error, OSError):
            continue
        finally:
            s.close()
    return None


def _pipe(src, dst, tag):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except (socket.error, OSError):
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except (socket.error, OSError):
            pass


class Relay(object):
    """最小可用的 HTTP CONNECT 代理：只做一次连接改写。"""

    def __init__(self, ip):
        self.ip = ip
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.count = 0
        self._stop = False
        self._thread = threading.Thread(target=self._serve)
        self._thread.daemon = True

    def start(self):
        self._thread.start()
        return self.port

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except (socket.error, OSError):
            pass

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except (socket.error, OSError):
                return
            t = threading.Thread(target=self._handle, args=(conn,))
            t.daemon = True
            t.start()

    def _handle(self, client):
        upstream = None
        try:
            client.settimeout(TIMEOUT)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = client.recv(4096)
                if not chunk:
                    return
                head += chunk
                if len(head) > 65536:
                    return

            lines = head.split(b"\r\n\r\n")[0].split(b"\r\n")
            parts = lines[0].decode("latin-1").split()
            if len(parts) < 3 or parts[0].upper() != "CONNECT":
                client.sendall(b"HTTP/1.1 405 Only CONNECT\r\n\r\n")
                return

            host, _, port = parts[1].rpartition(":")
            port = int(port or 443)
            if host in REWRITE_HOSTS:
                target = (self.ip, port)
            else:
                target = (host, port)

            upstream = socket.create_connection(target, timeout=TIMEOUT)
            upstream.settimeout(None)
            client.settimeout(None)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.count += 1

            t = threading.Thread(target=_pipe, args=(upstream, client, "u->c"))
            t.daemon = True
            t.start()
            _pipe(client, upstream, "c->u")
            t.join(timeout=1.0)
        except (socket.error, OSError) as exc:
            try:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            except (socket.error, OSError):
                pass
            if os.environ.get("GIT_PUSH_DEBUG"):
                print(u"  [relay] %s: %s" % (target if upstream else "connect", exc))
        finally:
            for s in (client, upstream):
                if s is not None:
                    try:
                        s.close()
                    except (socket.error, OSError):
                        pass


def main(argv):
    ip = pick_ip()
    if ip is None:
        print(u"所有候选 IP 都连不上，这条路也不通")
        return 2
    relay = Relay(ip)
    port = relay.start()
    proxy = "http://127.0.0.1:%d" % port
    print(u"本地代理 : %s -> github.com:%s" % (proxy, ip))

    if "--dry" in argv:
        relay.stop()
        return 0

    args = [a for a in argv if not a.startswith("--")]
    if args and args[0] == "ls-remote":
        cmd = ["git", "ls-remote", "origin"]
    else:
        cmd = ["git", "push", "origin", "HEAD"]

    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env[k] = proxy
    env["NO_PROXY"] = ""
    env["no_proxy"] = ""

    cmd = ["git",
           "-c", "http.proxy=" + proxy,
           "-c", "https.proxy=" + proxy] + cmd[1:]

    started = time.time()
    try:
        code = subprocess.call(cmd, env=env)
    finally:
        relay.stop()
    print(u"结果     : %s（%.1f 秒，%d 条隧道）"
          % (u"成功" if code == 0 else u"失败（退出码 %d）" % code,
             time.time() - started, relay.count))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
