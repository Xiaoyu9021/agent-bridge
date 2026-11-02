import importlib.util
import json
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_is_reproducible_and_excludes_unlisted_data(tmp_path, monkeypatch):
    builder = load_script("build_skill")
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / ".env").write_text("PRIVATE_FIXTURE=value", encoding="utf-8")
    (skill / "running.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(builder, "SKILL", skill)
    monkeypatch.setattr(builder, "package_files", lambda: {Path("SKILL.md"): b"Reviewed skill\n"})
    first = builder.build(tmp_path / "first")
    second = builder.build(tmp_path / "second")
    assert first["artifacts"] == second["artifacts"]
    with zipfile.ZipFile(tmp_path / "first/agent-bridge-skill.zip") as archive:
        assert archive.namelist() == ["agent-bridge/SKILL.md", "agent-bridge/runtime-manifest.json"]
    assert (skill / ".env").read_text(encoding="utf-8") == "PRIVATE_FIXTURE=value"


def test_check_detects_stale_manifest_even_when_runtime_matches(tmp_path, monkeypatch):
    builder = load_script("build_skill")
    skill = tmp_path / "skill"
    skill.mkdir()
    monkeypatch.setattr(builder, "SKILL", skill)
    monkeypatch.setattr(builder, "package_files", lambda: {Path("SKILL.md"): b"Reviewed skill\n"})
    builder.build(tmp_path / "dist")
    (skill / "runtime-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="runtime-manifest"):
        builder.build(tmp_path / "dist", check=True)


def test_manifest_order_is_identical_for_windows_and_posix_paths():
    builder = load_script("build_skill")
    files = {"SKILL.md": b"skill", "agents/openai.yaml": b"metadata", "LICENSE": b"license"}
    windows = {PureWindowsPath(name): content for name, content in files.items()}
    posix = {PurePosixPath(name): content for name, content in files.items()}
    assert builder.manifest_bytes(windows) == builder.manifest_bytes(posix)


def test_publish_check_rejects_runtime_data_secrets_and_changed_staged_blob():
    inspector = load_script("check_publish_tree")
    files = {
        "skills/agent-bridge/.runtime/token.txt": b"fixture",
        "docs/demo.env": b"not recognized by suffix alone",
        "notes/private.key": b"-----BEGIN PRIVATE KEY-----\nfixture\n",
        "src/settings.py": b'authorization="Bearer ' + b"x" * 40 + b'"',
        "skills/agent-bridge/runtime-manifest.json": json.dumps({"SKILL.md": "0" * 64}).encode(),
        "skills/agent-bridge/SKILL.md": b"changed",
    }
    issues = inspector.inspect(files)
    reasons = {item["reason"] for item in issues}
    assert reasons == {"private_runtime_or_credential_file", "possible_embedded_secret", "staged_manifest_mismatch"}
