import hashlib
import time

import httpx
import pytest

from codex_bridge.models import Attachment, PairInput, TaskInput
from codex_bridge.services.identity import save_preferences, secure_token


def test_interrupted_stream_is_cleaned_and_retry_publishes(bridge):
    api, store = bridge["api"], bridge["store"]
    content = b"x" * 128
    file = Attachment(original_filename="archive.zip", size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    model = TaskInput(title="断线测试", description_md="retry", recipient_device_id=bridge["mac"].id, attachments=[file])
    api.post("/api/v1/tasks", json=model.model_dump(), headers=bridge["host_headers"])
    path = f"/api/v1/tasks/{model.id}/attachments/{file.id}/content"
    # A truncated request is a real failure even if its HTTP framing is otherwise valid.
    assert api.put(path, content=content[:20], headers=bridge["host_headers"]).status_code == 422
    assert not list(store.files.glob("*.part"))
    assert not store.path_for(file.id).exists()
    assert store.list_tasks(bridge["mac"].id) == []
    assert api.put(path, content=content, headers=bridge["host_headers"]).status_code == 200
    assert api.post(f"/api/v1/tasks/{model.id}/publish", headers=bridge["host_headers"]).status_code == 200
    assert len(store.list_tasks(bridge["mac"].id)) == 1


def test_real_socket_disconnect_and_idempotent_retry(tmp_path):
    import socket

    from codex_bridge.client.api import BridgeClient
    from codex_bridge.config import Settings
    from codex_bridge.models import DeviceInput
    from codex_bridge.server.runtime import HostRuntime

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    host = DeviceInput(display_name="Host", platform="windows")
    peer = DeviceInput(display_name="Peer", platform="macos")
    runtime = HostRuntime(Settings(tmp_path / "host", port=port), host)
    runtime.start()
    runtime.control.store.register(peer)
    client = BridgeClient(runtime.url, host, runtime.control.token)
    data = b"x" * 1024**2
    item = Attachment(original_filename="broken.zip", size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    task = TaskInput(title="socket abort", description_md="retry", recipient_device_id=peer.id, attachments=[item])
    try:
        client.request("POST", "/tasks", json=task.model_dump())
        path = f"/api/v1/tasks/{task.id}/attachments/{item.id}/content"
        with socket.create_connection(("127.0.0.1", port)) as connection:
            headers = (f"PUT {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                       f"Authorization: Bearer {client.token}\r\nContent-Length: {len(data)}\r\n\r\n")
            connection.sendall(headers.encode() + data[:100])
            time.sleep(0.1)
        time.sleep(0.2)
        assert not list(runtime.control.store.files.glob("*.part"))
        assert not runtime.control.store.path_for(item.id).exists()
        source = tmp_path / item.original_filename
        source.write_bytes(data)
        client.send_task(task, [source])
        assert client.request("GET", f"/tasks/{task.id}")["status"] == "pending"
    finally:
        client.close()
        runtime.close()


def test_disk_space_and_task_total_limits(bridge, monkeypatch):
    from collections import namedtuple

    api, store = bridge["api"], bridge["store"]
    item = Attachment(original_filename="test.bin", size_bytes=1, sha256=hashlib.sha256(b"x").hexdigest())
    model = TaskInput(title="磁盘空间", description_md="test", recipient_device_id=bridge["mac"].id, attachments=[item])
    api.post("/api/v1/tasks", json=model.model_dump(), headers=bridge["host_headers"])
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("codex_bridge.server.app.shutil.disk_usage", lambda _: usage(100, 100, 0))
    response = api.put(f"/api/v1/tasks/{model.id}/attachments/{item.id}/content", content=b"x", headers=bridge["host_headers"])
    assert response.status_code == 507
    assert not store.path_for(item.id).exists()
    assert not list(store.files.glob("*.part"))
    files = [Attachment(original_filename=f"{index}.bin", size_bytes=store.settings.max_file_bytes, sha256="0" * 64)
             for index in range(3)]
    large = model.model_copy(update={"id": __import__("uuid").uuid4().__str__(), "attachments": files})
    assert api.post("/api/v1/tasks", json=large.model_dump(), headers=bridge["host_headers"]).status_code == 413


def test_no_plaintext_token_fallback_or_preferences_leak(tmp_path, monkeypatch):
    import keyring

    class InsecureBackend:
        def set_password(self, *args):
            pytest.fail("An unapproved backend must never be used")
    monkeypatch.setattr(keyring, "get_keyring", lambda: InsecureBackend())
    assert secure_token("http://127.0.0.1", "device", "very-secret") is None
    save_preferences(tmp_path, {"mode": "client", "token": "very-secret", "password": "very-secret"})
    assert "very-secret" not in (tmp_path / "preferences.json").read_text(encoding="utf-8")


def test_pair_invalid_unicode_and_validation_does_not_echo_secret(bridge):
    body = bridge["mac"].model_dump() | {"code": "秘密密码秘密密码"}
    response = bridge["api"].post("/api/v1/pair", json=body)
    assert response.status_code == 422
    assert "秘密" not in response.text
    with pytest.raises(ValueError):
        PairInput(**body)


def test_redirects_do_not_forward_credentials(tmp_path):
    from codex_bridge.client.api import BridgeClient
    from codex_bridge.models import DeviceInput
    from codex_bridge.storage.store import BridgeError

    client = BridgeClient("http://127.0.0.1:1", DeviceInput(display_name="test", platform="windows"), "secret")
    client.http.close()
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://elsewhere.invalid/"})
    client.http = httpx.Client(base_url=client.url, transport=httpx.MockTransport(respond), follow_redirects=False)
    with pytest.raises(BridgeError, match="重定向"):
        client.request("GET", "/devices")
    assert len(requests) == 1
    client.close()
