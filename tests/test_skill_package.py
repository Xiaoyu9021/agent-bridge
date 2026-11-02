import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_embedded_runtime_is_complete_and_matches_canonical_source():
    subprocess.run([sys.executable, "scripts/build_skill.py", "--check"], cwd=ROOT, check=True, capture_output=True)
    skill = ROOT / "skills/agent-bridge"
    manifest = json.loads((skill / "runtime-manifest.json").read_text(encoding="utf-8"))
    assert "runtime/codex_bridge/agent/cli.py" in manifest
    assert "SKILL.md" in manifest
    for name, expected in manifest.items():
        assert ".runtime" not in Path(name).parts
        assert hashlib.sha256((skill / name).read_bytes()).hexdigest() == expected
    requirements = (skill / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "pyside" not in requirements and "pyinstaller" not in requirements
    metadata = yaml.safe_load((skill / "agents/openai.yaml").read_text(encoding="utf-8"))
    assert "$agent-bridge" in metadata["interface"]["default_prompt"]


def test_local_installer_is_idempotent_and_protects_modified_skills(tmp_path):
    destination = tmp_path / "codex/skills/agent-bridge"
    command = [sys.executable, "scripts/install_skill_local.py", "--dest", str(destination)]
    first = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8", check=True)
    assert json.loads(first.stdout)["status"] == "installed"
    second = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8", check=True)
    assert json.loads(second.stdout)["status"] == "already_installed"
    (destination / "SKILL.md").write_text("User customization", encoding="utf-8")
    protected = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8")
    assert protected.returncode != 0
    protected_upgrade = subprocess.run([*command, "--upgrade"], cwd=ROOT, capture_output=True, encoding="utf-8")
    assert protected_upgrade.returncode != 0
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "User customization"


def test_reviewed_upgrade_preserves_environment_and_extra_user_files(tmp_path):
    destination = tmp_path / "agent-bridge"
    command = [sys.executable, "scripts/install_skill_local.py", "--dest", str(destination)]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
    old_skill = destination / "SKILL.md"
    original = old_skill.read_bytes()
    old_skill.write_bytes(b"Previous reviewed release")
    manifest = json.loads((destination / "runtime-manifest.json").read_text(encoding="utf-8"))
    manifest["SKILL.md"] = hashlib.sha256(old_skill.read_bytes()).hexdigest()
    (destination / "runtime-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    environment = destination / ".runtime"
    environment.mkdir()
    (environment / "keep.txt").write_text("private environment", encoding="utf-8")
    subprocess.run([*command, "--upgrade"], cwd=ROOT, check=True, capture_output=True)
    assert old_skill.read_bytes() == original
    assert (environment / "keep.txt").read_text(encoding="utf-8") == "private environment"
