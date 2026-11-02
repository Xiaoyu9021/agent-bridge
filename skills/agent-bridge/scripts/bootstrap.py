"""Install this skill's headless dependencies into its own virtual environment."""
import json
import os
import subprocess
import sys
import venv
from pathlib import Path


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    runtime = root / ".runtime"
    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if sys.version_info < (3, 11):
        print(json.dumps({"ok": False, "error": "需要 Python 3.11+；请由 Agent 查找或安装用户级 Python，再运行本脚本"}, ensure_ascii=False))
        return 1
    runtime.mkdir(exist_ok=True)
    lock = runtime / "bootstrap.lock"
    try:
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        print(json.dumps({"ok": False, "error": "安装正在进行；若之前异常中断，确认旧安装进程结束后移除 .runtime/bootstrap.lock 再试"}, ensure_ascii=False))
        return 1
    try:
        venv.EnvBuilder(with_pip=True).create(runtime)
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        with (runtime / "install.log").open("w", encoding="utf-8") as log:
            for command in ([str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")],
                            [str(python), "-m", "pip", "check"]):
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, **flags)
                if result.returncode:
                    print(json.dumps({"ok": False, "error": "依赖安装失败，请检查 .runtime/install.log", "log": str(runtime / "install.log")}, ensure_ascii=False))
                    return 1
        print(json.dumps({"ok": True, "python": str(python), "entry": str(root / "scripts/bridge.py"),
                          "message": "技能运行环境已安装，无需桌面程序或 Qt；接下来运行 setup"}, ensure_ascii=False, indent=2))
        return 0
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
