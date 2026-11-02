# Codex Bridge

**把开发任务、工程附件和执行结果，可靠地交给另一台电脑。**

Windows ↔ macOS 的任务交接桌面工具。适用于 Windows Codex 开发 Android、Mac Codex 使用另一账号开发 iOS 的工作流：需求和 ZIP 发出 → 接收与导出 → 手动开发 → 报告与截图回传。也可以供其他本地编程工具人工读取。

**状态：V0.1.1 本地开发预览，已简化首次连接。** Windows 已验证新版；Mac 回传了 V0.1.0 的 42 项测试、大文件、Keychain 和 `.app` 自检证据，新版界面待 Mac 复核。真实跨设备联调尚未完成，尚未发布 GitHub Release。Codex Bridge 为工作名，不是 OpenAI 官方产品。

![真实 Qt 界面，使用隔离的示例任务](docs/assets/desktop-demo.png)

## 已实现

- Host / Client 两种角色；一次性配对码 + Host 本地确认，设备授权可撤销。
- 双向发送中文 Markdown 任务和任意常规文件；UUID 幂等重试。
- 流式上传下载、进度、大小上限、SHA-256 和落盘复核；断线不显示虚假成功。
- 已接收 / 进行中 / 已完成 / 已失败状态；同任务多条执行结果和产物。
- SQLite 历史、标题/ID 搜索、离线缓存和自动重连。
- 导出新的任务目录：`TASK.md`、`manifest.json`、`attachments/`、`results/`，同名附件保留映射。
- 中文 Qt 桌面界面，网络与文件计算在后台执行。

V0.1 不调用或操控 Codex，不共享账号，不读取聊天历史，不自动执行/解压附件，不提供 Git 同步或 Agent 调度。Agent 自动化属于未来版本。

## 快速启动

需要 Python 3.11+。本机验证环境为 Windows 11 / Python 3.13.2。

Windows PowerShell（项目根目录）：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m codex_bridge
```

macOS Terminal（以下命令待真实 Mac 验证）：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m codex_bridge
```

Windows 选“创建连接”→“开始使用”，再点击“连接另一台电脑”→“复制连接信息”。Mac 选“加入连接”，粘贴这段信息并点击连接；回到 Windows 核对设备名称并确认即可。网络地址、端口、设备名和保存目录会自动设置，无需逐项填写。设置记住后，再次启动直接进入任务页。

程序只枚举本机网络接口，优先选择正在使用的私有 Wi-Fi / 有线网络，不扫描网络、不开放公网或通配地址。多网卡选错、跨网络或需要本机测试时，可展开“高级设置”手动指定地址；当前不会自动发现远端电脑。

已构建的 Windows 预览版位于 `dist/CodexBridge/CodexBridge.exe`，需保留整个 CodexBridge 目录。构建产物不提交 Git，不代表已经线上发布。

本地交付包位于 `artifacts/CodexBridge-0.1.1-preview-windows-x64.zip` 和 `artifacts/CodexBridge-0.1.1-preview-source.zip`；分别供 Windows 体验和 Mac 源码验证。校验值在同目录 preview-checksums.json。可运行 `python scripts/package_preview.py` 重新生成，源码包仅纳入 Git 已跟踪/暂存文件。

## 体验一个完整闭环

1. Windows 新建任务，选择 Mac，添加 `requirements.md`、`project.zip` 和截图后发送。
2. Mac 选择收到的任务，点击“接收任务”，再点“保存任务给 Codex”。
3. 在 Mac Codex 中手动引用导出目录的 `TASK.md`，在 Bridge 中点击“开始处理”。
4. 完成开发后，Mac 在原任务点击“回传结果”，添加总结和 `execution-report.md`、截图或代码包，选择已完成或已失败。
5. Windows 在原任务查看结果并下载附件。每次完整上传下载均核验 SHA-256。

没有第二台设备也可用两个数据目录运行两个实例，配对到 `http://127.0.0.1:47821`。详细步骤见 [Windows 手册](docs/USER_GUIDE_WINDOWS.md)、[macOS 手册](docs/USER_GUIDE_MACOS.md)。

## 验证与构建

```sh
python -m ruff check .
python -m pytest -q
python scripts/verify_large_transfer.py
python -m codex_bridge --self-check artifacts/source-smoke.json
```

大文件脚本实际生成并传输 512 MiB 文件，采样独立 Host 进程和 Qt 客户端内存，检测界面心跳；测试文件会清理。应预留约 2 GiB 空间。完整证据及 14 项验收映射见 [测试报告](docs/TEST_REPORT.md)。CI 文件已配置 Windows/macOS/Linux × Python 3.11/3.13，**尚未在线运行**。

Windows / Python 3.13 的已验证依赖快照在 `requirements/windows-py313.lock`。需要复现相同依赖时，先安装该文件，再执行 `python -m pip install -e . --no-deps`。该快照包含 Windows 组件，其他平台按 pyproject.toml 安装并单独验证。

Windows 执行 `./scripts/build_windows.ps1`；Mac 本机执行 `sh scripts/build_macos.sh`。Mac 构建未实测、未签名、未 notarize；Windows 构建也未签名。

## 架构

单代码库：PySide6 界面 → httpx → FastAPI / Uvicorn → SQLite 与 UUID 附件存储。任务和结果采用草稿—上传—发布流程，全部文件校验后才对接收者可见。

| 目录 | 内容 |
|---|---|
| src/codex_bridge | models、storage、server、client、services、ui |
| tests | 协议、安全、真实 HTTP、失败恢复和 Qt 后台操作测试 |
| scripts | 构建、512 MiB 联调和隔离示例截图 |
| docs | 设计、协议、安全、手册、测试证据和开发计划 |
| examples | 可公开使用的示例任务 |

详见 [架构与取舍](docs/ARCHITECTURE.md)、[API 协议](docs/PROTOCOL_V0_1.md)、[开发计划](docs/DEVELOPMENT_PLAN.md)。

## 安全与限制

仅在可信 LAN 或加密私有网络（如 Tailscale）使用。**普通 HTTP 没有传输加密**；不要映射到公网。HTTPS 使用默认的证书校验。系统凭据库不可用时设备令牌只留内存，下次重新配对。不要上传 `.env`、私钥或账号凭据。任务内容和缓存未做静态加密。

默认单文件 1 GiB、同任务输入和所有结果累计 2 GiB，可配置。中断后从头重传；不支持断点续传。草稿保留供恢复，暂无删除/垃圾回收界面。大量历史目前会读入 GUI 元数据列表。详细边界见 [安全说明](docs/SECURITY.md)。

## 路线图

V0.1：可靠人工交接（当前）；V0.2：官方公开接口支持的 Codex 自动执行；V0.3：其他 Agent 接入；V1.0：可复现工程交接；V2.0：授权的协作调度。**V0.2 及以后均未实现**，每个版本独立确定范围。

## 许可与贡献

项目自有代码采用 [MIT](LICENSE)。第三方组件遵守各自许可，Qt/PySide6 分发要求单独处理，见 [依赖告知与分发准备](docs/THIRD_PARTY_NOTICES.md)。欢迎按 [贡献指南](CONTRIBUTING.md) 提交脱敏复现、真实平台测试和改进。
