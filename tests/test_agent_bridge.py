import json
import os
import secrets
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from codex_bridge.agent import cli
from codex_bridge.agent.broker import JoinInput, Node, ReceiveInput, SendInput
from codex_bridge.agent.lifecycle import control_request
from codex_bridge.agent.local import init_profile, local_control_url, profile_home
from codex_bridge.client.api import BridgeClient
from codex_bridge.config import CHUNK_SIZE
from codex_bridge.models import new_id
from codex_bridge.services.files import file_hash
from codex_bridge.storage.store import BridgeError


class MemoryVault:
    """Test-only injectable vault: secrets stay in test process memory."""
    def __init__(self):
        self.values = {}

    def put(self, key, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def nodes(tmp_path):
    endpoints = []
    try:
        for name in ("windows-codex", "mac-codex"):
            root = profile_home("test", tmp_path / name)
            init_profile(root, name=name, listen="127.0.0.1", port=47821)
            vault = MemoryVault()
            token = secrets.token_urlsafe(48)
            vault.put("control", token)
            node = Node(root, vault, token)
            node.start()
            endpoints.append(node)
        yield endpoints
    finally:
        for endpoint in reversed(endpoints):
            endpoint.close()


def call(node, method, path, **kwargs):
    return control_request(node.root, method, path, vault=node.vault, **kwargs)


def connect(sender, receiver, alias):
    invitation = call(receiver, "POST", "/invite")["invitation"]
    response = call(sender, "POST", "/join", json={"alias": alias, "invitation": invitation})
    assert response["status"] == "waiting_for_approval"
    pending = call(receiver, "GET", "/pending")
    assert pending[0]["id"] == sender.device.id
    assert "request_id" not in pending[0]
    call(receiver, "POST", "/approve", json={"device_id": sender.device.id, "accepted": True})
    assert call(sender, "GET", "/peers")[0]["status"] == "paired"


def sample_delivery(tmp_path, peer="windows"):
    files = tmp_path / "artifacts"
    files.mkdir(exist_ok=True)
    report = files / "执行报告.md"
    report.write_text("# SpaceWatch iOS\n已完成页面复刻。\n测试：12 passed。\n遗留：推送权限待真机验证。", encoding="utf-8")
    archive = files / "ios-changes.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("README.md", "示例代码产物，不自动解压或执行")
    screenshot = files / "截图.png"
    screenshot.write_bytes(b"test-image-bytes")
    body = SendInput(peer=peer, project="SpaceWatch", title="iOS 第 12 轮执行交付", report=str(report),
                     files=[str(archive), str(screenshot)])
    return body, report, archive, screenshot


def test_spacewatch_delivery_receive_read_and_reverse_instruction(nodes, tmp_path):
    windows, mac = nodes
    connect(mac, windows, "windows")
    body, report, archive, screenshot = sample_delivery(tmp_path)
    sent = call(mac, "POST", "/send", json=body.model_dump())
    assert sent["status"] == "delivered_to_receiver" and sent["files"] == 3
    assert call(mac, "GET", "/delivery/" + body.id)["read_at"] is None
    inbox = call(windows, "GET", "/inbox", params={"project": "SpaceWatch"})
    assert len(inbox) == 1 and inbox[0]["received_at"] is None
    receipt = call(windows, "POST", "/receive", json={"project": "SpaceWatch"})
    assert receipt["status"] == "received_verified"
    assert Path(receipt["report_path"]).read_bytes() == report.read_bytes()
    received_files = {Path(item["path"]).name: Path(item["path"]) for item in receipt["files"]}
    for source in (archive, screenshot):
        assert received_files[source.name].read_bytes() == source.read_bytes()
    assert not list(Path(receipt["directory"]).rglob("ios-changes/"))
    before_read = call(mac, "GET", "/delivery/" + body.id)
    assert before_read["received_at"] and not before_read["read_at"]
    # Simulate the agent reading the actual report, then explicitly acknowledging it.
    assert "推送权限" in Path(receipt["report_path"]).read_text(encoding="utf-8")
    call(windows, "POST", "/read/" + body.id)
    assert call(mac, "GET", "/delivery/" + body.id)["read_at"]
    assert call(windows, "POST", "/receive", json={"project": "SpaceWatch"})["status"] == "nothing_new"
    # Reverse transfer uses the same mechanism after the reverse direction is paired.
    connect(windows, mac, "mac")
    instructions = report.parent / "下一轮执行单.md"
    instructions.write_text("请验证 iOS 推送权限，参考附件中的 Android 实现。", encoding="utf-8")
    next_task = SendInput(peer="mac", project="SpaceWatch", title="第 13 轮执行单", report=str(instructions),
                          files=[str(archive)])
    call(windows, "POST", "/send", json=next_task.model_dump())
    reverse = call(mac, "POST", "/receive", json={"project": "SpaceWatch"})
    assert Path(reverse["report_path"]).read_bytes() == instructions.read_bytes()


def test_agent_retry_is_idempotent_and_source_changes_rejected(nodes, tmp_path):
    windows, mac = nodes
    connect(mac, windows, "windows")
    body, report, _, _ = sample_delivery(tmp_path)
    call(mac, "POST", "/send", json=body.model_dump())
    call(mac, "POST", "/retry/" + body.id)
    assert len(call(windows, "GET", "/inbox")) == 1
    assert len(call(mac, "GET", "/outbox")) == 1
    report.write_text("changed", encoding="utf-8")
    with pytest.raises(BridgeError, match="源文件"):
        call(mac, "POST", "/retry/" + body.id)
    assert call(mac, "GET", "/outbox")[0]["status"] == "failed"


def test_interrupted_delivery_retries_same_id_and_preserves_complete_attachments(nodes, tmp_path, monkeypatch, capsys):
    windows, mac = nodes
    connect(mac, windows, "windows")
    report = tmp_path / "断网验证.md"
    report.write_text("# 合成中断测试", encoding="utf-8")
    archive = (tmp_path / "大附件.zip").resolve()
    mib = 512 if os.environ.get("AGENT_BRIDGE_LARGE_RETRY") == "1" else 4
    with zipfile.ZipFile(archive, "w") as zipped, zipped.open("payload.bin", "w") as target:
        chunk = os.urandom(CHUNK_SIZE)
        for _ in range(mib):
            target.write(chunk)

    store = windows.runtime.control.store
    upload = BridgeClient.upload
    uploaded = []
    observed_partial = []

    def interrupt_first_archive(client, task_id, metadata, path, progress=None):
        uploaded.append(path.name)
        if path != archive or observed_partial:
            return upload(client, task_id, metadata, path, progress)

        def interrupt(_, sent, __):
            cutoff = mib // 2 * CHUNK_SIZE
            if sent <= cutoff:
                return
            partial = store.path_for(metadata.id).with_suffix(".part")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    with partial.open("rb") as handle:
                        size = handle.seek(0, os.SEEK_END)
                except FileNotFoundError:
                    size = 0
                # The server's buffered file can still hold the last part of a socket read.
                if size >= cutoff - 64 * 1024:
                    observed_partial.append((partial, size))
                    raise httpx.WriteError("synthetic socket interruption")
                time.sleep(0.01)
            raise RuntimeError("Receiver did not write the first half of the archive")

        return upload(client, task_id, metadata, path, interrupt)

    monkeypatch.setattr(BridgeClient, "upload", interrupt_first_archive)
    monkeypatch.setattr(cli, "control_request",
                        lambda root, method, path, **kwargs: control_request(root, method, path, vault=mac.vault, **kwargs))
    delivery_id = new_id()
    args = ["--home", str(mac.root)]
    with pytest.raises(SystemExit) as failed:
        cli.main([*args, "send", "--to", "windows", "--id", delivery_id, "--title", "中断验证",
                  "--report", str(report), "--file", str(archive)])
    error = json.loads(capsys.readouterr().out)
    assert observed_partial, "The interruption did not reach the expected upload position"
    assert failed.value.code == 1 and error["error"]["code"] == "offline"
    assert error["delivery_id"] == delivery_id and "outbox" in error["action"]
    assert windows.inbox() == []
    assert mac.outbox()[0]["status"] == "failed"
    partial, interrupted_bytes = observed_partial[0]
    deadline = time.monotonic() + 10
    while partial.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not partial.exists()
    assert call(mac, "GET", "/delivery/" + delivery_id)["receiver_status"] == "draft"

    cli.main([*args, "retry", delivery_id])
    delivered = json.loads(capsys.readouterr().out)
    assert delivered["status"] == "delivered_to_receiver"
    assert delivered["delivery_id"] == delivery_id
    assert call(mac, "GET", "/delivery/" + delivery_id)["receiver_status"] == "delivered_to_receiver"
    assert uploaded == [report.name, archive.name, archive.name]
    assert [item["delivery_id"] for item in windows.inbox()] == [delivery_id]
    received = windows.receive(ReceiveInput(id=delivery_id))
    assert Path(received["report_path"]).read_text(encoding="utf-8") == "# 合成中断测试"
    received_zip = next(Path(item["path"]) for item in received["files"] if Path(item["path"]).name == archive.name)
    size, sha256 = file_hash(archive)
    assert file_hash(received_zip) == (size, sha256)
    if mib == 512:
        with capsys.disabled():
            print(json.dumps({"archive_bytes": size, "interrupted_after_bytes": interrupted_bytes,
                              "sha256": sha256, "inbox_count": 1, "same_id": True,
                              "completed_report_reused": True, "partial_cleaned": True}))


def test_local_admin_not_exposed_on_lan_and_receipts_are_private(nodes, tmp_path):
    windows, mac = nodes
    with httpx.Client(trust_env=False) as client:
        assert client.post(windows.control_url + "/local/invite").status_code == 401
        assert client.post(windows.runtime.url + "/local/invite").status_code == 404
        assert client.get(windows.control_url + "/openapi.json").status_code == 404
    connect(mac, windows, "windows")
    body, _, _, _ = sample_delivery(tmp_path)
    call(mac, "POST", "/send", json=body.model_dump())
    with httpx.Client(trust_env=False) as client:
        assert client.get(windows.runtime.url + "/api/v1/agent/receipts/" + body.id).status_code == 401
    call(windows, "POST", "/receive", json={"id": body.id})
    remote_receipt = call(mac, "GET", "/delivery/" + body.id)
    assert "directory" not in remote_receipt and "report_path" not in remote_receipt


def test_no_secret_in_profile_or_outbox_and_pending_approval_required(nodes, tmp_path):
    windows, mac = nodes
    code = call(windows, "POST", "/invite")["invitation"]
    mac.begin_join(JoinInput(alias="windows", invitation=code))
    body, _, _, _ = sample_delivery(tmp_path)
    with pytest.raises(BridgeError, match="尚未配对"):
        mac.send(body)
    call(windows, "POST", "/approve", json={"device_id": mac.device.id})
    mac.poll_joins()
    mac.send(body)
    for node in nodes:
        secrets_to_check = list(node.vault.values.values()) + [code]
        for path in node.root.rglob("*.json"):
            contents = path.read_text(encoding="utf-8")
            assert all(secret not in contents for secret in secrets_to_check)


def test_receiver_restart_preserves_history_and_peer_credentials(nodes, tmp_path):
    windows, mac = nodes
    connect(mac, windows, "windows")
    body, report, _, _ = sample_delivery(tmp_path)
    mac.send(body)
    token = mac.vault.get("peer:windows")
    settings = windows.runtime.control.store.settings
    windows.close()
    # Force the same bind port after restart so the peer's saved URL remains usable.
    windows.config["preferred_port"] = settings.port
    from codex_bridge.agent.local import write_json
    write_json(windows.root / "agent.json", windows.config)
    windows.vault.put("control", secrets.token_urlsafe(48))
    restarted = Node(windows.root, windows.vault, windows.vault.get("control"))
    nodes[0] = restarted
    restarted.start()
    assert mac.vault.get("peer:windows") == token
    assert call(mac, "GET", "/delivery/" + body.id)["received_at"] is None
    received = restarted.receive(ReceiveInput(id=body.id))
    assert Path(received["report_path"]).read_bytes() == report.read_bytes()


def test_receive_is_idempotent_but_checks_local_copy(nodes, tmp_path):
    windows, mac = nodes
    connect(mac, windows, "windows")
    body, _, _, _ = sample_delivery(tmp_path)
    mac.send(body)
    first = windows.receive(ReceiveInput(id=body.id))
    second = windows.receive(ReceiveInput(id=body.id))
    assert first["directory"] == second["directory"]
    Path(first["report_path"]).write_text("local edit", encoding="utf-8")
    with pytest.raises(BridgeError, match="副本已改变"):
        windows.receive(ReceiveInput(id=body.id))


def test_revoke_prevents_agent_send(nodes, tmp_path):
    windows, mac = nodes
    connect(mac, windows, "windows")
    call(windows, "POST", "/revoke/" + mac.device.id)
    body, _, _, _ = sample_delivery(tmp_path)
    with pytest.raises(BridgeError):
        mac.send(body)
    assert mac.outbox()[0]["status"] == "failed"


def test_local_config_validation_and_idempotent_setup(tmp_path):
    root = profile_home("one", tmp_path / "profile")
    first = init_profile(root, "windows", listen="127.0.0.1")
    assert init_profile(root, "different") == first
    for invalid in ["http://8.8.8.8:123", "http://localhost:123", "https://127.0.0.1:123"]:
        with pytest.raises(ValueError):
            local_control_url(invalid)
    with pytest.raises(ValueError):
        profile_home("../escape", tmp_path)
    assert local_control_url("http://127.0.0.1:123") == "http://127.0.0.1:123"
    assert json.loads((root / "agent.json").read_text(encoding="utf-8"))["device"]["id"]


def test_read_requires_a_received_delivery(nodes):
    with pytest.raises(BridgeError, match="先 receive"):
        nodes[0].acknowledge(new_id())
