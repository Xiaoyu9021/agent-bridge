import os
import socket
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from codex_bridge.config import Settings
from codex_bridge.models import DeviceInput, TaskInput
from codex_bridge.services.connection import invitation, parse_invitation, private_ipv4
from codex_bridge.services.identity import read_preferences
from codex_bridge.ui.app import MainWindow, apply_profile
from codex_bridge.ui.pairing import PairingDialog
from codex_bridge.ui.setup import SetupDialog


def pump_until(app, condition, timeout=12):
    deadline = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        time.sleep(0.01)
        assert time.monotonic() < deadline, "GUI connection timed out"


def test_first_run_only_requires_role_or_one_pasted_invitation(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("codex_bridge.ui.setup.suggested_host", lambda: "192.168.1.20")
    device = DeviceInput(display_name="Windows", platform="windows")
    setup = SetupDialog(Settings(tmp_path), device, {"mode": "host"})
    setup.show()
    app.processEvents()
    assert setup.host_choice.isVisible()
    assert not setup.advanced.isVisible() and not setup.host.isVisible()
    assert not setup.invite.isVisible()
    assert setup.values()["host"] == "192.168.1.20"
    setup.client_choice.click()
    assert setup.invite.isVisible() and not setup.advanced.isVisible()
    setup.invite.setPlainText(invitation("http://192.168.1.20:47821", "12345678"))
    setup.validate()
    assert setup.values()["url"] == "http://192.168.1.20:47821"
    assert setup.initial_code == "12345678"
    assert "12345678" not in str(setup.values())


def test_saved_profile_skips_reconfiguration_and_follows_network_change(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    monkeypatch.setattr("codex_bridge.services.connection.suggested_host", lambda: "192.168.2.50")
    prefs = {"mode": "host", "host": "192.168.1.20", "auto_host": True}
    assert apply_profile(settings, prefs)
    assert settings.host == "192.168.2.50"
    prefs["auto_host"] = False
    prefs["host"] = "127.0.0.1"
    assert apply_profile(settings, prefs) and settings.host == "127.0.0.1"
    assert not apply_profile(settings, {})
    assert not apply_profile(settings, {"mode": "client", "url": "not-a-url"})


@pytest.mark.parametrize("text", [
    "http://192.168.1.20:47821", "http://192.168.1.20/#bridge-pair=abcdefgh",
    "http://user:secret@192.168.1.20/#bridge-pair=12345678",
    "http://192.168.1.20/?token=secret#bridge-pair=12345678",
    "http://192.168.1.20/file#bridge-pair=12345678", "x" * 2049,
])
def test_invitation_rejects_malformed_or_credential_bearing_urls(text):
    with pytest.raises(ValueError):
        parse_invitation(text)


def test_interface_filter_never_selects_public_or_wildcard():
    assert private_ipv4("192.168.2.3") and private_ipv4("100.64.1.2")
    for address in ["8.8.8.8", "0.0.0.0", "127.0.0.1", "169.254.0.1", "::", "bad"]:
        assert not private_ipv4(address)


def test_one_paste_then_local_approval_connects_two_real_gui_instances(tmp_path):
    app = QApplication.instance() or QApplication([])
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    host_device = DeviceInput(display_name="Windows", platform="windows")
    mac_device = DeviceInput(display_name="Mac", platform="macos")
    host = MainWindow(Settings(tmp_path / "host", port=port), host_device,
                      {"mode": "host", "download_dir": str(tmp_path / "host-downloads")})
    peer = None
    try:
        host.show()
        pump_until(app, lambda: host.runtime is not None and not host.busy and not host.polling)
        host.timer.stop()
        host.pair()
        code = host.runtime.control.code
        text = invitation(host.runtime.url, code)
        peer = MainWindow(Settings(tmp_path / "peer"), mac_device,
                          {"mode": "client", "url": host.runtime.url,
                           "download_dir": str(tmp_path / "peer-downloads")})
        peer.show()
        pump_until(app, lambda: peer.client is not None and not peer.busy and not peer.polling)
        peer.timer.stop()
        peer.pair()
        peer.pair_dialog.invite.setPlainText(text)
        peer.pair_dialog.join_button.click()
        pump_until(app, lambda: peer.pair_request_id is not None and not peer.busy)
        host.pair_dialog.refresh()
        assert host.pair_dialog.waiting.count() == 1
        host.pair_dialog.allow_button.click()
        pump_until(app, lambda: not host.busy)
        peer.refresh()
        pump_until(app, lambda: peer.online and not peer.polling)
        assert peer.new_task_button.isEnabled()
        saved = read_preferences(tmp_path / "peer")
        assert "bridge-pair" not in str(saved) and code not in str(saved)
        # The primary status action follows the current task instead of asking users to pick an enum.
        task = TaskInput(title="简单连接", description_md="测试", recipient_device_id=mac_device.id)
        host.client.send_task(task, [])
        peer.refresh()
        pump_until(app, lambda: not peer.polling)
        peer.tasks.setCurrentRow(0)
        assert peer.change_status_button.text() == "接收任务"
        peer.change_status_button.click()
        pump_until(app, lambda: not peer.busy and not peer.polling)
        assert peer.change_status_button.text() == "开始处理"
        peer.change_status_button.click()
        pump_until(app, lambda: not peer.busy and not peer.polling)
        assert not peer.change_status_button.isEnabled() and peer.submit_result_button.isEnabled()
    finally:
        for window in (peer, host):
            if window:
                window.timer.stop()
                if window.pair_dialog:
                    window.pair_dialog.close()
                pump_until(app, lambda: not window.busy and not window.polling)
                if window.runtime:
                    window.runtime.close()
                if window.client:
                    window.client.close()
                window.ready_to_close = True
                window.close()


def test_client_pairing_dialog_reports_invalid_paste_without_a_request():
    app = QApplication.instance() or QApplication([])
    dialog = PairingDialog()
    requests = []
    dialog.requested.connect(lambda url, code: requests.append((url, code)))
    dialog.invite.setPlainText("随便一段文字")
    dialog.join()
    assert requests == [] and "完整内容" in dialog.status.text()
    dialog.close()
    app.processEvents()
