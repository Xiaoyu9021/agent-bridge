from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field

from codex_bridge.agent.local import (
    alias_name,
    automatic_address,
    available_port,
    read_json,
    write_json,
)
from codex_bridge.client.api import BridgeClient
from codex_bridge.config import Settings
from codex_bridge.models import DeviceInput, Model, TaskInput, new_id, utc_now, validate_id
from codex_bridge.server.runtime import HostRuntime
from codex_bridge.services.connection import invitation, parse_invitation
from codex_bridge.services.export import export_task
from codex_bridge.services.files import describe_file, file_hash
from codex_bridge.storage.store import BridgeError


def safe_error(error: Exception) -> dict:
    if isinstance(error, BridgeError):
        return {"code": error.code, "message": error.message}
    if isinstance(error, httpx.TimeoutException):
        return {"code": "timeout", "message": "连接超时，操作结果待确认"}
    if isinstance(error, httpx.RequestError):
        return {"code": "offline", "message": "网络连接失败或传输中断，操作结果待确认"}
    if isinstance(error, OSError):
        return {"code": "file_error", "message": "文件操作失败，请检查文件是否存在、目录权限和磁盘空间"}
    if isinstance(error, ValueError):
        return {"code": "invalid_input", "message": "输入或文件内容无效，请检查命令参数和 UTF-8 报告"}
    return {"code": "operation_failed", "message": "操作失败，未确认成功；请检查 status 和交付记录"}


class JoinInput(Model):
    alias: str = Field(min_length=1, max_length=50)
    invitation: str = Field(min_length=1, max_length=2048)


class ApprovalInput(Model):
    device_id: str
    accepted: bool = True


class SendInput(Model):
    id: str = Field(default_factory=new_id)
    peer: str = Field(min_length=1, max_length=50)
    project: str = Field(default="", max_length=100)
    title: str = Field(min_length=1, max_length=200)
    report: str
    files: list[str] = Field(default_factory=list, max_length=99)


class ReceiveInput(Model):
    id: str | None = None
    project: str = Field(default="", max_length=100)


