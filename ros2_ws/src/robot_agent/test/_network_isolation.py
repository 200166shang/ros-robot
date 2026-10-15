"""Agent测试的本机网络隔离，不影响生产连接或安装子进程。"""

import ipaddress
import socket

from pytest import MonkeyPatch


def _require_loopback(host):
    """域名在DNS前拒绝，只允许localhost及字面回环地址。"""
    if host == "localhost":
        return
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    assert local, f"Agent tests forbid non-loopback network: {host!r}"


def _guard_connect(connect):
    """原始系统调用只接纳Unix或回环目标。"""

    def guarded(sock, address):
        """先验证目标，再调用保留的本地socket出口。"""
        if sock.family != socket.AF_UNIX:
            _require_loopback(address[0])
        return connect(sock, address)

    return guarded


def isolate_network(monkeypatch: MonkeyPatch) -> None:
    """仅允许Python测试进程连接Unix socket与本机回环地址。"""
    for operation in ("connect", "connect_ex"):
        monkeypatch.setattr(
            socket.socket,
            operation,
            _guard_connect(getattr(socket.socket, operation)),
        )
    resolve = socket.getaddrinfo

    def local_addresses(host, *args, **kwargs):
        """远程域名不能先通过系统解析器发送DNS请求。"""
        if host is not None:
            _require_loopback(host)
        return resolve(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", local_addresses)
