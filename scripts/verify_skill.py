"""Verify the installed skill via independent CLI processes, real HTTP, and the OS vault."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from codex_bridge import __version__
from codex_bridge.agent.local import Vault


def main():
    project = Path(__file__).resolve().parents[1]
    skill = project / "skills" / "agent-bridge"
    python = skill / ".runtime" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    entry = skill / "scripts" / "bridge.py"
    if not python.is_file():
        raise RuntimeError("Run the skill bootstrap first")
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    subprocess.run([str(python), "-c", "import importlib.util; assert importlib.util.find_spec('PySide6') is None"],
                   check=True, env=environment, **flags)
    with tempfile.TemporaryDirectory(prefix="agent-bridge-skill-") as temp:
        base = Path(temp)
        windows, mac = base / "windows", base / "mac"
        def command(home, *args, input=None, allow_error=False):
            process = subprocess.run([sys.executable, str(entry), "--home", str(home), *args], input=input,
                                     encoding="utf-8", capture_output=True, env=environment, timeout=90, **flags)
            result = json.loads(process.stdout)
            if process.returncode and not allow_error:
                raise RuntimeError(result.get("error", {}).get("message", "CLI failed"))
            return result
        started = []
        try:
            for home, name in [(windows, "windows-codex"), (mac, "mac-codex")]:
                result = command(home, "setup", "--name", name, "--listen", "127.0.0.1")
                assert result["running"]
                started.append(home)
            invite = command(windows, "invite")["invitation"]
            assert command(mac, "join", "--alias", "windows", input=invite)["status"] == "waiting_for_approval"
            pending = command(windows, "pending")
            assert pending[0]["display_name"] == "mac-codex"
            command(windows, "approve", pending[0]["id"])
            for _ in range(20):
                peers = command(mac, "peers")
                if peers and peers[0]["status"] == "paired":
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Pairing did not complete")
            report = base / "执行报告.md"
            report.write_text("# SpaceWatch iOS 第12轮\n已完成页面复刻；待验证推送权限。\n测试：示例数据，不代表真实 App 验收。", encoding="utf-8")
            artifact = base / "ios-changes.zip"
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("README.md", "Synthetic handoff fixture; never auto-extract")
            screenshot = base / "截图.png"
            screenshot.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic-test")
            sent = command(mac, "send", "--to", "windows", "--project", "SpaceWatch", "--title", "iOS 第12轮交付",
                           "--report", str(report), "--file", str(artifact), "--file", str(screenshot))
            assert sent["status"] == "delivered_to_receiver" and sent["files"] == 3
            delivery_id = sent["delivery_id"]
            command(mac, "retry", delivery_id)
            assert len(command(windows, "inbox", "--project", "SpaceWatch")) == 1
            received = command(windows, "receive", "--project", "SpaceWatch")
            assert Path(received["report_path"]).read_bytes() == report.read_bytes()
            expected = {hashlib.sha256(source.read_bytes()).hexdigest() for source in [report, artifact, screenshot]}
            assert {item["sha256"] for item in received["files"]} == expected
            before_read = command(mac, "delivery-status", delivery_id)
            assert before_read["received_at"] and before_read["read_at"] is None
            command(windows, "read", delivery_id)
            assert command(mac, "delivery-status", delivery_id)["read_at"]
            # Restart both real background processes; control credentials rotate, paired credentials remain.
            receiver_url = command(windows, "status")["receiver_url"]
            assert command(mac, "stop")["status"] == "stopped"
            assert command(windows, "stop")["status"] == "stopped"
            command(windows, "start")
            command(mac, "start")
            assert command(windows, "status")["receiver_url"] == receiver_url
            assert command(mac, "delivery-status", delivery_id)["read_at"]
            assert Path(command(windows, "receive", "--id", delivery_id)["report_path"]).read_bytes() == report.read_bytes()
            report_result = {"version": __version__, "platform": platform.platform(), "python": platform.python_version(),
                             "isolated_skill_runtime": True, "qt_required": False, "independent_receiver_processes": 2,
                             "independent_cli_invocations": True, "system_vault": True, "files": 3,
                             "chinese_filenames": True, "sha256_verified": True, "idempotent_retry": True,
                             "received_and_read_distinguished": True, "restart_recovery": True,
                             "transport": "127.0.0.1 on Windows; simulated Mac, not physical cross-device LAN"}
            output = project / "artifacts" / "skill-smoke.windows.json"
            output.write_text(json.dumps(report_result, indent=2), encoding="utf-8")
            print(json.dumps(report_result, indent=2))
        finally:
            for home in reversed(started):
                try:
                    command(home, "stop", allow_error=True)
                    Vault(home).delete("peer:windows")
                except Exception:
                    pass


if __name__ == "__main__":
    main()
