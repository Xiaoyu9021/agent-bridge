"""Build shareable local preview ZIPs from tracked source and the Windows onedir build."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from codex_bridge import __version__


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024**2):
            digest.update(block)
    return digest.hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    prefix = f"CodexBridge-{__version__}-preview"
    source_zip = artifacts / f"{prefix}-source.zip"
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")
    if not any(tracked):
        raise RuntimeError("Source package requires tracked/staged files")
    with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in tracked:
            if filename:
                archive.write(root / filename, f"{prefix}/{filename}")
    outputs = [source_zip]
    build = root / "dist" / "CodexBridge"
    if (build / "CodexBridge.exe").is_file():
        windows_zip = artifacts / f"{prefix}-windows-x64.zip"
        with zipfile.ZipFile(windows_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(build.rglob("*")):
                if path.is_file():
                    archive.write(path, "CodexBridge/" + path.relative_to(build).as_posix())
            archive.write(root / "README.md", "CodexBridge/README.md")
            for path in (root / "docs").rglob("*"):
                if path.is_file():
                    archive.write(path, "CodexBridge/docs/" + path.relative_to(root / "docs").as_posix())
        outputs.append(windows_zip)
    report = [{"filename": path.name, "size_bytes": path.stat().st_size, "sha256": sha256(path)} for path in outputs]
    (artifacts / "preview-checksums.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
