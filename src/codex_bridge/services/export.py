from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from codex_bridge.client.api import BridgeClient


def export_task(client: BridgeClient, task_id: str, directory: Path, progress=None) -> Path:
    task = client.request("GET", f"/tasks/{task_id}")
    if task["status"] == "draft":
        raise ValueError("任务尚未发布，不能导出")
    task["results"] = [result for result in task["results"] if result["published"]]
    directory.mkdir(parents=True, exist_ok=True)
    # A unique new folder prevents writing into existing projects or overwriting source files.
    staging = Path(tempfile.mkdtemp(prefix=".bridge-export-", dir=directory))
    target = directory / f"Task_{task_id}"
    if target.exists():
        target = directory / f"Task_{task_id}_{staging.name[-8:]}"
    try:
        (staging / "attachments").mkdir()
        (staging / "results").mkdir()
        mappings = []
        for attachment in task["attachments"]:
            output = client.download(attachment, staging / "attachments", progress)
            mappings.append({"attachment_id": attachment["id"],
                             "original_filename": attachment["original_filename"],
                             "relative_path": output.relative_to(staging).as_posix(),
                             "sha256": attachment["sha256"], "size_bytes": attachment["size_bytes"]})
        for result in task["results"]:
            if not result["published"]:
                continue
            folder = staging / "results" / result["id"]
            folder.mkdir()
            (folder / "REPORT.md").write_text(result["summary_md"], encoding="utf-8")
            # Separate artifacts from generated report names to avoid collisions.
            for artifact in result["artifacts"]:
                output = client.download(artifact, folder / "artifacts", progress)
                mappings.append({"attachment_id": artifact["id"], "original_filename": artifact["original_filename"],
                                 "relative_path": output.relative_to(staging).as_posix(),
                                 "sha256": artifact["sha256"], "size_bytes": artifact["size_bytes"]})
        task["export_files"] = mappings
        (staging / "manifest.json").write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        inputs = "\n".join(f"- `{item['relative_path']}` (SHA-256: {item['sha256']})"
                           for item in mappings if item["relative_path"].startswith("attachments/"))
        text = (f"# {task['title']}\n\n- Task ID: {task_id}\n"
                f"- 来源设备: {task['sender_device_id']}\n- 目标设备: {task['recipient_device_id']}\n\n"
                f"## 任务目标\n\n{task['description_md']}\n\n## 输入附件\n\n{inputs}\n\n"
                "## 交付建议\n\n请将代码变更说明、execution-report.md、截图、测试结果和未解决问题保存到 results/。\n"
                "在本机编程工具中手动引用本 TASK.md 和附件；导出操作不会自动启动 Agent。\n")
        (staging / "TASK.md").write_text(text, encoding="utf-8")
        staging.rename(target)
        return target
    except BaseException:
        shutil.rmtree(staging)
        raise
