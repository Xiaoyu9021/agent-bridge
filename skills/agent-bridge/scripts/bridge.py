"""Agent Bridge entry point for an installed, self-contained skill folder."""
import json
import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
root = Path(__file__).resolve().parents[1]
environment = root / ".runtime"
python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.is_file():
    print(json.dumps({"ok": False, "error": "请先用 Python 3.11+ 运行 scripts/bootstrap.py"}, ensure_ascii=False))
    raise SystemExit(1)
if Path(sys.prefix).resolve() != environment.resolve():
    raise SystemExit(subprocess.call([str(python), str(Path(__file__).resolve()), *sys.argv[1:]]))
sys.path.insert(0, str(root / "runtime"))

from codex_bridge.agent.cli import main  # noqa: E402 -- runtime path must be selected first

main()
