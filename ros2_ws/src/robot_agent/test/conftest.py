"""Agent验收默认禁止未替换的外网连接。"""

import pytest
from _network_isolation import isolate_network


@pytest.fixture(autouse=True)
def local_network_only(monkeypatch):
    """外部协议必须路由到本机fixture，安装子进程保持独立。"""
    isolate_network(monkeypatch)
