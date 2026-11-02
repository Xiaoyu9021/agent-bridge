from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from codex_bridge.config import CHUNK_SIZE
from codex_bridge.models import Attachment


def file_hash(path: Path, progress=None) -> tuple[int, str]:
    hasher = hashlib.sha256()
    total = path.stat().st_size
    done = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            hasher.update(chunk)
            done += len(chunk)
            if progress:
                progress(f"校验 {path.name}", done, total)
    return done, hasher.hexdigest()


def describe_file(path: Path, progress=None) -> Attachment:
    size, sha = file_hash(path, progress)
    return Attachment(original_filename=path.name, size_bytes=size, sha256=sha,
                      mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return str(size)
