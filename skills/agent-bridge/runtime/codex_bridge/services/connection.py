"""Local interface selection and short-lived, explicitly shared connection invitations."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from codex_bridge.client.api import normalize_url


def private_ipv4(address: str) -> bool:
    try:
        value = ipaddress.ip_address(address)
        return value.version == 4 and any(value in ipaddress.ip_network(network) for network in (
            "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
        ))
    except ValueError:
        return False


def local_addresses() -> list[tuple[str, str]]:
    # Inspect local adapters only: no remote probes, broadcasts, or network scanning.
    from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface

    choices = []
    for adapter in QNetworkInterface.allInterfaces():
        flags = adapter.flags()
        if not flags & QNetworkInterface.InterfaceFlag.IsUp or not flags & QNetworkInterface.InterfaceFlag.IsRunning:
            continue
        if flags & QNetworkInterface.InterfaceFlag.IsLoopBack:
            continue
        name = adapter.humanReadableName() or adapter.name()
        virtual = bool(re.search(r"virtual|vethernet|vmware|vbox|docker|wsl|hyper-v", name, re.I))
        physical = adapter.type() in {QNetworkInterface.InterfaceType.Wifi, QNetworkInterface.InterfaceType.Ethernet}
        rank = 0 if physical and not virtual else 1 if "tailscale" in name.lower() else 2
        for entry in adapter.addressEntries():
            address = entry.ip()
            if address.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol and private_ipv4(address.toString()):
                choices.append((rank, address.toString(), name))
    return [(address, name) for _, address, name in sorted(set(choices))]


def suggested_host() -> str:
    candidates = local_addresses()
    return candidates[0][0] if candidates else "127.0.0.1"


def invitation(url: str, code: str) -> str:
    if not re.fullmatch(r"[0-9]{8}", code):
        raise ValueError("连接码已失效，请在另一台电脑重新生成连接信息")
    return normalize_url(url) + "/#bridge-pair=" + code


def parse_invitation(text: str) -> tuple[str, str]:
    text = text.strip()
    if len(text) > 2048:
        raise ValueError("连接信息过长，请重新复制")
    parts = urlsplit(text)
    if not re.fullmatch(r"bridge-pair=[0-9]{8}", parts.fragment):
        raise ValueError("请粘贴另一台电脑通过“复制连接信息”生成的完整内容")
    url = normalize_url(urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, "")))
    return url, parts.fragment.split("=", 1)[1]
