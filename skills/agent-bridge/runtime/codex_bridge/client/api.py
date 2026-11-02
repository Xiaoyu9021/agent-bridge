from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from codex_bridge.config import CHUNK_SIZE
from codex_bridge.models import Attachment, DeviceInput, ResultInput, TaskInput
from codex_bridge.storage.store import BridgeError


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in {"", "/"}):
        raise ValueError("请输入 http://私有IP:端口 或具有有效证书的 HTTPS 主机地址")
    return url.strip().rstrip("/")


class BridgeClient:
    def __init__(self, url: str, device: DeviceInput, token: str = "", cache_dir: Path | None = None):
        self.url = normalize_url(url)
        self.device = device
        self.token = token
        self.http = httpx.Client(base_url=self.url, timeout=httpx.Timeout(60, connect=5), trust_env=False,
                                 follow_redirects=False)
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
            with self._cache() as db:
                db.execute("CREATE TABLE IF NOT EXISTS snapshots(server TEXT PRIMARY KEY,body TEXT NOT NULL)")

    def _cache(self):
        return sqlite3.connect(self.cache_dir / "client-cache.db", timeout=10)

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @staticmethod
    def check(response: httpx.Response):
        if response.is_error:
            try:
                error = response.json()["error"]
                raise BridgeError(error["code"], error["message"], response.status_code)
            except (ValueError, KeyError, TypeError):
                raise BridgeError("http_error", f"主机返回错误 HTTP {response.status_code}", response.status_code) from None
        if response.is_redirect:
            raise BridgeError("redirect", "主机发生重定向，已停止请求以保护设备授权", 400)

    def request(self, method: str, path: str, **kwargs):
        response = self.http.request(method, "/api/v1" + path, headers=self.headers, **kwargs)
        self.check(response)
        return response.json()

    def pair_request(self, code: str) -> str:
        return self.request("POST", "/pair", json=self.device.model_dump() | {"code": code})["request_id"]

    def pair_poll(self, request_id: str) -> dict:
        result = self.request("POST", "/pair/status", json={"request_id": request_id})
        if result["status"] == "approved":
            self.token = result["token"]
        return result

    def snapshot(self) -> dict:
        devices = self.request("GET", "/devices")
        tasks = []
        while True:
            page = self.request("GET", "/tasks", params={"limit": 200, "offset": len(tasks)})
            tasks.extend(page)
            if len(page) < 200:
                break
        data = {"devices": devices, "tasks": tasks}
        if self.cache_dir:
            with self._cache() as db:
                db.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?)", (
                    self.url, json.dumps(data, ensure_ascii=False)))
        return data

    def cached_snapshot(self) -> dict:
        if self.cache_dir:
            with self._cache() as db:
                row = db.execute("SELECT body FROM snapshots WHERE server=?", (self.url,)).fetchone()
                if row:
                    return json.loads(row[0])
        return {"devices": [], "tasks": []}

    def upload(self, task_id: str, metadata: Attachment, path: Path, progress=None):
        def chunks():
            done = 0
            with path.open("rb") as handle:
                while chunk := handle.read(CHUNK_SIZE):
                    done += len(chunk)
                    if progress:
                        progress(f"上传 {path.name}", done, metadata.size_bytes)
                    yield chunk
        response = self.http.put(f"/api/v1/tasks/{task_id}/attachments/{metadata.id}/content", content=chunks(),
                                 headers=self.headers | {"Content-Type": "application/octet-stream"})
        self.check(response)

    def send_task(self, model: TaskInput, paths: list[Path], progress=None):
        if len(paths) != len(model.attachments):
            raise ValueError("附件路径与清单数量不一致")
        draft = self.request("POST", "/tasks", json=model.model_dump())
        complete = {item["id"] for item in draft["attachments"] if item["complete"]}
        for metadata, path in zip(model.attachments, paths):
            if metadata.id not in complete:
                self.upload(model.id, metadata, path, progress)
        return self.request("POST", f"/tasks/{model.id}/publish")

    def send_result(self, task_id: str, model: ResultInput, paths: list[Path], progress=None):
        if len(paths) != len(model.artifacts):
            raise ValueError("附件路径与清单数量不一致")
        self.request("POST", f"/tasks/{task_id}/results", json=model.model_dump())
        task = self.request("GET", f"/tasks/{task_id}")
        result = next(item for item in task["results"] if item["id"] == model.id)
        complete = {item["id"] for item in result["artifacts"] if item["complete"]}
        for metadata, path in zip(model.artifacts, paths):
            if metadata.id not in complete:
                self.upload(task_id, metadata, path, progress)
        return self.request("POST", f"/tasks/{task_id}/results/{model.id}/publish")

    def download(self, metadata: dict, directory: Path, progress=None) -> Path:
        # Validate again: an authenticated peer's metadata is still untrusted input.
        item = Attachment(**{key: metadata[key] for key in Attachment.model_fields})
        directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(directory).free < item.size_bytes + 16 * 1024**2:
            raise BridgeError("disk_full", "下载目录空间不足", 507)
        stem, suffix = Path(item.original_filename).stem, Path(item.original_filename).suffix
        target = directory / item.original_filename
        index = 1
        while True:
            try:
                with target.open("xb"):
                    pass
                break
            except FileExistsError:
                target = directory / f"{stem} ({index}){suffix}"
                index += 1
        temporary = None
        try:
            size = 0
            hasher = hashlib.sha256()
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".bridge-", suffix=".part", delete=False) as file:
                temporary = Path(file.name)
                with self.http.stream("GET", f"/api/v1/attachments/{item.id}/download", headers=self.headers) as res:
                    if not res.is_success:
                        res.read()
                    self.check(res)
                    for chunk in res.iter_bytes(CHUNK_SIZE):
                        size += len(chunk)
                        if size > item.size_bytes:
                            raise BridgeError("size_mismatch", "下载内容超过声明大小", 422)
                        file.write(chunk)
                        hasher.update(chunk)
                        if progress:
                            progress(f"下载 {item.original_filename}", size, item.size_bytes)
                file.flush()
                os.fsync(file.fileno())
            if size != item.size_bytes or hasher.hexdigest() != item.sha256:
                raise BridgeError("checksum_mismatch", "下载文件大小或 SHA-256 校验失败", 422)
            os.replace(temporary, target)
            return target
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def close(self):
        self.http.close()
