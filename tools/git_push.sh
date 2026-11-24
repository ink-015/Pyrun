#!/bin/sh
# 推送兜底脚本。
#
# 为什么需要它：这台机器上 git push 偶尔会报
#   fatal: unable to access '...': CONNECT tunnel failed, response 502
# 原因是 Workspace 的本地代理端口每次会话都可能变（见过 64795、54782），
# 而 git 没有把环境变量里的代理稳定传下去。表现就是"网络明明是好的，
# curl 能访问 github，git 却一直 502"。
#
# 用法： sh tools/git_push.sh
#
# 先按当前会话的代理推；代理不通就绕开代理直连再推一次。
# 120 秒超时，避免半开的连接把命令挂死。

set -u
cd "$(dirname "$0")/.." || exit 1

proxy="${HTTPS_PROXY:-${https_proxy:-}}"

if [ -n "$proxy" ]; then
    echo "[push] 走代理 $proxy"
    if timeout 120 git -c "http.proxy=$proxy" -c "https.proxy=$proxy" \
            push origin HEAD 2>&1 | tee /tmp/_push.log | tail -5; then
        if grep -qE "\.\.|Everything up-to-date|->" /tmp/_push.log; then
            exit 0
        fi
    fi
    echo "[push] 代理不通，改直连重试" >&2
fi

echo "[push] 直连（-c http.proxy= 清空代理）"
timeout 120 git -c http.proxy= -c https.proxy= push origin HEAD 2>&1 | tail -5
