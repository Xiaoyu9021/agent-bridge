# macOS 使用与验证说明

**Mac 已回传 V0.1.0 基线验证：42 项测试、Keychain、大文件及 `.app` 自检通过。当前 V0.1.1 改了连接界面，需在 Mac 再次验证。真实双机联调仍未完成。** 历史证据见 validation/MAC_BASELINE_REPORT.md。

## 源码启动

安装 Python 3.11+ 和 Git，取得仓库后在根目录执行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m codex_bridge
```

首次启动选“加入连接”，粘贴 Windows 上通过“连接另一台电脑”→“复制连接信息”得到的内容，点“连接”。再回 Windows 确认设备名称即可。无需手动填写 IP、端口、目录或设备名；以后启动自动使用已保存设置。

已经打开过的客户端，可在主界面点击“连接另一台电脑”重新粘贴。技术参数与手动连接方式保留在高级选项。

无需共享两端 Codex 账号，不需要提供任何 Codex 令牌。

## 接收与导出

1. 选择收到的任务，阅读完整 Markdown 和附件列表。
2. 点击“接收任务”。
3. 点击“保存任务给 Codex”，选择专门的任务父目录。
4. 完成后在新目录得到 `TASK.md`、`manifest.json`、`attachments/`、`results/`。重名附件安全改名，映射在 manifest；下载不完整时不会显示导出完成。
5. 在 Mac Codex 中手动选择/引用该目录，例如输入“请读取 `/Users/你的用户名/BridgeTasks/Task_任务UUID/TASK.md`，检查附件后完成需求，将报告放到 results。”
6. 在 Bridge 点击“开始处理”。完成后点击“回传结果”，填写总结、选择已完成或已失败，并添加报告、截图及代码包。

Bridge 不会自动开始 Codex 工作，不会自动解压项目包。是否解压、运行代码由你在本机工作环境中决定。

## 跨网络

两台设备可以自行安装并登录授权的 Tailscale 网络，使用 Windows 的 Tailscale IP。先确认两端私有网络互通；Bridge 不代为配置网络账户、VPN 或防火墙。普通 LAN 上的 HTTP 没有加密，不应传送敏感凭据。

## 构建（V0.1.0 已测，V0.1.1 待复核）

```sh
sh scripts/build_macos.sh
open dist/CodexBridge.app
```

仅能在 Mac 本机构建对应架构应用。当前没有开发者证书，不提供签名或 notarization；不宣称可直接通过所有 Gatekeeper 检查。不建议关闭系统安全机制；可优先用源码方式验证。

## Mac 验证清单

```sh
.venv/bin/python -m ruff check .
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python -m codex_bridge --self-check artifacts/macos-source-smoke.json
.venv/bin/python scripts/verify_large_transfer.py
```

然后与 Windows 真实联调：至少 3 个附件含中文名 → 接收、导出并核对哈希 → 状态更新 → 回传报告和截图 → Windows 下载 → 两端重启后确认历史 → 断网失败及重试。分别记录 Mac 型号、架构、系统/Python/Qt 版本、测试命令和真实结果，补入 TEST_REPORT。
