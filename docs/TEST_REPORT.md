# V0.1 测试报告

更新日期：2026-11-03（Asia/Shanghai）。各项证据保留实际验证日期。当前是本地开发预览，**不是跨平台验收全部通过**。

## V0.1.2：主要交付改为 Agent Bridge skill

运行入口为 `skills/agent-bridge`。已完成自包含技能包、独立无 Qt 环境、安装校验、后台收件、本地控制、两端配对、发送/收取/已读区分、固定 ID 重试和收件复核。

- Windows 自动化 **65 passed**：原 53 项回归、9 项 Agent 交付与 3 项技能包安装/升级测试；Ruff、嵌入代码同步校验与技能校验通过。两端已安装 skill、运行私有接口接收进程并分别完成配对。
- `scripts/verify_skill.py` 使用技能自己的虚拟环境，并实际确认未安装 PySide6；通过独立命令进程、两个后台进程和真实 Windows 系统凭据库完成三附件交付、中文文件名、SHA-256、重试幂等、收取与已读时间、双方重启恢复。
- 测试资料为合成执行报告、有效 ZIP 和原始图片字节 fixture，不代表 SpaceWatch App 已执行开发或通过功能验收。
- verify_skill.py 为 Windows 本机回环模拟测试，另已完成下述真实 Windows ↔ Mac 基本双向交接。Mac 新 skill 安装及真实收发已验证，不依赖历史桌面版结果推断。
- skill-creator 的 quick_validate 通过，Windows 使用 Python `-X utf8`；嵌入运行代码与源代码一致性由 build_skill.py --check 验证。
- 此前 512 MiB 证据验证复用的传输核心；本轮独立 skill 测试使用小型交付，不额外宣称完成了 skill 层 512 MiB 实测。

2026-11-03 发布准备回归为 **68 passed**：在原 65 项基础上，新增可复现打包与额外文件排除、陈旧清单识别、暂存文件发布检查三项测试。Ruff 通过；测试有一条上游 Starlette/httpx 弃用警告，无失败。GitHub Actions 尚未运行，不将本地结果推断为线上或其他平台通过。见 `evidence/release-preflight.windows.json`。

原始脱敏证据见 `evidence/skill-smoke.0.1.2.windows.json` 和本轮测试 JSON。主要实现代码为 `src/codex_bridge/agent/`；生成 runtime 不手动维护。

### 首轮线上 CI 与清单排序修复（2026-11-03）

