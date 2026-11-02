import hashlib
import time

import pytest
from pydantic import ValidationError

from codex_bridge.config import Settings
from codex_bridge.models import Attachment, DeviceInput, ResultInput, TaskInput, new_id
from codex_bridge.storage.store import BridgeError, Store


def task_for(bridge, attachments=None):
    return TaskInput(title="iOS 个人中心", description_md="# 开发指令\n保持 API 一致。",
                     recipient_device_id=bridge["mac"].id, attachments=attachments or [])


def create_published(bridge):
    model = task_for(bridge)
    api = bridge["api"]
    assert api.post("/api/v1/tasks", json=model.model_dump(), headers=bridge["host_headers"]).status_code == 200
    assert api.post(f"/api/v1/tasks/{model.id}/publish", headers=bridge["host_headers"]).status_code == 200
    return model


@pytest.mark.parametrize("name", ["../secret", "C:\\secret", "/etc/passwd", "NUL", "COM1.txt", "a.", "a ", "a\x00b"])
def test_unsafe_filenames_rejected(name):
    with pytest.raises(ValidationError):
        Attachment(original_filename=name, size_bytes=1, sha256="0" * 64)


def test_uuid_and_identity_spoofing(bridge):
    body = task_for(bridge).model_dump() | {"sender_device_id": bridge["mac"].id}
    response = bridge["api"].post("/api/v1/tasks", json=body, headers=bridge["host_headers"])
    assert response.status_code == 422
    assert "sender_device_id" not in response.text
    with pytest.raises(ValidationError):
        DeviceInput(id="../path", display_name="bad", platform="windows")


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "8.8.8.8", "169.254.0.1"])
def test_bind_rejects_public_and_wildcard(tmp_path, host):
    with pytest.raises(ValueError):
        Settings(tmp_path, host=host).validate()


@pytest.mark.parametrize("host", ["127.0.0.1", "192.168.1.5", "100.64.1.2", "::1"])
def test_bind_allows_private(tmp_path, host):
    Settings(tmp_path, host=host).validate()


def test_pairing_requires_local_approval_and_is_single_use(bridge):
    api, control = bridge["api"], bridge["control"]
    code = control.open_pairing()
    body = DeviceInput(display_name="新 Mac", platform="macos").model_dump() | {"code": code}
    response = api.post("/api/v1/pair", json=body)
    assert response.status_code == 202
    key = response.json()["request_id"]
    assert api.post("/api/v1/pair/status", json={"request_id": key}).json() == {"status": "pending"}
    assert api.post("/api/v1/pair", json=body).status_code == 403
    control.approve(key)
    response = api.post("/api/v1/pair/status", json={"request_id": key}).json()
    headers = {"Authorization": "Bearer " + response["token"]}
    assert api.get("/api/v1/devices", headers=headers).status_code == 200
    assert api.post("/api/v1/pair/status", json={"request_id": key}).status_code == 410
    control.store.revoke(body["id"])
    assert api.get("/api/v1/devices", headers=headers).status_code == 401
    assert response["token"].encode() not in control.store.db_path.read_bytes()


def test_pairing_expiry_and_rate_limit(bridge):
    control, api = bridge["control"], bridge["api"]
    code = control.open_pairing()
    control.expires = time.monotonic() - 1
    body = DeviceInput(display_name="Mac", platform="macos").model_dump() | {"code": code}
    for _ in range(5):
        assert api.post("/api/v1/pair", json=body).status_code == 403
    assert api.post("/api/v1/pair", json=body).status_code == 429


def test_pair_rejection_and_close(bridge):
    control, api = bridge["control"], bridge["api"]
    body = DeviceInput(display_name="Mac", platform="macos").model_dump() | {"code": control.open_pairing()}
    key = api.post("/api/v1/pair", json=body).json()["request_id"]
    control.approve(key, False)
    assert api.post("/api/v1/pair/status", json={"request_id": key}).json()["status"] == "rejected"
    control.close_pairing()
    assert api.post("/api/v1/pair/status", json={"request_id": key}).status_code == 410


def test_auth_and_cross_device_permissions(bridge):
    api = bridge["api"]
    model = create_published(bridge)
    assert api.get("/api/v1/tasks").status_code == 401
    assert api.get(f"/api/v1/tasks/{model.id}", headers=bridge["other_headers"]).status_code == 404
    assert api.get("/api/v1/tasks", headers=bridge["other_headers"]).json() == []
    assert api.patch(f"/api/v1/tasks/{model.id}/status", json={"status": "accepted"},
                     headers=bridge["host_headers"]).status_code == 403


