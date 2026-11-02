from __future__ import annotations

import os
import threading
import time

import uvicorn

from codex_bridge.config import Settings
from codex_bridge.models import DeviceInput
from codex_bridge.server.app import create_app
from codex_bridge.server.control import HostControl
from codex_bridge.storage.store import Store


class HostRuntime:
    def __init__(self, settings: Settings, device: DeviceInput):
        settings.validate()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = (settings.data_dir / "host.lock").open("a+b")
        self.thread = None
        self.server = None
        try:
            self.lock_file.seek(0)
            if os.name == "nt":
                import msvcrt
                self.lock_file.write(b"0")
                self.lock_file.flush()
                self.lock_file.seek(0)
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.control = HostControl(Store(settings), device)
            self.app = create_app(self.control)
            self.server = uvicorn.Server(uvicorn.Config(self.app, host=settings.host, port=settings.port,
                                                       access_log=False, log_level="warning", log_config=None))
            self.url = f"http://[{settings.host}]:{settings.port}" if ":" in settings.host else (
                f"http://{settings.host}:{settings.port}")
        except BaseException:
            self.lock_file.close()
            raise

    def start(self):
        self.thread = threading.Thread(target=self.server.run, daemon=True, name="bridge-host")
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() >= deadline:
                self.close()
                raise RuntimeError("Host 启动失败，请检查监听 IP 是否属于本机、端口是否被占用")
            time.sleep(0.05)

    def close(self):
        if self.server:
            self.server.should_exit = True
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=15)
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Host 仍在结束传输，请稍后重试退出")
        self.lock_file.close()
