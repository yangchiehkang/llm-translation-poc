# 网络修正：本服务器 getaddrinfo 把 dashscope 的 IPv6 地址排在前面，但 IPv6 到
# dashscope 的链路不通，Python(requests/urllib3)按顺序逐个连、无 Happy-Eyeballs，
# 会在 IPv6 SYN 上卡满 tcp_syn_retries(=6, 约63s)才回退 IPv4 —— 这就是每次翻译固定 ~64s 的根因。
# 修法：把 socket.getaddrinfo 结果里的 IPv4 排到前面，Python 先连 IPv4(约0.2s)即成功。
# 只重排、不删除 IPv6：万一将来只有 IPv6 也仍能连。可用 PREFER_IPV4=false 关闭。

from __future__ import annotations

import socket

_installed = False


def install_ipv4_first() -> None:
    global _installed
    if _installed:
        return
    _orig_getaddrinfo = socket.getaddrinfo

    def _ipv4_first(host, port, family=0, *args, **kwargs):
        res = _orig_getaddrinfo(host, port, family, *args, **kwargs)
        res.sort(key=lambda r: 0 if r[0] == socket.AF_INET else 1)
        return res

    socket.getaddrinfo = _ipv4_first
    _installed = True