def test_transitions_history_and_restart(bridge):
    api, store = bridge["api"], bridge["store"]
    model = create_published(bridge)
    path = f"/api/v1/tasks/{model.id}/status"
    assert api.patch(path, json={"status": "completed"}, headers=bridge["mac_headers"]).status_code == 409
    for status in ["accepted", "accepted", "in_progress", "failed", "in_progress", "completed"]:
        assert api.patch(path, json={"status": status}, headers=bridge["mac_headers"]).status_code == 200
    restarted = Store(store.settings)
    task = restarted.get_task(bridge["host"].id, model.id)
    assert task["status"] == "completed"
    assert [item["status"] for item in task["events"]] == [
        "pending", "accepted", "in_progress", "failed", "in_progress", "completed"]


def test_manifest_publication_idempotency_and_corruption(bridge):
    api = bridge["api"]
    content = "中文需求\n".encode()
    attachment = Attachment(original_filename="需求.md", size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    model = task_for(bridge, [attachment])
    for _ in range(2):
        assert api.post("/api/v1/tasks", json=model.model_dump(), headers=bridge["host_headers"]).status_code == 200
    assert api.get("/api/v1/tasks", headers=bridge["mac_headers"]).json() == []
    assert api.post(f"/api/v1/tasks/{model.id}/publish", headers=bridge["host_headers"]).status_code == 409
    path = f"/api/v1/tasks/{model.id}/attachments/{attachment.id}/content"
    assert api.put(path, content=b"x" * len(content), headers=bridge["host_headers"]).status_code == 422
    assert not list(bridge["store"].files.glob("*.part"))
    assert api.get(f"/api/v1/attachments/{attachment.id}/download", headers=bridge["mac_headers"]).status_code == 404
    for _ in range(2):
        assert api.put(path, content=content, headers=bridge["host_headers"]).status_code == 200
        assert api.post(f"/api/v1/tasks/{model.id}/publish", headers=bridge["host_headers"]).status_code == 200
    response = api.get(f"/api/v1/attachments/{attachment.id}/download", headers=bridge["mac_headers"])
    assert response.content == content
    assert api.get(f"/api/v1/attachments/{attachment.id}/download", headers=bridge["other_headers"]).status_code == 404
    assert len(api.get("/api/v1/tasks", headers=bridge["mac_headers"]).json()) == 1
    assert len(list(bridge["store"].files.glob("*.bin"))) == 1
    different = model.model_copy(update={"title": "不同内容"})
    assert api.post("/api/v1/tasks", json=different.model_dump(), headers=bridge["host_headers"]).status_code == 409


def test_limits_rollback_and_cross_task_attachment_id(bridge):
    store = bridge["store"]
    attachment = Attachment(original_filename="large.zip", size_bytes=store.settings.max_file_bytes + 1, sha256="0" * 64)
    model = task_for(bridge, [attachment])
    with pytest.raises(BridgeError, match="单文件"):
        store.create_task(bridge["host"].id, model)
    assert store.list_tasks(bridge["host"].id) == []
    attachment.size_bytes = 1
    model = task_for(bridge, [attachment])
    store.create_task(bridge["host"].id, model)
    different_task = task_for(bridge, [attachment])
    with pytest.raises(BridgeError, match="ID"):
        store.create_task(bridge["host"].id, different_task)
    assert len(store.list_tasks(bridge["host"].id)) == 1


def test_result_transaction_and_reverse_task(bridge):
    store, host, mac = bridge["store"], bridge["host"].id, bridge["mac"].id
    task = create_published(bridge)
    store.set_status(mac, task.id, "accepted")
    store.set_status(mac, task.id, "in_progress")
    result = ResultInput(summary_md="完成，测试通过", outcome="completed", artifacts=[
        Attachment(original_filename="报告.md", size_bytes=0, sha256=hashlib.sha256(b"").hexdigest())])
    store.create_result(mac, task.id, result)
    assert store.get_task(host, task.id)["results"] == []
    with pytest.raises(BridgeError, match="尚未完整"):
        store.publish_result(mac, task.id, result.id)
    assert store.get_task(host, task.id)["status"] == "in_progress"
    attachment = result.artifacts[0]
    store.path_for(attachment.id).touch()
    store.complete_attachment(attachment.id)
    for _ in range(2):
        store.publish_result(mac, task.id, result.id)
    received = store.get_task(host, task.id)
    assert received["status"] == "completed"
    assert len(received["results"]) == 1
    reverse = TaskInput(title="Mac 提问", description_md="请澄清接口", recipient_device_id=host)
    store.create_task(mac, reverse)
    store.publish_task(mac, reverse.id)
    assert store.get_task(host, reverse.id)["sender_device_id"] == mac


def test_search_literals_and_pagination(bridge):
    store, host = bridge["store"], bridge["host"].id
    for title in ["abc_100%", "abcX100X", "测试"]:
        model = task_for(bridge).model_copy(update={"id": new_id(), "title": title})
        store.create_task(host, model)
    assert len(store.list_tasks(host, "_100%")) == 1
    assert len(store.list_tasks(host, "测试")) == 1
    assert len(store.list_tasks(host, limit=2)) == 2
    assert len(store.list_tasks(host, offset=2, limit=2)) == 1
