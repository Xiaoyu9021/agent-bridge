from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


@dataclass
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 47821
    max_file_bytes: int = 1024**3
    max_task_bytes: int = 2 * 1024**3
    pair_ttl: int = 600
    reserve_bytes: int = 16 * 1024**2

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            Path(os.environ.get("BRIDGE_DATA_DIR", user_data_path("CodexBridge", appauthor=False))),
            os.environ.get("BRIDGE_HOST", "127.0.0.1"), int(os.environ.get("BRIDGE_PORT", "47821")),
            int(os.environ.get("BRIDGE_MAX_FILE_BYTES", str(1024**3))),
            int(os.environ.get("BRIDGE_MAX_TASK_BYTES", str(2 * 1024**3))),
        )

    def validate(self) -> None:
        address = ipaddress.ip_address(self.host)
        private_ranges = [ipaddress.ip_network(item) for item in (
            "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
            "100.64.0.0/10", "::1/128", "fc00::/7",
        )]
        if not any(address in network for network in private_ranges):
            raise ValueError("仅允许监听明确的回环、局域网或私有网络 IP；不允许公网或通配地址")
        if not 1 <= self.port <= 65535 or not 0 < self.max_file_bytes <= self.max_task_bytes:
            raise ValueError("端口或文件大小配置无效")


CHUNK_SIZE = 1024 * 1024
