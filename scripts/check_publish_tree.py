"""Check staged Git content for common private artifacts and manifest inconsistencies."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import PurePosixPath

FORBIDDEN_PARTS = {".venv", ".runtime", "__pycache__", ".local", "artifacts", "dist", "build"}
FORBIDDEN_SUFFIXES = {".db", ".db-shm", ".db-wal", ".sqlite", ".sqlite3", ".part", ".log", ".pem", ".pfx", ".p12", ".env", ".key"}
SECRET_PATTERNS = [
    re.compile(rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s*$"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"Bearer [A-Za-z0-9_-]{32,}"),
]


def inspect(files):
    issues = []
    for name, content in files.items():
        path = PurePosixPath(name)
        if (set(path.parts) & FORBIDDEN_PARTS or path.suffix.lower() in FORBIDDEN_SUFFIXES
                or path.name == ".env" or path.name.startswith(".env.")
                or path.name in {"agent.json", "running.json", "peers.json", "id_rsa", "id_ed25519"}):
            issues.append({"file": name, "reason": "private_runtime_or_credential_file"})
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            issues.append({"file": name, "reason": "possible_embedded_secret"})
    prefix = "skills/agent-bridge/"
    if prefix + "runtime-manifest.json" in files:
        manifest = json.loads(files[prefix + "runtime-manifest.json"])
        for name, expected in manifest.items():
            content = files.get(prefix + name)
            if content is None or hashlib.sha256(content).hexdigest() != expected:
                issues.append({"file": prefix + name, "reason": "staged_manifest_mismatch"})
    return issues


def main():
    names = subprocess.check_output(["git", "ls-files", "-z"]).decode("utf-8").strip("\0").split("\0")
    files = {name: subprocess.check_output(["git", "cat-file", "blob", ":" + name]) for name in names if name}
    issues = inspect(files)
    print(json.dumps({"staged_files": len(files), "issues": issues, "passed": not issues}, indent=2))
    raise SystemExit(1 if issues else 0)


if __name__ == "__main__":
    main()