首次推送 [Tests #1](https://github.com/Xiaoyu9021/agent-bridge/actions/runs/41483596503) 的两个 Windows 任务通过；Linux 在技能包同步检查失败。原因是 pathlib 的默认路径排序在 Windows 和 POSIX 上对大小写的处理不同，使生成清单的 JSON 键顺序不一致。已改为按标准化 POSIX 路径字符串排序，新增 PureWindowsPath/PurePosixPath 清单一致性测试；修复后的本地 Windows 回归 **69 passed**，Ruff 与清单检查通过。修复后线上结果单独记录，不以本地回归代替。见 `evidence/manifest-order-fix.windows.json`。

### 真实局域网双向交接（2026-11-02）

- Mac → Windows：交付 `0e68cac2-639f-424d-a12e-304f0d9759ec`，3 个文件共 585 B。Windows 实际读取 UTF-8 报告，ZIP 可打开且 CRC 通过，PNG 实际显示为 32×32 蓝色图，三文件大小和 SHA-256 均与清单一致。收取及已读时间均已记录。
- Windows → Mac：交付 `0287c71b-e4d9-4bfb-bea4-640e91326732`，3 个文件共 1177 B。用户回传 Mac 验证通过；Windows 通过鉴权 API 查询到 received_at 与 read_at，确认已收取并已读。Mac 文件内容验证依据用户回报，不宣称 Windows 在 Mac 上独立操作过解码器。
- 以上均为 SpaceWatch-Test 合成资料；完整脱敏记录在 `evidence/real-lan.0.1.2.json`。不代表真实 SpaceWatch 工程验收，也不替代物理 LAN 大文件、断网恢复和 Tailscale 测试。

### 真实业务试运行（2026-11-03，用户确认）

用户在本对话确认：已在实际 SpaceWatch 开发场景完成上一轮建议的真实执行报告、代码包与截图交接试运行。该结论来源于用户确认，没有在本项目对话中重新打开或审核真实业务附件；不添加臆造的交付 ID、哈希、文件大小或 App 验收结果。公开证据只记录该确认，不包含真实报告与代码。见 `evidence/spacewatch-trial.user-confirmed.json`。

## V0.1.1 易用性更新

Windows 新版自动化：**53 passed**，Ruff 和 pip check 通过。新增首次启动折叠配置、单次粘贴邀请、两个 Qt 窗口真实 HTTP 配对、主机本地确认、接收/开始按钮和旧配置复用测试。原 42 项核心测试仍通过。源码 native Qt 自检通过；PyInstaller 0.1.1 最终 EXE 自检退出码 0，验证新向导、邀请解析、私有网卡枚举及原有 Qt/API 能力。新版证据为 `evidence/*0.1.1.windows.json`。

界面变更：初次仅选“创建连接 / 加入连接”，邀请一次粘贴；网卡、设备名、端口与目录自动设置，技术参数留在高级设置；记住配置后跳过向导。未新增远端发现，不扫描网络，不移除本地确认。

Mac 返回的是 **V0.1.0 基线** 的 42 项测试、512 MiB 回环传输、Keychain 与源码/`.app` 自检证据，见 [原始报告](validation/MAC_BASELINE_REPORT.md) 和 `evidence/*.baseline.macos.json`。该报告没有业务源码修改，不能把基线结果当作新版连接界面已在 Mac 验证。

| Mac 基线项目 | 回传结果 |
|---|---|
| 系统 / 架构 / Python | macOS 26.6.2 / arm64 / 3.13.18 |
| pytest / Ruff / pip check | 42 passed / 通过 / 通过 |
| 512 MiB 上传 / 下载 | 0.913 秒 / 0.925 秒，SHA-256 一致 |
| Host / Client+Qt RSS 增量 | 2.62 MiB / 5.83 MiB |
| Qt 心跳 | 41 次，最大间隔 0.056 秒 |
| Keychain | 随机值写入、读取、删除通过 |
| `.app` 构建和自检 | 通过；无开发者证书或 notarization |
| 原生 GUI 完整人工闭环 / 真实双机 | 未完成 / 未执行 |

## Windows V0.1.0 基线环境与结果

- Windows 11 `10.0.26200`，Python 3.13.2。
- FastAPI 0.162.0、Uvicorn 0.54.0、httpx 0.28.1、Pydantic 2.14.2、PySide6 6.12.0。
- pytest 9.2.0：**42 passed**；测试包括真实 TCP/HTTP、SQLite 重启恢复、权限、中文文件和 Qt 后台工作。测试详细 XML 位于本地 `artifacts/tests.xml`（不提交测试运行目录）。
- Ruff 0.17.3：检查通过；`pip check`：无依赖冲突。
- 1 项上游弃用警告：Starlette TestClient 提示其 httpx 传输未来改用 httpx2；当前测试通过，真实 HTTP 测试另用独立 httpx 客户端。
- Windows 源码 native Qt/API 自检：通过，发现 451 个系统字体族。
- Windows PyInstaller 6.22.3：onedir 构建成功；实际 EXE 自检退出码 0，Qt 窗口组件、系统字体及真实 HTTP 配对/任务通过。该自检不是人工逐项点击测试。
- 文档截图来自真正的 Qt 窗口和隔离示例 Host，不包含用户项目；Windows offscreen 截图引用本机已安装字体，未分发字体文件。

## 512 MiB 实测

命令：`python scripts/verify_large_transfer.py`。使用独立 Host 进程、两个独立 httpx 客户端、Qt 窗口及后台工作线程。源文件为随机块流式写出的 536,870,912 字节文件，未整文件载入内存；临时文件测试后清理。

| 指标 | 结果 |
|---|---|
| 文件大小 | 512 MiB（536,870,912 bytes） |
| 上传（含服务端落盘复核和发布） | 4.026 秒 |
| 下载（含客户端完整性校验） | 2.028 秒 |
| Host RSS 峰值增量 | 3.44 MiB |
| Client + Qt RSS 峰值增量 | 4.96 MiB |
| Qt 50ms 心跳 | 114 次，最大间隔 0.071 秒 |
| 下载后 SHA-256 | 与源文件一致 |
| 测试网络 | Windows 本机 127.0.0.1，不是真实 LAN / Mac |

这些速度与内存采样只描述这次本机测试，不代表物理网络吞吐或所有平台性能。原始 JSON 位于本地 `artifacts/large-transfer.json`。

脱敏的可提交证据同时保存在 `docs/evidence/`。构建初测发现 QtGui DLL 无法加载：PyInstaller 从外部 Poppler 工具链 PATH 误选了 ICU 库，而源码实际使用 Windows 系统 ICU。Windows 构建脚本改为限定 Python 与系统 PATH 后，最终 EXE 自检通过。窗口版 Uvicorn 禁用默认控制台日志配置，以适配没有标准输出流的打包环境。

## P0 验收映射

| 项目 | 本地证据 | 状态与限制 |
|---|---|---|
| AT-01 双端启动 | Windows 新版自检，Mac 基线源码/`.app` 自检 | Mac 新版界面待复核 |
| AT-02 配对 | 一次性、过期、错误频控、主机确认、拒绝、撤销测试 | 本地通过 |
| AT-03 发送 | 真 HTTP 中文任务 + 3 附件；反向任务测试 | 本地通过；跨机待测 |
| AT-04 接收 | 接收客户端读取正文、下载与导出 | 本地通过 |
| AT-05 完整性 | SHA-256、中文名、同名映射、损坏拒绝 | 本地通过 |
| AT-06 大文件 | 两平台各有 512 MiB 回环独立进程 + Qt 心跳证据 | 基线两平台通过；真实 LAN 待测 |
| AT-07 状态 | 完整迁移、非法迁移、失败重开、事件历史 | 本地通过 |
| AT-08 回传 | 真 HTTP 报告上传、原任务关联、发送端下载 | 本地通过 |
| AT-09 重启 | Host 关闭后重建、保留 peer token 与附件、Client 缓存 | 本地通过 |
| AT-10 失败可见 | 实际 TCP 上传中途断开、重试、截断下载清理、Qt 失败重试状态 | 本地通过；真实拔网体验待测 |
| AT-11 安全 | 路径/UUID、越权、输入校验不泄密、公网监听拒绝 | 测试通过；不等于独立安全审计 |
| AT-12 导出 | TASK.md/manifest/附件、冲突重命名、失败清理 | 本地通过 |
| AT-13 不同账号 | 无 Agent 登录/账号接口，无凭据要求 | 设计和代码符合；未操作真实 Codex 账号 |
| AT-14 文档 | README、两端手册、Mac 按源码启动和验证 | 新版易用流程与双机手册待实机复核 |

## 尚未验证

- V0.1.1 新连接界面的 macOS 复核、两个原生 GUI 完整人工闭环；Intel Mac。Apple Silicon 的 V0.1.0 启动、Keychain 与 `.app` 已有回传证据。
- 真实 LAN 大文件和断网恢复、Tailscale、其他网络/防火墙配置；基本双向三附件与已读流程已完成。
- 签名、notarization、全新无 Python 的 Windows 机器。
- GitHub Actions 在线运行、公开仓库、Release 发布和第三方分发许可最终核查。

## 复现命令

```powershell
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m pytest -q --junitxml=artifacts/tests.xml
.\.venv\Scripts\python scripts\verify_large_transfer.py
.\.venv\Scripts\python -m codex_bridge --self-check artifacts\source-smoke.json
.\scripts\build_windows.ps1
```

Mac 验证命令和真实跨机步骤见 USER_GUIDE_MACOS.md。CI 文件已配置，但未经运行的矩阵不能标为通过。
