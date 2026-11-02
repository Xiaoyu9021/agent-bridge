from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from contextlib import asynccontextmanager
from weakref import WeakValueDictionary

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect

from codex_bridge import __version__
from codex_bridge.models import PairInput, ResultInput, StatusInput, TaskInput
from codex_bridge.server.control import HostControl
from codex_bridge.services.files import file_hash
from codex_bridge.storage.store import BridgeError


def create_app(control: HostControl) -> FastAPI:
    store = control.store
    locks = WeakValueDictionary()

    @asynccontextmanager
    async def lifespan(app):
        yield
        control.close_pairing()

    app = FastAPI(title="Codex Bridge", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.control = control

    @app.exception_handler(BridgeError)
    async def bridge_error(request, error):
        return JSONResponse({"error": {"code": error.code, "message": error.message}}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Do not echo request bodies or credentials from Pydantic validation errors.
        return JSONResponse({"error": {"code": "validation", "message": "输入字段或文件名格式无效"}}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({"error": {"code": "http_error", "message": str(error.detail)}},
                            status_code=error.status_code)

    @app.middleware("http")
    async def request_limits(request: Request, call_next):
        # Upload bodies are streamed; bound JSON/metadata requests before deserialization.
        if request.method in {"POST", "PATCH"} and not request.url.path.endswith("/content"):
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    return JSONResponse({"error": {"code": "body_too_large", "message": "请求正文过大"}}, 413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def auth(authorization: str = Header(default="")) -> dict:
        if not authorization.startswith("Bearer "):
            raise BridgeError("unauthorized", "需要设备授权", 401)
        return store.authenticate(authorization[7:])

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "schema_version": "0.1"}

    @app.get("/api/v1/openapi.json")
    def openapi(device=Depends(auth)):
        return app.openapi()

    @app.post("/api/v1/pair", status_code=202)
    def pair(model: PairInput):
        return {"request_id": control.request(model), "status": "pending"}

    @app.post("/api/v1/pair/status")
    def pair_status(body: dict):
        request_id = body.get("request_id")
        if not isinstance(request_id, str) or len(request_id) > 100:
            raise BridgeError("validation", "配对请求格式无效", 422)
        return control.poll(request_id)

    @app.get("/api/v1/devices")
    def devices(device=Depends(auth)):
        return store.devices()

    @app.get("/api/v1/settings")
    def settings(device=Depends(auth)):
        return {"max_file_bytes": store.settings.max_file_bytes, "max_task_bytes": store.settings.max_task_bytes}

    @app.post("/api/v1/tasks")
    def create_task(model: TaskInput, device=Depends(auth)):
        return store.create_task(device["id"], model)

    @app.get("/api/v1/tasks")
    def tasks(q: str = Query(default="", max_length=200), offset: int = Query(default=0, ge=0),
              limit: int = Query(default=100, ge=1, le=200), device=Depends(auth)):
        return store.list_tasks(device["id"], q, offset, limit)

    @app.get("/api/v1/tasks/{task_id}")
    def task(task_id: str, device=Depends(auth)):
        return store.get_task(device["id"], task_id)

    @app.post("/api/v1/tasks/{task_id}/publish")
    def publish(task_id: str, device=Depends(auth)):
        return store.publish_task(device["id"], task_id)

    @app.patch("/api/v1/tasks/{task_id}/status")
    def status(task_id: str, model: StatusInput, device=Depends(auth)):
        return store.set_status(device["id"], task_id, model.status.value)

    @app.post("/api/v1/tasks/{task_id}/results")
    def create_result(task_id: str, model: ResultInput, device=Depends(auth)):
        return store.create_result(device["id"], task_id, model)

    @app.get("/api/v1/tasks/{task_id}/results")
    def results(task_id: str, device=Depends(auth)):
        return store.get_task(device["id"], task_id)["results"]

    @app.post("/api/v1/tasks/{task_id}/results/{result_id}/publish")
    def publish_result(task_id: str, result_id: str, device=Depends(auth)):
        return store.publish_result(device["id"], task_id, result_id)

    @app.put("/api/v1/tasks/{task_id}/attachments/{file_id}/content")
    async def upload(task_id: str, file_id: str, request: Request, device=Depends(auth)):
        metadata = await asyncio.to_thread(store.attachment, device["id"], file_id, True)
        if metadata["task_id"] != task_id:
            raise BridgeError("not_found", "附件不属于此任务", 404)
        # Entries live only during a request; waiting concurrent retries share the same lock.
        lock = locks.setdefault(file_id, asyncio.Lock())
        async with lock:
            metadata = await asyncio.to_thread(store.attachment, device["id"], file_id, True)
            if metadata["complete"]:
                return {"id": file_id, "sha256": metadata["sha256"], "complete": True}
            final = store.path_for(file_id)
            partial = final.with_suffix(".part")
            size = 0
            hasher = hashlib.sha256()
            try:
                free = (await asyncio.to_thread(shutil.disk_usage, store.files)).free
                if free < metadata["size_bytes"] + store.settings.reserve_bytes:
                    raise BridgeError("disk_full", "Host 存储空间不足", 507)
                with partial.open("wb") as handle:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > metadata["size_bytes"] or size > store.settings.max_file_bytes:
                            raise BridgeError("size_mismatch", "上传文件超过声明大小", 413)
                        await asyncio.to_thread(handle.write, chunk)
                        hasher.update(chunk)
                    await asyncio.to_thread(handle.flush)
                    await asyncio.to_thread(os.fsync, handle.fileno())
                if size != metadata["size_bytes"] or hasher.hexdigest() != metadata["sha256"]:
                    raise BridgeError("checksum_mismatch", "文件大小或 SHA-256 校验失败，请重试", 422)
                disk_size, disk_sha = await asyncio.to_thread(file_hash, partial)
                if disk_size != size or disk_sha != metadata["sha256"]:
                    raise BridgeError("disk_checksum_mismatch", "落盘文件校验失败，请检查磁盘后重试", 422)
                # Revocation during a long transfer must take effect before publication.
                await asyncio.to_thread(store.authenticate, request.headers["authorization"][7:])
                await asyncio.to_thread(os.replace, partial, final)
                await asyncio.to_thread(store.complete_attachment, file_id)
                return {"id": file_id, "sha256": metadata["sha256"], "complete": True}
            except OSError as error:
                raise BridgeError("storage_error", "文件写入失败，请检查磁盘空间与权限", 507) from error
            except ClientDisconnect:
                raise BridgeError("disconnected", "上传连接已断开，请重新上传", 400) from None
            finally:
                partial.unlink(missing_ok=True)

    @app.get("/api/v1/attachments/{file_id}/download")
    def download(file_id: str, device=Depends(auth)):
        metadata = store.attachment(device["id"], file_id)
        path = store.path_for(file_id)
        if not path.is_file():
            raise BridgeError("missing_file", "附件文件丢失，请联系主机检查存储", 410)
        return FileResponse(path, media_type="application/octet-stream", filename=metadata["original_filename"],
                            headers={"X-SHA256": metadata["sha256"]})

    return app
