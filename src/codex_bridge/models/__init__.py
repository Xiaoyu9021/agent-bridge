from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def new_id() -> str:
    return str(uuid4())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Status(str, Enum):
    pending = "pending"
    accepted = "accepted"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


STATUS_NAMES = {
    "draft": "发送草稿", "pending": "待接收", "accepted": "已接收",
    "in_progress": "进行中", "completed": "已完成", "failed": "已失败",
}
TRANSITIONS = {
    "pending": {"accepted"}, "accepted": {"in_progress"},
    "in_progress": {"completed", "failed"}, "failed": {"in_progress"}, "completed": set(),
}


def validate_id(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("ID 必须是规范的 UUID")
    return value


class DeviceInput(Model):
    id: str = Field(default_factory=new_id)
    display_name: str = Field(min_length=1, max_length=100)
    platform: str = Field(max_length=30)
    _id = field_validator("id")(validate_id)


class Attachment(Model):
    id: str = Field(default_factory=new_id)
    original_filename: str = Field(min_length=1, max_length=240)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: str = Field(default="application/octet-stream", max_length=150)
    _id = field_validator("id")(validate_id)

    @field_validator("original_filename")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if (value in {".", ".."} or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', value)
                or value.endswith((".", " "))
                or value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
                                                                  *(f"LPT{i}" for i in range(10))}):
            raise ValueError("附件文件名包含不安全字符或系统保留名称")
        return value


class TaskInput(Model):
    id: str = Field(default_factory=new_id)
    title: str = Field(min_length=1, max_length=200)
    project: str = Field(default="", max_length=100)
    description_md: str = Field(max_length=262144)
    recipient_device_id: str
    source_agent: str = Field(default="codex", max_length=100)
    target_agent: str = Field(default="codex", max_length=100)
    attachments: list[Attachment] = Field(default_factory=list, max_length=100)
    _ids = field_validator("id", "recipient_device_id")(validate_id)

    @field_validator("attachments")
    @classmethod
    def unique_attachments(cls, value: list[Attachment]) -> list[Attachment]:
        if len({item.id for item in value}) != len(value):
            raise ValueError("附件 ID 重复")
        return value


class ResultInput(Model):
    id: str = Field(default_factory=new_id)
    summary_md: str = Field(min_length=1, max_length=262144)
    outcome: str = Field(pattern="^(completed|failed)$")
    artifacts: list[Attachment] = Field(default_factory=list, max_length=100)
    _id = field_validator("id")(validate_id)
    _unique = field_validator("artifacts")(TaskInput.unique_attachments.__func__)


class PairInput(DeviceInput):
    code: str = Field(pattern=r"^[0-9]{8}$")


class StatusInput(Model):
    status: Status
