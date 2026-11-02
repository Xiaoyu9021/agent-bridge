"""Real 512 MiB transfer: separate Host process, two clients, Qt heartbeat, RSS samples.

Run from repository root: python scripts/verify_large_transfer.py
Only the JSON report is kept; generated files live in an automatically removed temp directory.
No tokens are persisted or printed.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import platform
import socket
import tempfile
import threading
import time
from pathlib import Path

import psutil

from codex_bridge.client.api import BridgeClient
from codex_bridge.config import Settings
from codex_bridge.models import DeviceInput, TaskInput
from codex_bridge.server.runtime import HostRuntime
from codex_bridge.services.files import describe_file, file_hash


def host_process(root, port, host, pipe):
    runtime = HostRuntime(Settings(Path(root), port=port), DeviceInput(**host))
    try:
        runtime.start()
        pipe.send({"url": runtime.url, "token": runtime.control.token, "code": runtime.control.open_pairing()})
        while True:
            command = pipe.recv()
            if command == "stop":
                break
            if command == "approve":
                pending = runtime.control.pending()
                runtime.control.approve(pending[0]["request_id"])
                pipe.send("approved")
    finally:
        runtime.close()


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from codex_bridge.ui.app import MainWindow

    app = QApplication.instance() or QApplication([])
    host = DeviceInput(display_name="Large test Windows", platform="windows")
    mac = DeviceInput(display_name="Large test peer", platform="simulated-macos")
    with tempfile.TemporaryDirectory(prefix="bridge-large-") as temp:
        root = Path(temp)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        parent, child = multiprocessing.Pipe()
        process = multiprocessing.Process(target=host_process, args=(str(root / "host"), port, host.model_dump(), child))
        process.start()
        sender = receiver = window = None
        try:
            if not parent.poll(30):
                raise TimeoutError("Host did not start")
            info = parent.recv()
            sender = BridgeClient(info["url"], host, info["token"])
            receiver = BridgeClient(info["url"], mac)
            request = receiver.pair_request(info["code"])
            parent.send("approve")
            assert parent.recv() == "approved"
            receiver.pair_poll(request)
            source = root / "512MiB-项目.bin"
            chunk = os.urandom(1024**2)
            with source.open("wb") as handle:
                for _ in range(512):
                    handle.write(chunk)
            del chunk
            metadata = describe_file(source)
            model = TaskInput(title="512 MiB 实测", description_md="真实分进程网络传输", recipient_device_id=mac.id,
                              attachments=[metadata])
            prefs = {"mode": "client", "url": info["url"], "download_dir": str(root / "downloads")}
            window = MainWindow(Settings(root / "gui"), host, prefs)
            window.client = sender
            window.refresh = lambda: None
            window.show()
            app.processEvents()
            host_memory = psutil.Process(process.pid)
            client_memory = psutil.Process()
            baseline_host = host_memory.memory_info().rss
            baseline_client = client_memory.memory_info().rss
            samples = []
            ticks = []
            timer = QTimer()
            timer.setInterval(50)
            timer.timeout.connect(lambda: ticks.append(time.monotonic()))
            timer.start()
            stop_sampling = threading.Event()
            def sample():
                while not stop_sampling.wait(0.02):
                    samples.append((host_memory.memory_info().rss, client_memory.memory_info().rss))
            sampler = threading.Thread(target=sample, daemon=True)
            sampler.start()
            measurements = {}
            completed, failures = [], []
            def transfer(progress):
                started = time.monotonic()
                sender.send_task(model, [source], progress)
                measurements["upload_seconds"] = round(time.monotonic() - started, 3)
                task = receiver.request("GET", f"/tasks/{model.id}")
                started = time.monotonic()
                target = receiver.download(task["attachments"][0], root / "downloads", progress)
                measurements["download_seconds"] = round(time.monotonic() - started, 3)
                assert file_hash(target) == (metadata.size_bytes, metadata.sha256)
                return True
            window.launch_worker(transfer, completed.append, failures.append, True)
            started = time.monotonic()
            while not completed and not failures:
                app.processEvents()
                time.sleep(0.005)
                if time.monotonic() - started > 240:
                    raise TimeoutError("Large transfer exceeded 240 seconds")
            stop_sampling.set()
            sampler.join()
            timer.stop()
            if failures:
                raise failures[0]
            peak_host = max([baseline_host] + [item[0] for item in samples])
            peak_client = max([baseline_client] + [item[1] for item in samples])
            gaps = [b - a for a, b in zip(ticks, ticks[1:])]
            report = {
                "platform": platform.platform(), "python": platform.python_version(),
                "file_bytes": metadata.size_bytes, "sha256": metadata.sha256,
                "separate_host_process": True, "independent_http_clients": 2,
                "transport": "HTTP over 127.0.0.1 (not physical LAN)",
                "sha256_verified": True, **measurements,
                "host_rss_growth_mib": round((peak_host - baseline_host) / 1024**2, 2),
                "client_gui_rss_growth_mib": round((peak_client - baseline_client) / 1024**2, 2),
                "qt_heartbeat_ticks": len(ticks), "qt_max_heartbeat_gap_seconds": round(max(gaps, default=0), 3),
                "measured_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            }
            # Bounded growth and responsive event processing are explicit acceptance conditions.
            assert report["host_rss_growth_mib"] < 128
            assert report["client_gui_rss_growth_mib"] < 128
            assert len(ticks) > 10 and max(gaps, default=0) < 1
            output = Path("artifacts/large-transfer.json")
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=True, indent=2))
        finally:
            if window:
                window.ready_to_close = True
                window.close()
            if sender:
                sender.close()
            if receiver:
                receiver.close()
            if process.is_alive():
                parent.send("stop")
                process.join(20)
            if process.is_alive():
                process.terminate()
                process.join()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
