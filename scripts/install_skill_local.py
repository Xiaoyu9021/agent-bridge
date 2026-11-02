"""Install the reviewed self-contained skill into a local Codex skill directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", type=Path, help="Exact destination folder; defaults to CODEX_HOME/skills/agent-bridge")
    parser.add_argument("--upgrade", action="store_true", help="Upgrade only if installed files still match their previous manifest")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    if not (source / "SKILL.md").is_file():
        source = source / "skills" / "agent-bridge"
    codex_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    destination = (args.dest or codex_root / "skills" / "agent-bridge").expanduser().resolve()
    manifest = json.loads((source / "runtime-manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest.items():
        relative = PurePosixPath(name)
        path = source / name
        if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                or "\\" in name or ":" in name or not path.resolve().is_relative_to(source.resolve())):
            raise ValueError("Unsafe package path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Package checksum mismatch; rebuild before installation")
    if destination.exists():
        previous = destination / "runtime-manifest.json"
        matches = previous.is_file() and json.loads(previous.read_text(encoding="utf-8")) == manifest
        if matches and all((destination / name).is_file() and
                           hashlib.sha256((destination / name).read_bytes()).hexdigest() == expected
                           for name, expected in manifest.items()):
            print(json.dumps({"status": "already_installed", "skill": str(destination)}))
            return
        if not args.upgrade or not previous.is_file():
            raise SystemExit("An existing skill differs; review it before explicitly upgrading with --upgrade")
        old_manifest = json.loads(previous.read_text(encoding="utf-8"))
        for name, expected in old_manifest.items():
            old = destination / name
            if not old.resolve().is_relative_to(destination) or not old.is_file() or old.is_symlink():
                raise SystemExit("Installed skill layout changed; refusing automatic upgrade")
            if hashlib.sha256(old.read_bytes()).hexdigest() != expected:
                raise SystemExit("Installed skill has user modifications; refusing automatic upgrade")
        # Only reviewed package files are updated; preserve the private environment and extra user files.
        for name in [*manifest, "runtime-manifest.json"]:
            target = destination / name
            if not target.resolve().is_relative_to(destination) or target.is_symlink():
                raise SystemExit("Unsafe installation path")
            if name != "runtime-manifest.json" and name not in old_manifest and target.exists():
                raise SystemExit("A user file conflicts with a new package path; refusing automatic upgrade")
        for name in [*manifest, "runtime-manifest.json"]:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                staged = Path(handle.name)
                handle.write((source / name).read_bytes())
            os.replace(staged, target)
        print(json.dumps({"status": "upgraded", "skill": str(destination)}))
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".agent-bridge-install-", dir=destination.parent)).resolve()
    try:
        for name in [*manifest, "runtime-manifest.json"]:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        staging.rename(destination)
    except BaseException:
        # This is a fresh temporary directory created immediately above under the named destination parent.
        if staging.exists() and staging.parent == destination.parent:
            shutil.rmtree(staging)
        raise
    print(json.dumps({"status": "installed", "skill": str(destination), "entry": str(destination / "scripts/bridge.py")}))


if __name__ == "__main__":
    main()
