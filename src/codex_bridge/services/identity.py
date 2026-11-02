from __future__ import annotations

import json
import os
import platform
import socket
from pathlib import Path

from codex_bridge.models import DeviceInput


def read_preferences(root: Path) -> dict:
    path = root / "preferences.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_preferences(root: Path, values: dict):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "preferences.json"
    temporary = path.with_suffix(".tmp")
    # Only explicit non-secret configuration is persisted.
    allowed = {key: value for key, value in values.items() if key in {
        "device", "mode", "url", "host", "port", "download_dir", "max_file_bytes", "max_task_bytes", "auto_host",
    }}
    temporary.write_text(json.dumps(allowed, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def local_device(root: Path, name: str | None = None) -> DeviceInput:
    prefs = read_preferences(root)
    if "device" in prefs:
        device = DeviceInput(**prefs["device"])
        if name:
            device.display_name = name
    else:
        device = DeviceInput(display_name=name or socket.gethostname(), platform=platform.system().lower())
    prefs["device"] = device.model_dump()
    save_preferences(root, prefs)
    return device


def secure_token(url: str, device_id: str, token: str | None = None) -> str | None:
    import keyring
    try:
        backend = keyring.get_keyring()
        if not type(backend).__module__.startswith((
            "keyring.backends.Windows", "keyring.backends.macOS", "keyring.backends.SecretService",
            "keyring.backends.kwallet",
        )):
            return None
        account = f"{url}|{device_id}"
        if token is not None:
            backend.set_password("CodexBridge", account, token)
            return token
        return backend.get_password("CodexBridge", account)
    except Exception:
        # A locked/unavailable keyring means memory-only authorization, never plaintext fallback.
        return None
