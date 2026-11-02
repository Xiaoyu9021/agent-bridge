# Mac V0.1 验证报告

2026-11-02，macOS 26.6.2 (25G83)，arm64，Python 3.13.18。系统 Python 3.9.6 未改动；独立 Python 位于工作区 ../.python。原项目未修改，验证在本目录副本执行，基线 /tmp/CodexBridge-macos-baseline。

## 实际执行结果

- uv python install 3.13：成功；安装独立 Python 3.13.18。
- 新 Python -m venv .venv；.venv/bin/python -m pip install -e '.[dev]'：成功。
- .venv/bin/python -m pip check：通过。
- .venv/bin/python -m ruff check .：通过。
- QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --junitxml=artifacts/tests-macos.xml：42 passed，1 项上游 Starlette/httpx 弃用警告，6.73 秒。
- .venv/bin/python -m codex_bridge --self-check artifacts/macos-source-smoke.json：通过，原生 Qt 窗口组件、266 字体族、真实 HTTP 配对和中文任务。
- .venv/bin/python scripts/verify_large_transfer.py：通过，512 MiB，SHA-256 一致；上传 0.913 秒、下载 0.925 秒；Host RSS 增长 2.62 MiB，Client+Qt 5.83 MiB；41 次心跳，最大间隔 0.056 秒。仅 127.0.0.1，非跨机。
- sh scripts/build_macos.sh：成功。
- dist/CodexBridge.app/Contents/MacOS/CodexBridge --self-check artifacts/macos-packaged-smoke.json：通过。
- open -n dist/CodexBridge.app --args --data-dir /tmp/bridge-mac-packaged：成功；原生中文主界面、设置页面和系统目录选择器已实际操作。
- Keychain：keyring.backends.macOS，临时随机值写入、读取比对、删除通过；未输出秘密。明文回退拒绝由测试覆盖。

## 限制和剩余项

自动化真实 HTTP 用例覆盖三中文附件、导出、状态、报告回传下载、重启历史、断线重试。不能将这些等同于两个原生 GUI 实例的完整人工闭环；该完整操作链尚未完成。原生控制首次调用耗时异常约 29 分钟，后续设置和目录选择操作正常。窗口可见并不代表全部 GUI 验收通过。

未使用开发者证书或 notarization；PyInstaller 本地临时签名不构成开发者签名。未改 Gatekeeper。Windows ↔ Mac 双机联调未执行，等待两端准备。Windows 42 项历史记录未覆盖。

原始 Python 过低问题已自行解决，无已证实需修改的业务源码故障。Qt 缺少 Windows 字体的提示未造成测试失败。未扩展 Agent 自动化。

## 依赖版本

- PySide6 6.12.0
- fastapi 0.162.0
- uvicorn 0.54.0
- httpx 0.28.1
- pydantic 2.14.2
- keyring 25.7.0
- pytest 9.2.0
- ruff 0.17.3
- pyinstaller 6.22.3