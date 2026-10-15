"""隔离规则通过socket出口验证，RED也不建立真实外网连接。"""

import socket

import pytest
from _network_isolation import isolate_network


@pytest.mark.parametrize("operation", ["connect", "connect_ex"])
def test_unmocked_external_connection_fails_before_socket_io(
    monkeypatch, operation
):
    """下层连接替身若被调用，说明隔离未在联网前拒绝。"""
    attempts = []

    def lower_connect(sock, address):
        """只记录调用，无论RED或GREEN都不访问网络。"""
        attempts.append(address)
        return 0

    monkeypatch.setattr(socket.socket, operation, lower_connect)
    isolate_network(monkeypatch)
    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="non-loopback"):
            getattr(sock, operation)(("192.0.2.1", 443))
    assert attempts == []


@pytest.mark.parametrize(
    "family,address",
    [
        (socket.AF_INET, ("127.0.0.1", 1)),
        (socket.AF_INET6, ("::1", 1)),
        (socket.AF_UNIX, "/tmp/fixture-only"),
    ],
)
def test_local_socket_destinations_remain_available(
    monkeypatch, family, address
):
    """本机IPv4、IPv6和Unix通道仍可抵达原始出口。"""
    attempts = []

    def lower_connect(sock, target):
        """替身避免连接未监听的本机目标。"""
        attempts.append(target)

    monkeypatch.setattr(socket.socket, "connect", lower_connect)
    isolate_network(monkeypatch)
    with socket.socket(family) as sock:
        sock.connect(address)
    assert attempts == [address]


def test_remote_dns_is_rejected_before_resolver(monkeypatch):
    """未替换的域名不能在socket拒绝前先访问外部DNS。"""
    attempts = []

    def lower_resolve(host, *args, **kwargs):
        """仅记录请求，测试不发送DNS。"""
        attempts.append(host)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", lower_resolve)
    isolate_network(monkeypatch)
    with pytest.raises(AssertionError, match="non-loopback"):
        socket.getaddrinfo("service.example.test", 443)
    assert attempts == []
    assert socket.getaddrinfo("localhost", 443) == []
    assert attempts == ["localhost"]
