import hashlib
import json
import socket

import httpx
import pytest

from codex_bridge.client.api import BridgeClient, normalize_url
from codex_bridge.config import Settings
from codex_bridge.models import DeviceInput, ResultInput, TaskInput
from codex_bridge.server.runtime import HostRuntime
from codex_bridge.services.export import export_task
from codex_bridge.services.files import describe_file
from codex_bridge.storage.store import BridgeError


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def live(tmp_path):
    settings = Settings(tmp_path / "host", port=free_port())
    host = DeviceInput(display_name="Windows", platform="windows")
    mac = DeviceInput(display_name="Mac", platform="macos")
    runtime = HostRuntime(settings, host)
    runtime.start()
    client_a = BridgeClient(runtime.url, host, runtime.control.token, tmp_path / "cache-a")
    client_b = BridgeClient(runtime.url, mac, cache_dir=tmp_path / "cache-b")
    code = runtime.control.open_pairing()
    key = client_b.pair_request(code)
    runtime.control.approve(key)
    assert client_b.pair_poll(key)["status"] == "approved"
    yield runtime, client_a, client_b
    client_a.close()
    client_b.close()
    runtime.close()


def test_real_http_round_trip_export_and_restart(live, tmp_path):
    runtime, sender, receiver = live
    source = tmp_path / "source"
    source.mkdir()
    paths = [source / "需求.md", source / "项目.zip", source / "截图.png"]
    for index, path in enumerate(paths):
        path.write_bytes((f"测试附件 {index}\n" * 1000).encode())
    model = TaskInput(title="中文任务", description_md="# iOS\n对齐 Android。", recipient_device_id=receiver.device.id,
                      attachments=[describe_file(path) for path in paths])
    sender.send_task(model, paths)
    sender.send_task(model, paths)  # Lost response/retry must not duplicate task or attachment.
    snapshot = receiver.snapshot()
    assert len(snapshot["tasks"]) == 1
    assert receiver.cached_snapshot() == snapshot
    folder = export_task(receiver, model.id, tmp_path / "exports")
    assert (folder / "TASK.md").read_text(encoding="utf-8").startswith("# 中文任务")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["export_files"]) == 3
    for path in paths:
        assert (folder / "attachments" / path.name).read_bytes() == path.read_bytes()
    for status in ["accepted", "in_progress"]:
        receiver.request("PATCH", f"/tasks/{model.id}/status", json={"status": status})
    report = source / "报告.md"
    report.write_text("完成，测试通过。", encoding="utf-8")
    result = ResultInput(summary_md="已完成", outcome="completed", artifacts=[describe_file(report)])
    receiver.request("POST", f"/tasks/{model.id}/results", json=result.model_dump())
    # A recipient's own unpublished result must not leak incomplete artifacts into an export.
    draft_export = export_task(receiver, model.id, tmp_path / "draft-result-export")
    draft_manifest = json.loads((draft_export / "manifest.json").read_text(encoding="utf-8"))
    assert draft_manifest["results"] == [] and len(draft_manifest["export_files"]) == 3
    receiver.send_result(model.id, result, [report])
    receiver.send_result(model.id, result, [report])
    task = sender.request("GET", f"/tasks/{model.id}")
    assert task["status"] == "completed" and len(task["results"]) == 1
    artifact = task["results"][0]["artifacts"][0]
    downloaded = sender.download(artifact, tmp_path / "downloads")
    assert downloaded.read_bytes() == report.read_bytes()
    token_b = receiver.token
    runtime.close()
    # Local host authorization rotates; peer authorization and history survive restart.
    restarted = HostRuntime(runtime.control.store.settings, sender.device)
    try:
        restarted.start()
        assert receiver.token == token_b
        assert receiver.request("GET", f"/tasks/{model.id}")["status"] == "completed"
        assert receiver.download(artifact, tmp_path / "after-restart").read_bytes() == report.read_bytes()
    finally:
        restarted.close()


def test_filename_collisions_and_export_cleanup(live, tmp_path):
    _, sender, receiver = live
    paths = []
    for index in range(2):
        folder = tmp_path / str(index)
        folder.mkdir()
        path = folder / "同名.md"
        path.write_text(str(index), encoding="utf-8")
        paths.append(path)
    model = TaskInput(title="同名文件", description_md="test", recipient_device_id=receiver.device.id,
                      attachments=[describe_file(path) for path in paths])
    sender.send_task(model, paths)
    folder = export_task(receiver, model.id, tmp_path / "exports")
    files = list((folder / "attachments").iterdir())
    assert len(files) == 2
    assert {file.read_text(encoding="utf-8") for file in files} == {"0", "1"}
    mappings = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["export_files"]
    assert len({item["relative_path"] for item in mappings}) == 2
    # Simulate at-rest corruption: no final export may be reported or left behind.
    sender_file = live[0].control.store.path_for(model.attachments[0].id)
    sender_file.write_bytes(b"corrupt")
    with pytest.raises(BridgeError):
        export_task(receiver, model.id, tmp_path / "broken-exports")
    assert not list((tmp_path / "broken-exports").iterdir())


def test_truncated_download_removes_partials(tmp_path):
    device = DeviceInput(display_name="client", platform="windows")
    client = BridgeClient("http://127.0.0.1:47821", device)
    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"short")),
                               base_url=client.url)
    metadata = {"id": device.id, "original_filename": "test.zip", "size_bytes": 100,
                "sha256": hashlib.sha256(b"x" * 100).hexdigest(), "mime_type": "application/zip"}
    with pytest.raises(BridgeError, match="校验失败"):
        client.download(metadata, tmp_path / "downloads")
    assert not list((tmp_path / "downloads").iterdir())
    client.close()


@pytest.mark.parametrize("url", ["ftp://127.0.0.1", "http://user:secret@host", "http://host/?token=secret", "http://host/path"])
def test_untrusted_urls_rejected(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_second_host_rejected_without_damaging_running_instance(live):
    runtime, sender, _ = live
    with pytest.raises(OSError):
        HostRuntime(runtime.control.store.settings, sender.device)
    assert sender.request("GET", "/health")["status"] == "ok"
