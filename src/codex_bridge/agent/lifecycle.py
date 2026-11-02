from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

from codex_bridge.agent.local import StartupLock, Vault, init_profile, local_control_url, read_json
from codex_bridge.client.api import BridgeClient
from codex_bridge.storage.store import BridgeError


def control_request(root: Path, method: str, path: str, *, vault=None, timeout=660, **kwargs):
    state = read_json(root / "running.json")
    if not state:
        raise BridgeError("not_running", "接收进程没有运行，请先运行 setup 或 start", 409)
    url = local_control_url(state["url"])
    vault = vault or Vault(root)
    token = vault.get("control")
    if not token:
        raise BridgeError("missing_credentials", "本地控制凭据丢失，请运行 start 重新启动接收进程", 401)
    try:
        with httpx.Client(base_url=url, timeout=httpx.Timeout(timeout, connect=2), trust_env=False) as client:
            response = client.request(method, "/local" + path, headers={"Authorization": "Bearer " + token}, **kwargs)
            BridgeClient.check(response)
            result = response.json()
            if path == "/status" and result.get("instance") != state.get("instance"):
                raise BridgeError("stale_state", "本地服务记录已过期，请重新运行 start", 409)
            return result
    except httpx.ConnectError:
        raise BridgeError("not_running", "接收进程已停止，请运行 start", 409) from None


def start_receiver(root: Path, *, name=None, listen="auto", port=47821):
    with StartupLock(root):
        vault = Vault(root)
        try:
            return control_request(root, "GET", "/status", vault=vault, timeout=3)
        except (BridgeError, httpx.RequestError):
            pass
        init_profile(root, name, listen, port)
        token = secrets.token_urlsafe(48)
        vault.put("control", token)
        # No secret is put in argv, environment variables, or the startup state file.
        command = [sys.executable, "-m", "codex_bridge.agent.cli", "--home", str(root), "_serve"]
        flags = {}
        if os.name == "nt":
            flags["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            flags["start_new_session"] = True
        # An installed skill prepends its embedded runtime; carry only this import path to the child.
        environment = os.environ.copy()
        package_root = str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"] = package_root
        with (root / "receiver.log").open("ab") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       env=environment, cwd=root, close_fds=True, **flags)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                result = control_request(root, "GET", "/status", vault=vault, timeout=2)
                if result.get("device"):
                    return result
            except (BridgeError, httpx.RequestError, ValueError):
                pass
            time.sleep(0.1)
        raise BridgeError("startup_failed", "接收进程未能启动，请检查监听地址、系统凭据库和本地 receiver.log", 503)


def serve(root: Path):
    from codex_bridge.agent.broker import Node
    vault = Vault(root)
    token = vault.get("control")
    if not token:
        raise BridgeError("missing_credentials", "缺少本地控制授权，请从 start 启动", 401)
    node = Node(root, vault, token)
    try:
        node.start()
        while not node.stop_event.wait(1):
            node.poll_joins()
    finally:
        node.close()


def stop_receiver(root: Path):
    try:
        response = control_request(root, "POST", "/stop", timeout=3)
    except BridgeError as error:
        if error.code == "not_running":
            return {"status": "already_stopped"}
        raise
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if not (root / "running.json").exists():
            return {"status": "stopped"}
        time.sleep(0.1)
    return response
