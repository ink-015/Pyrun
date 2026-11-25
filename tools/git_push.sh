#!/bin/sh
# 推送兜底脚本。
#
# 这台机器（校园网）上有三种不同的"推不上去"，按顺序试：
#
#   1) 会话代理端口每次都在变（见过 64795、54782、60213），git 不一定
#      继承了环境变量 → 先按当前 $HTTPS_PROXY 推。
#   2) 代理自己回 502 Bad Gateway。2026-11-25 查明真因：这个网络的 DNS
#      把 github.com 解析成 20.6.7.17（443 直接超时），真实 IP 反而是通的，
#      代理按 DNS 去连所以连不上 → 直连（清空代理）试一次。
#   3) DNS 还是脏的 → 交给 tools/git_push.py：它在本机起一个只改写
#      "CONNECT github.com:443" 的临时代理，把目标换成真实 IP。TLS 仍是
#      端到端校验，不关 sslVerify。
#
# 用法： sh tools/git_push.sh
# 每条路都是 120 秒超时，避免半开连接把命令挂死。

set -u
cd "$(dirname "$0")/.." || exit 1

proxy="${HTTPS_PROXY:-${https_proxy:-}}"

if [ -n "$proxy" ]; then
    echo "[push] 1/3 走会话代理 $proxy"
    if timeout 120 git -c "http.proxy=$proxy" -c "https.proxy=$proxy" \
            push origin HEAD 2>&1 | tee /tmp/_push.log | tail -5; then
        if grep -qE "\.\.|Everything up-to-date|->" /tmp/_push.log; then
            exit 0
        fi
    fi
    echo "[push] 代理不通，改直连" >&2
fi

echo "[push] 2/3 直连（-c http.proxy= 清空代理）"
if timeout 120 git -c http.proxy= -c https.proxy= push origin HEAD 2>&1 \
        | tee /tmp/_push2.log | tail -5; then
    if grep -qE "\.\.|Everything up-to-date|->" /tmp/_push2.log; then
        exit 0
    fi
fi

echo "[push] 3/3 DNS 被污染：用本地改写代理（tools/git_push.py）" >&2
py="${PYTHON:-python}"
"$py" tools/git_push.py