class Node:
    def __init__(self, root: Path, vault, control_token: str):
        self.root, self.vault, self.control_token = root, vault, control_token
        self.config = read_json(root / "agent.json")
        if not self.config:
            raise BridgeError("not_configured", "请先运行 setup", 409)
        self.device = DeviceInput(**self.config["device"])
        host = automatic_address() if self.config["listen"] == "auto" else self.config["listen"]
        port = available_port(host, self.config["preferred_port"])
        if port != self.config["preferred_port"]:
            self.config["preferred_port"] = port
            write_json(root / "agent.json", self.config)
        self.runtime = HostRuntime(Settings(root / "receiver", host=host, port=port), self.device)
        self.self_client = BridgeClient(self.runtime.url, self.device, self.runtime.control.token)
        self.peers = read_json(root / "peers.json", {})
        self.joins = {}
        self.join_errors = {}
        self.lock = threading.RLock()
        self.pair_poll_lock = threading.Lock()
        self.delivery_locks: dict[str, threading.Lock] = {}
        self.stop_event = threading.Event()
        self.instance = new_id()
        self.control_port = available_port("127.0.0.1", 0)
        self.control_url = f"http://127.0.0.1:{self.control_port}"
        self.admin = self.create_admin()
        self.server = None
        self.admin_thread = None
        self.add_receipt_api()

    def status(self):
        return {"running": True, "device": self.device.model_dump(), "receiver_url": self.runtime.url,
                "instance": self.instance, "inbox": self.config["inbox"],
                "local_only": self.runtime.control.store.settings.host in {"127.0.0.1", "::1"},
                "peers": self.peer_list()}

    def peer_list(self):
        with self.lock:
            output = [dict(alias=key, **value, status="paired") for key, value in self.peers.items()]
            output.extend({"alias": key, "status": "waiting_for_approval"} for key in self.joins)
            output.extend({"alias": key, "status": "pairing_failed", "error": val}
                          for key, val in self.join_errors.items())
            return output

    def begin_join(self, body: JoinInput):
        alias = alias_name(body.alias)
        url, code = parse_invitation(body.invitation)
        client = BridgeClient(url, self.device)
        try:
            key = client.pair_request(code)
        except BaseException:
            client.close()
            raise
        with self.lock:
            if alias in self.joins:
                self.joins[alias]["client"].close()
            self.joins[alias] = {"client": client, "request": key}
            self.join_errors.pop(alias, None)
        return {"alias": alias, "status": "waiting_for_approval", "action": "请在另一台电脑运行 pending 并核对设备名称后 approve"}

    def poll_joins(self):
        with self.pair_poll_lock:
            self._poll_joins()

    def _poll_joins(self):
        with self.lock:
            waiting = list(self.joins.items())
        for alias, entry in waiting:
            client = entry["client"]
            try:
                response = client.pair_poll(entry["request"])
                if response["status"] == "pending":
                    continue
                if response["status"] != "approved":
                    raise BridgeError("rejected", "另一台电脑拒绝了配对，请核对后重新邀请", 403)
                # Secure persistence must succeed before declaring the alias usable.
                self.vault.put("peer:" + alias, client.token)
                with self.lock:
                    self.peers[alias] = {"url": client.url, "device_id": response["host_device_id"],
                                         "paired_at": utc_now()}
                    write_json(self.root / "peers.json", self.peers)
                    self.joins.pop(alias, None)
            except Exception as error:
                # Network outages can be retried until the short-lived request expires.
                if isinstance(error, httpx.RequestError):
                    continue
                with self.lock:
                    self.join_errors[alias] = safe_error(error)
                    self.joins.pop(alias, None)
            finally:
                with self.lock:
                    finished = alias not in self.joins
                if finished:
                    client.close()

    def approve(self, body: ApprovalInput):
        validate_id(body.device_id)
        matches = [item for item in self.runtime.control.pending() if item["id"] == body.device_id]
        if len(matches) != 1:
            raise BridgeError("no_request", "没有此设备的待确认申请，请重新查询 pending", 404)
        self.runtime.control.approve(matches[0]["request_id"], body.accepted)
        return {"device_id": body.device_id, "status": "approved" if body.accepted else "rejected"}

    def remote_client(self, alias: str):
        alias_name(alias)
        with self.lock:
            peer = self.peers.get(alias)
        if not peer:
            raise BridgeError("not_paired", "这个发送别名尚未配对；请先 join 并由另一端确认", 409)
        token = self.vault.get("peer:" + alias)
        if not token:
            raise BridgeError("missing_credentials", "安全凭据丢失，请重新配对", 401)
        return BridgeClient(peer["url"], self.device, token), peer

    def send(self, body: SendInput | None = None, retry_id: str | None = None):
        delivery_id = validate_id(retry_id or body.id)
        with self.lock:
            lock = self.delivery_locks.setdefault(delivery_id, threading.Lock())
        with lock:
            path = self.root / "outbox" / f"{delivery_id}.json"
            record = read_json(path)
            if record:
                if body and record["request"] != body.model_dump():
                    raise BridgeError("id_conflict", "同一交付 ID 已绑定其他内容", 409)
            elif retry_id:
                raise BridgeError("not_found", "交付记录不存在", 404)
            else:
                report = Path(body.report).expanduser()
                if report.is_symlink() or any(Path(item).expanduser().is_symlink() for item in body.files):
                    raise BridgeError("file_invalid", "不接受符号链接，请明确选择目标普通文件", 422)
                report = report.resolve()
                if not report.is_file() or report.stat().st_size > 200 * 1024:
                    raise BridgeError("report_invalid", "请提供不超过 200 KiB 的 UTF-8 执行报告", 422)
                text = report.read_text(encoding="utf-8")
                paths = list(dict.fromkeys([str(report)] + [str(Path(item).expanduser().resolve()) for item in body.files]))
                for item in paths:
                    source = Path(item)
                    if not source.is_file() or source.is_symlink():
                        raise BridgeError("file_invalid", "只能发送明确选择的普通文件，不接受目录或符号链接", 422)
                attachments = [describe_file(Path(item)) for item in paths]
                preview, peer = self.remote_client(body.peer)
                preview.close()
                model = TaskInput(id=delivery_id, title=body.title, project=body.project, description_md=text,
                                  recipient_device_id=peer["device_id"], attachments=attachments)
                record = {"request": body.model_dump(), "task": model.model_dump(), "paths": paths,
                          "state": "prepared", "created_at": utc_now()}
                write_json(path, record)
            client = None
            try:
                model = TaskInput(**record["task"])
                client, peer = self.remote_client(record["request"]["peer"])
                if peer["device_id"] != model.recipient_device_id:
                    raise BridgeError("peer_changed", "别名已指向不同设备，旧交付不能重试到新设备", 409)
                for source, item in zip(record["paths"], model.attachments):
                    if file_hash(Path(source)) != (item.size_bytes, item.sha256):
                        raise BridgeError("source_changed", "源文件自首次发送后已改变；请用新交付 ID 发送，不能修改旧清单", 409)
                record.update(state="sending", updated_at=utc_now())
                record.pop("error", None)
                write_json(path, record)
                client.send_task(model, [Path(item) for item in record["paths"]])
                record.update(state="delivered_to_receiver", updated_at=utc_now())
                write_json(path, record)
                return self.public_delivery(record)
            except Exception as error:
                record.update(state="failed", error=safe_error(error), updated_at=utc_now())
                write_json(path, record)
                result = safe_error(error)
                raise BridgeError(result["code"], result["message"], 409) from None
            finally:
                if client:
                    client.close()

    @staticmethod
    def public_delivery(record):
        return {"delivery_id": record["task"]["id"], "project": record["request"]["project"],
                "title": record["task"]["title"], "peer": record["request"]["peer"], "status": record["state"],
                "files": len(record["paths"]), "size_bytes": sum(item["size_bytes"] for item in record["task"]["attachments"]),
                "error": record.get("error")}

    def outbox(self):
        return [self.public_delivery(read_json(path)) for path in sorted((self.root / "outbox").glob("*.json"))]

    def inbox(self, project=""):
        tasks = []
        offset = 0
        while True:
            page = self.runtime.control.store.list_tasks(self.device.id, offset=offset, limit=200)
            for task in page:
                if task["recipient_device_id"] != self.device.id or task["status"] == "draft":
                    continue
                if project and task.get("project") != project:
                    continue
                receipt = read_json(self.root / "receipts" / f"{task['id']}.json", {})
                tasks.append({"delivery_id": task["id"], "project": task.get("project", ""), "title": task["title"],
                              "created_at": task["created_at"], "files": len(task["attachments"]),
                              "received_at": receipt.get("received_at"), "read_at": receipt.get("read_at")})
            offset += len(page)
            if len(page) < 200:
                break
        return tasks

    def receive(self, body: ReceiveInput):
        if body.id:
            delivery_id = validate_id(body.id)
        else:
            unread = [item for item in self.inbox(body.project) if not item["received_at"]]
            if not unread:
                return {"status": "nothing_new", "message": "没有尚未收取的新交付"}
            delivery_id = max(unread, key=lambda item: item["created_at"])["delivery_id"]
        with self.lock:
            lock = self.delivery_locks.setdefault(delivery_id, threading.Lock())
        with lock:
            task = self.runtime.control.store.get_task(self.device.id, delivery_id)
            if task["recipient_device_id"] != self.device.id or task["status"] == "draft":
                raise BridgeError("not_recipient", "只能收取发送给当前端点的已发布交付", 403)
            receipt_path = self.root / "receipts" / f"{delivery_id}.json"
            receipt = read_json(receipt_path)
            if receipt:
                # Verify again instead of reporting success for a locally deleted or corrupted receipt.
                for item in receipt["files"]:
                    if file_hash(Path(item["path"])) != (item["size_bytes"], item["sha256"]):
                        raise BridgeError("local_copy_changed", "本地收件副本已改变，请保留修改后另行重新导出", 409)
            else:
                folder = export_task(self.self_client, delivery_id, Path(self.config["inbox"]))
                manifest = read_json(folder / "manifest.json")
                files = [{"path": str(folder / item["relative_path"]), "sha256": item["sha256"],
                          "size_bytes": item["size_bytes"]} for item in manifest["export_files"]]
                first = task["attachments"][0]["id"] if task["attachments"] else None
                report = next((item for item in manifest["export_files"] if item["attachment_id"] == first), None)
                receipt = {"delivery_id": delivery_id, "status": "received_verified", "directory": str(folder),
                           "report_path": str(folder / report["relative_path"]) if report else str(folder / "TASK.md"),
                           "task_path": str(folder / "TASK.md"), "manifest_path": str(folder / "manifest.json"),
                           "files": files, "received_at": utc_now(), "read_at": None}
                write_json(receipt_path, receipt)
            if task["status"] == "pending":
                self.runtime.control.store.set_status(self.device.id, delivery_id, "accepted")
            return receipt

    def acknowledge(self, delivery_id):
        delivery_id = validate_id(delivery_id)
        path = self.root / "receipts" / f"{delivery_id}.json"
        receipt = read_json(path)
        if not receipt:
            raise BridgeError("not_received", "请先 receive 并实际阅读报告，再标记已读", 409)
        receipt["read_at"] = receipt["read_at"] or utc_now()
        write_json(path, receipt)
        return {key: receipt[key] for key in ("delivery_id", "received_at", "read_at")}

    def add_receipt_api(self):
        @self.runtime.app.get("/api/v1/agent/receipts/{delivery_id}")
        def receipt(delivery_id: str, authorization: str = Header(default="")):
            if not authorization.startswith("Bearer "):
                raise BridgeError("unauthorized", "需要设备授权", 401)
            actor = self.runtime.control.store.authenticate(authorization[7:])
            task = self.runtime.control.store.get_task(actor["id"], delivery_id)
            validate_id(delivery_id)
            result = read_json(self.root / "receipts" / f"{delivery_id}.json", {})
            receiver_status = "draft" if task["status"] == "draft" else "delivered_to_receiver"
            return {"delivery_id": delivery_id, "receiver_status": receiver_status, "received_at": result.get("received_at"),
                    "read_at": result.get("read_at")}

    def create_admin(self):
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        def auth(authorization: str = Header(default="")):
            if not secrets.compare_digest(authorization.encode(), ("Bearer " + self.control_token).encode()):
                raise BridgeError("unauthorized", "本地控制授权无效，请重新启动接收进程", 401)

        @app.middleware("http")
        async def body_limit(request: Request, call_next):
            if request.method == "POST":
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 256 * 1024:
                        return JSONResponse({"error": {"code": "too_large", "message": "控制请求过大"}}, 413)
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            return await call_next(request)

        @app.exception_handler(BridgeError)
        async def bridge_error(request, error):
            return JSONResponse({"error": safe_error(error)}, error.status)

        @app.exception_handler(RequestValidationError)
        async def invalid(request, error):
            return JSONResponse({"error": {"code": "invalid_input", "message": "控制请求字段无效"}}, 422)

        @app.exception_handler(Exception)
        async def failed(request, error):
            return JSONResponse({"error": safe_error(error)}, 500)

        @app.get("/local/status", dependencies=[Depends(auth)])
        def status():
            return self.status()

        @app.post("/local/invite", dependencies=[Depends(auth)])
        def invite():
            code = self.runtime.control.open_pairing()
            return {"invitation": invitation(self.runtime.url, code), "expires_in_seconds": 600,
                    "local_only": self.runtime.control.store.settings.host == "127.0.0.1",
                    "message": "只把这段短时连接信息交给本人的另一端；收到申请后还需本机确认"}

        @app.get("/local/pending", dependencies=[Depends(auth)])
        def pending():
            return [{key: value for key, value in item.items() if key != "request_id"}
                    for item in self.runtime.control.pending()]

        @app.post("/local/approve", dependencies=[Depends(auth)])
        def approve(body: ApprovalInput):
            return self.approve(body)

        @app.post("/local/join", dependencies=[Depends(auth)])
        def join(body: JoinInput):
            return self.begin_join(body)

        @app.get("/local/peers", dependencies=[Depends(auth)])
        def peers():
            self.poll_joins()
            return self.peer_list()

        @app.post("/local/send", dependencies=[Depends(auth)])
        def send(body: SendInput):
            return self.send(body)

        @app.post("/local/retry/{delivery_id}", dependencies=[Depends(auth)])
        def retry(delivery_id: str):
            return self.send(retry_id=delivery_id)

        @app.get("/local/outbox", dependencies=[Depends(auth)])
        def outbox():
            return self.outbox()

        @app.get("/local/inbox", dependencies=[Depends(auth)])
        def inbox(project: str = ""):
            return self.inbox(project)

        @app.post("/local/receive", dependencies=[Depends(auth)])
        def receive(body: ReceiveInput):
            return self.receive(body)

        @app.post("/local/read/{delivery_id}", dependencies=[Depends(auth)])
        def read(delivery_id: str):
            return self.acknowledge(delivery_id)

        @app.get("/local/delivery/{delivery_id}", dependencies=[Depends(auth)])
        def delivery(delivery_id: str):
            record = read_json(self.root / "outbox" / f"{validate_id(delivery_id)}.json")
            if not record:
                raise BridgeError("not_found", "交付记录不存在", 404)
            client, _ = self.remote_client(record["request"]["peer"])
            try:
                return self.public_delivery(record) | client.request("GET", f"/agent/receipts/{delivery_id}")
            finally:
                client.close()

        @app.post("/local/revoke/{device_id}", dependencies=[Depends(auth)])
        def revoke(device_id: str):
            self.runtime.control.store.revoke(validate_id(device_id))
            return {"status": "revoked", "device_id": device_id}

        @app.post("/local/stop", dependencies=[Depends(auth)])
        def stop():
            self.stop_event.set()
            return {"status": "stopping"}

        return app

    def start(self):
        import os

        import uvicorn
        self.runtime.start()
        self.server = uvicorn.Server(uvicorn.Config(self.admin, host="127.0.0.1", port=self.control_port,
                                                   access_log=False, log_config=None, log_level="critical"))
        self.admin_thread = threading.Thread(target=self.server.run, daemon=True, name="bridge-local-control")
        self.admin_thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.admin_thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("本地控制服务启动失败")
            time.sleep(0.05)
        write_json(self.root / "running.json", {"url": self.control_url, "pid": os.getpid(), "instance": self.instance})

    def close(self):
        self.runtime.close()
        if self.server:
            self.server.should_exit = True
        if self.admin_thread:
            self.admin_thread.join(20)
        self.self_client.close()
        with self.lock:
            for entry in self.joins.values():
                entry["client"].close()
            self.joins.clear()
        state = read_json(self.root / "running.json", {})
        if state.get("instance") == self.instance:
            (self.root / "running.json").unlink(missing_ok=True)
            if self.vault.get("control") == self.control_token:
                self.vault.delete("control")
