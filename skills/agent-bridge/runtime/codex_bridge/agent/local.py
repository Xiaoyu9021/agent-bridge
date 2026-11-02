from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import platform
import re
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_data_path

from codex_bridge.client.api import normalize_url
from codex_bridge.config import Settings
from codex_bridge.models import DeviceInput
from codex_bridge.storage.store import BridgeError


def profile_home(profile: str, home: Path | None = None) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,50}", profile):
        raise ValueError("profile 只能包含字母、数字、下划线或短横线")
    root = home or Path(os.environ.get("BRIDGE_AGENT_HOME", user_data_path("AgentBridge", appauthor=False))) / profile
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
    return root


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def init_profile(root: Path, name: str | None = None, listen: str = "auto", port: int = 47821) -> dict:
    existing = read_json(root / "agent.json")
    if existing:
        return existing
    if listen != "auto":
        Settings(root, host=listen, port=port).validate()
    device = DeviceInput(display_name=name or f"{platform.system().lower()}-codex", platform=platform.system().lower())
    config = {"device": device.model_dump(), "listen": listen, "preferred_port": port,
              "inbox": str(root / "inbox")}
    write_json(root / "agent.json", config)
    return config


def automatic_address() -> str:
    candidates = []
    # UDP connect only asks the OS which local route it would use; no data is sent.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(("192.0.2.1", 9))
            candidates.append(route.getsockname()[0])
    except OSError:
        pass
    try:
        candidates.extend(entry[4][0] for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    for candidate in dict.fromkeys(candidates):
        try:
            address = ipaddress.ip_address(candidate)
            Settings(Path("."), host=candidate).validate()
            if not address.is_loopback:
                return candidate
        except ValueError:
            continue
    return "127.0.0.1"


def available_port(host: str, preferred: int) -> int:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, preferred))
        except OSError:
            probe.bind((host, 0))
        return probe.getsockname()[1]


def local_control_url(value: str) -> str:
    value = normalize_url(value)
    parts = urlsplit(value)
    if parts.hostname != "127.0.0.1" or parts.scheme != "http" or not parts.port:
        raise ValueError("本地控制地址无效")
    return value


def alias_name(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,50}", value):
        raise ValueError("设备别名只能包含字母、数字、下划线或短横线")
    return value


class Vault:
    """Require a real OS credential backend. Never write cleartext fallback tokens."""

    def __init__(self, root: Path):
        import keyring
        self.backend = keyring.get_keyring()
        if not type(self.backend).__module__.startswith((
            "keyring.backends.Windows", "keyring.backends.macOS", "keyring.backends.SecretService",
            "keyring.backends.kwallet",
        )):
            raise BridgeError("credential_store_unavailable", "系统凭据库不可用；请启用系统凭据库后重试，不会明文保存令牌", 503)
        self.namespace = hashlib.sha256(str(root.resolve()).encode()).hexdigest()

    def get(self, key: str) -> str | None:
        try:
            return self.backend.get_password("AgentBridge", self.namespace + ":" + key)
        except Exception:
            raise BridgeError("credential_store_unavailable", "系统凭据库读取失败，请解锁凭据库后重试", 503) from None

    def put(self, key: str, value: str):
        try:
            self.backend.set_password("AgentBridge", self.namespace + ":" + key, value)
        except Exception:
            raise BridgeError("credential_store_unavailable", "系统凭据库保存失败；授权没有写入明文文件", 503) from None

    def delete(self, key: str):
        try:
            self.backend.delete_password("AgentBridge", self.namespace + ":" + key)
        except Exception:
            pass


class StartupLock:
    def __init__(self, root: Path):
        self.file = (root / "agent-start.lock").open("a+b")

    def __enter__(self):
        try:
            if os.name == "nt":
                import msvcrt
                if self.file.seek(0, 2) == 0:
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise BridgeError("starting", "另一个命令正在启动接收进程，请稍后运行 status", 409) from None
        return self

    def __exit__(self, *args):
        self.file.close()
