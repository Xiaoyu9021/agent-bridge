"""Noninteractive smoke test for source and frozen distributions."""
import json
import platform
import socket
import tempfile
from pathlib import Path


def self_check(report_path: Path):
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from codex_bridge import __version__
    from codex_bridge.client.api import BridgeClient
    from codex_bridge.config import Settings
    from codex_bridge.models import DeviceInput, TaskInput
    from codex_bridge.server.runtime import HostRuntime
    from codex_bridge.services.connection import invitation, local_addresses, parse_invitation
    from codex_bridge.ui.app import MainWindow
    from codex_bridge.ui.setup import SetupDialog

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="bridge-selfcheck-") as temp:
        root = Path(temp)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        settings = Settings(root / "host", port=port)
        host = DeviceInput(display_name="Self-check Host", platform=platform.system().lower())
        peer = DeviceInput(display_name="Self-check Client", platform=platform.system().lower())
        runtime = HostRuntime(settings, host)
        runtime.start()
        sender = BridgeClient(runtime.url, host, runtime.control.token)
        receiver = BridgeClient(runtime.url, peer)
        try:
            key = receiver.pair_request(runtime.control.open_pairing())
            runtime.control.approve(key)
            receiver.pair_poll(key)
            setup = SetupDialog(settings, host, {"mode": "host", "host": "127.0.0.1", "auto_host": False})
            assert setup.advanced.isHidden()
            setup.client_choice.click()
            setup.invite.setPlainText(invitation(runtime.url, "12345678"))
            assert parse_invitation(setup.invite.toPlainText()) == (runtime.url, "12345678")
            assert setup.values()["url"] == runtime.url
            adapters = len(local_addresses())
            setup.close()
            model = TaskInput(title="打包自检", description_md="中文任务往返", recipient_device_id=peer.id)
            sender.send_task(model, [])
            assert receiver.snapshot()["tasks"][0]["title"] == "打包自检"
            prefs = {"mode": "host", "url": runtime.url, "download_dir": str(root)}
            window = MainWindow(settings, host, prefs)
            window.client = sender
            window.refresh = lambda: None
            window.apply_snapshot(sender.snapshot())
            window.tasks.setCurrentRow(0)
            app.processEvents()
            assert "中文任务往返" in window.body.toPlainText()
            fonts = len(QFontDatabase.families())
            window.ready_to_close = True
            window.close()
            report = {"passed": True, "version": __version__, "platform": platform.platform(),
                      "python": platform.python_version(), "gui_created": True, "system_font_families": fonts,
                      "pairing_and_task_http": True, "simple_setup_and_invitation": True,
                      "private_adapter_candidates": adapters}
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            sender.close()
            receiver.close()
            runtime.close()
