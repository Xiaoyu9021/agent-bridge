from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from codex_bridge.config import Settings
from codex_bridge.models import TRANSITIONS, DeviceInput, ResultInput, TaskInput, utc_now


class BridgeError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_dir.resolve()
        self.files = self.root / "attachments"
        self.files.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "bridge.db"
        self.lock = threading.RLock()
        with self.transaction() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] > 1:
                raise BridgeError("newer_schema", "数据库版本高于当前程序，请使用更新版本", 409)
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS devices(
                    id TEXT PRIMARY KEY, display_name TEXT NOT NULL, platform TEXT NOT NULL,
                    role TEXT NOT NULL, token_hash TEXT UNIQUE, paired_at TEXT NOT NULL,
                    last_seen TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS tasks(
                    id TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    published INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS task_sender ON tasks(sender);
                CREATE INDEX IF NOT EXISTS task_recipient ON tasks(recipient);
                CREATE TABLE IF NOT EXISTS results(
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), sender TEXT NOT NULL,
                    payload TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attachments(
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    result_id TEXT REFERENCES results(id), uploader TEXT NOT NULL,
                    payload TEXT NOT NULL, size INTEGER NOT NULL, complete INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS attachment_task ON attachments(task_id);
                CREATE TABLE IF NOT EXISTS events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id),
                    actor TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
                );
                PRAGMA user_version=1;
            """)
        # Interrupted uploads are never exposed. One Host process per data directory is required.
        for path in self.files.glob("*.part"):
            path.unlink(missing_ok=True)

    @contextmanager
    def transaction(self):
        with self.lock:
            db = sqlite3.connect(self.db_path, timeout=15)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def register(self, device: DeviceInput, role: str = "client") -> str:
        token = secrets.token_urlsafe(48)
        now = utc_now()
        with self.transaction() as db:
            existing = db.execute("SELECT role FROM devices WHERE id=?", (device.id,)).fetchone()
            if existing and existing["role"] == "host" and role != "host":
                raise BridgeError("device_conflict", "设备 ID 已被主机使用", 409)
            db.execute("""INSERT INTO devices VALUES(?,?,?,?,?,?,?,0)
                ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,
                platform=excluded.platform, token_hash=excluded.token_hash,
                paired_at=excluded.paired_at,last_seen=excluded.last_seen,revoked=0""",
                       (device.id, device.display_name, device.platform, role, digest(token), now, now))
        return token

    def authenticate(self, token: str) -> dict:
        with self.transaction() as db:
            device = db.execute("SELECT * FROM devices WHERE token_hash=? AND revoked=0",
                                (digest(token),)).fetchone()
            if not device:
                raise BridgeError("unauthorized", "设备未授权或授权已撤销，请重新配对", 401)
            db.execute("UPDATE devices SET last_seen=? WHERE id=?", (utc_now(), device["id"]))
            return {key: device[key] for key in device.keys() if key != "token_hash"}

    def devices(self) -> list[dict]:
        with self.transaction() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,display_name,platform,role,paired_at,last_seen FROM devices WHERE revoked=0"
            )]

    def revoke(self, device_id: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE devices SET revoked=1,token_hash=NULL WHERE id=? AND role!='host'", (device_id,))

    def rename(self, device_id: str, name: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE devices SET display_name=? WHERE id=?", (name, device_id))

    def _task(self, db, task_id: str, actor: str):
        row = db.execute("SELECT * FROM tasks WHERE id=? AND (sender=? OR recipient=?)",
                         (task_id, actor, actor)).fetchone()
        if not row or (not row["published"] and row["sender"] != actor):
            raise BridgeError("not_found", "任务不存在或无权访问", 404)
        return row

    def _declare(self, db, attachments, task_id: str, actor: str, result_id: str | None = None):
        total = db.execute("SELECT COALESCE(SUM(size),0) FROM attachments WHERE task_id=?",
                           (task_id,)).fetchone()[0]
        for item in attachments:
            if item.size_bytes > self.settings.max_file_bytes:
                raise BridgeError("file_too_large", "单文件超过配置上限", 413)
            total += item.size_bytes
            if total > self.settings.max_task_bytes:
                raise BridgeError("task_too_large", "任务输入与结果附件总量超过配置上限", 413)
            try:
                db.execute("INSERT INTO attachments VALUES(?,?,?,?,?,?,0)",
                           (item.id, task_id, result_id, actor, encode(item.model_dump()), item.size_bytes))
            except sqlite3.IntegrityError:
                raise BridgeError("id_conflict", "附件 ID 已被使用", 409) from None

    def create_task(self, actor: str, model: TaskInput) -> dict:
        payload = encode(model.model_dump())
        with self.transaction() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (model.id,)).fetchone()
            if row:
                if row["sender"] != actor or row["payload"] != payload:
                    raise BridgeError("id_conflict", "任务 ID 与已有内容冲突", 409)
            else:
                target = db.execute("SELECT id FROM devices WHERE id=? AND revoked=0",
                                    (model.recipient_device_id,)).fetchone()
                if not target or model.recipient_device_id == actor:
                    raise BridgeError("bad_recipient", "请选择另一个已配对的设备")
                now = utc_now()
                db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,0,?,?)",
                           (model.id, actor, model.recipient_device_id, payload, "pending", now, now))
                self._declare(db, model.attachments, model.id, actor)
        return self.get_task(actor, model.id)

    def _serialize(self, db, row, actor: str) -> dict:
        task = json.loads(row["payload"])
        task.update(schema_version="0.1", sender_device_id=row["sender"],
                    status=row["status"] if row["published"] else "draft",
                    created_at=row["created_at"], updated_at=row["updated_at"])
        files = []
        for file in db.execute("SELECT * FROM attachments WHERE task_id=?", (row["id"],)):
            item = json.loads(file["payload"])
            item.update(task_id=row["id"], result_id=file["result_id"],
                        kind="result" if file["result_id"] else "input", complete=bool(file["complete"]))
            files.append(item)
        task["attachments"] = [item for item in files if item["kind"] == "input"]
        task["results"] = []
        for result in db.execute("SELECT * FROM results WHERE task_id=? ORDER BY created_at", (row["id"],)):
            if not result["published"] and result["sender"] != actor:
                continue
            item = json.loads(result["payload"])
            item.update(sender_device_id=result["sender"], created_at=result["created_at"],
                        published=bool(result["published"]),
                        artifacts=[f for f in files if f["result_id"] == result["id"]])
            task["results"].append(item)
        task["events"] = [dict(event) for event in db.execute(
            "SELECT actor,status,created_at FROM events WHERE task_id=? ORDER BY sequence", (row["id"],))]
        return task

    def get_task(self, actor: str, task_id: str) -> dict:
        with self.transaction() as db:
            return self._serialize(db, self._task(db, task_id, actor), actor)

    def list_tasks(self, actor: str, query: str = "", offset: int = 0, limit: int = 100) -> list[dict]:
        with self.transaction() as db:
            # Escape LIKE metacharacters so a literal title/ID search behaves consistently.
            term = "%" + query.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
            rows = db.execute("""SELECT * FROM tasks WHERE
                (sender=? OR (recipient=? AND published=1)) AND
                (id LIKE ? ESCAPE '!' OR json_extract(payload,'$.title') LIKE ? ESCAPE '!')
                ORDER BY updated_at DESC LIMIT ? OFFSET ?""", (actor, actor, term, term, limit, offset))
            return [self._serialize(db, row, actor) for row in rows]

    def _event(self, db, task_id: str, actor: str, status: str):
        now = utc_now()
        db.execute("UPDATE tasks SET status=?,updated_at=? WHERE id=?", (status, now, task_id))
        db.execute("INSERT INTO events(task_id,actor,status,created_at) VALUES(?,?,?,?)",
                   (task_id, actor, status, now))

    def publish_task(self, actor: str, task_id: str) -> dict:
        with self.transaction() as db:
            task = self._task(db, task_id, actor)
            if task["sender"] != actor:
                raise BridgeError("forbidden", "只有发送设备可以发布任务", 403)
            if not task["published"]:
                if db.execute("SELECT 1 FROM attachments WHERE task_id=? AND result_id IS NULL AND complete=0",
                              (task_id,)).fetchone():
                    raise BridgeError("incomplete", "附件尚未完整上传并校验", 409)
                db.execute("UPDATE tasks SET published=1 WHERE id=?", (task_id,))
                self._event(db, task_id, actor, "pending")
        return self.get_task(actor, task_id)

    def set_status(self, actor: str, task_id: str, status: str) -> dict:
        with self.transaction() as db:
            task = self._task(db, task_id, actor)
            if task["recipient"] != actor or not task["published"]:
                raise BridgeError("forbidden", "只有接收设备可以更新已发布任务的状态", 403)
            if task["status"] != status:
                if status not in TRANSITIONS[task["status"]]:
                    raise BridgeError("bad_transition", "状态顺序无效，请先接收任务并开始处理", 409)
                self._event(db, task_id, actor, status)
        return self.get_task(actor, task_id)

    def create_result(self, actor: str, task_id: str, model: ResultInput) -> dict:
        payload = encode(model.model_dump())
        with self.transaction() as db:
            task = self._task(db, task_id, actor)
            if task["recipient"] != actor:
                raise BridgeError("forbidden", "只有接收设备可以提交执行结果", 403)
            row = db.execute("SELECT * FROM results WHERE id=?", (model.id,)).fetchone()
            if row:
                if row["task_id"] != task_id or row["payload"] != payload or row["sender"] != actor:
                    raise BridgeError("id_conflict", "结果 ID 与已有内容冲突", 409)
            else:
                if task["status"] not in {"in_progress", "completed", "failed"}:
                    raise BridgeError("bad_transition", "请先将任务设为进行中", 409)
                db.execute("INSERT INTO results VALUES(?,?,?,?,0,?)", (model.id, task_id, actor, payload, utc_now()))
                self._declare(db, model.artifacts, task_id, actor, model.id)
        return {"id": model.id}

    def publish_result(self, actor: str, task_id: str, result_id: str) -> dict:
        with self.transaction() as db:
            task = self._task(db, task_id, actor)
            result = db.execute("SELECT * FROM results WHERE id=? AND task_id=? AND sender=?",
                                (result_id, task_id, actor)).fetchone()
            if not result:
                raise BridgeError("not_found", "结果不存在或无权操作", 404)
            if not result["published"]:
                if db.execute("SELECT 1 FROM attachments WHERE result_id=? AND complete=0", (result_id,)).fetchone():
                    raise BridgeError("incomplete", "结果附件尚未完整上传并校验", 409)
                outcome = json.loads(result["payload"])["outcome"]
                if task["status"] != outcome and outcome not in TRANSITIONS[task["status"]]:
                    raise BridgeError("bad_transition", "请先开始任务或重新开始失败任务", 409)
                db.execute("UPDATE results SET published=1 WHERE id=?", (result_id,))
                self._event(db, task_id, actor, outcome)
        return self.get_task(actor, task_id)

    def attachment(self, actor: str, file_id: str, upload: bool = False) -> dict:
        with self.transaction() as db:
            file = db.execute("SELECT * FROM attachments WHERE id=?", (file_id,)).fetchone()
            if not file:
                raise BridgeError("not_found", "附件不存在或无权访问", 404)
            self._task(db, file["task_id"], actor)
            if upload:
                if file["uploader"] != actor:
                    raise BridgeError("forbidden", "无权上传此附件", 403)
            elif not file["complete"]:
                raise BridgeError("incomplete", "附件尚未校验完成", 409)
            if file["result_id"]:
                result = db.execute("SELECT * FROM results WHERE id=?", (file["result_id"],)).fetchone()
                if not result["published"] and file["uploader"] != actor:
                    raise BridgeError("not_found", "附件不存在或无权访问", 404)
            return dict(file) | json.loads(file["payload"])

    def complete_attachment(self, file_id: str):
        with self.transaction() as db:
            db.execute("UPDATE attachments SET complete=1 WHERE id=?", (file_id,))

    def path_for(self, file_id: str) -> Path:
        # Only canonical UUIDs may ever reach a filesystem operation.
        from codex_bridge.models import validate_id
        validate_id(file_id)
        return self.files / f"{file_id}.bin"
