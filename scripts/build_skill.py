"""Build a deterministic skill archive from an explicit, reviewed file list."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "agent-bridge"
PACKAGE = ROOT / "src" / "codex_bridge"


def normalized(path):
    return path.read_bytes().replace(b"\r\n", b"\n")


def inputs():
    files = [PACKAGE / "__init__.py", PACKAGE / "config.py"]
    for directory in ("agent", "client", "models", "server", "storage"):
        files.extend(sorted((PACKAGE / directory).glob("*.py")))
    for name in ("__init__.py", "files.py", "export.py", "connection.py"):
        files.append(PACKAGE / "services" / name)
    return {Path("runtime/codex_bridge") / path.relative_to(PACKAGE): normalized(path) for path in files}


def package_files():
    files = inputs()
    files[Path("requirements.txt")] = (
        "fastapi>=0.115,<1\nuvicorn>=0.30,<1\nhttpx>=0.28,<1\npydantic>=2.10,<3\n"
        "platformdirs>=4,<5\nkeyring>=25,<26\n"
    ).encode()
    files[Path("LICENSE")] = normalized(ROOT / "LICENSE")
    files[Path("scripts/install.py")] = normalized(ROOT / "scripts/install_skill_local.py")
    for name in ("SKILL.md", "agents/openai.yaml", "references/commands.md",
                 "scripts/bootstrap.py", "scripts/bridge.py"):
        files[Path(name)] = normalized(SKILL / name)
    return files


def manifest_bytes(files):
    manifest = {path.as_posix(): hashlib.sha256(content).hexdigest()
                for path, content in sorted(files.items())}
    return (json.dumps(manifest, indent=2) + "\n").encode()


def archive_bytes(path, files):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build(output, check=False):
    files = package_files()
    manifest = manifest_bytes(files)
    if check:
        mismatched = [path.as_posix() for path, content in files.items()
                      if not (SKILL / path).is_file() or (SKILL / path).read_bytes() != content]
        manifest_path = SKILL / "runtime-manifest.json"
        if not manifest_path.is_file() or manifest_path.read_bytes() != manifest:
            mismatched.append("runtime-manifest.json")
        if mismatched:
            raise ValueError("Skill package is stale: " + ", ".join(mismatched))
        return {"status": "verified", "files": len(files) + 1}
    for path, content in files.items():
        destination = SKILL / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file() or destination.read_bytes() != content:
            destination.write_bytes(content)
    expected = {SKILL / path for path in files}
    for old in (SKILL / "runtime").rglob("*.py"):
        if old not in expected:
            old.unlink()
    (SKILL / "runtime-manifest.json").write_bytes(manifest)
    packed = {"agent-bridge/" + path.as_posix(): content for path, content in files.items()}
    packed["agent-bridge/runtime-manifest.json"] = manifest
    output.mkdir(parents=True, exist_ok=True)
    skill_zip = output / "agent-bridge-skill.zip"
    mac_zip = output / "agent-bridge-mac-skill.zip"
    archive_bytes(skill_zip, packed)
    archive_bytes(mac_zip, packed | {"MAC_INSTALL.md": normalized(ROOT / "docs/MAC_SKILL_INSTALL.md")})
    checksums = {path.name: {"size_bytes": path.stat().st_size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                 for path in (skill_zip, mac_zip)}
    (output / "skill-checksums.json").write_text(json.dumps(checksums, indent=2) + "\n", encoding="utf-8")
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{value['sha256']}  {name}\n" for name, value in checksums.items()), encoding="utf-8")
    return {"status": "built", "files": len(files) + 1, "artifacts": checksums}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts")
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.check), indent=2))


if __name__ == "__main__":
    main()
