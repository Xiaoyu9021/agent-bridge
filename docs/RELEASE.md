# V0.1.2 首次预览发布准备

## 交付物

- `skills/agent-bridge/`：可直接从 GitHub 技能目录安装的自包含 skill。
- `agent-bridge-skill.zip`：同一技能的离线安装包。
- `agent-bridge-mac-skill.zip`：增加 Mac 首次联调说明的同一技能包。
- `SHA256SUMS.txt`、`skill-checksums.json`：公开发布包的大小与 SHA-256。

本次发布以 Codex、Windows/macOS 和显式文件交接为范围。DeepSeek Harness、WorkBuddy 和自动 Agent 调度尚未接入。发布为预览版；大文件 LAN 和真实断网恢复尚未实测。

## 本地检查

```sh
python scripts/build_skill.py
python scripts/build_skill.py --check
python -m ruff check .
python -m pytest -q
git add --all
python scripts/check_publish_tree.py
git diff --cached --check
```

上面的 Python 指向项目 .venv，开发依赖见 pyproject.toml。check_publish_tree 只检查 Git 已暂存/跟踪的内容，不读取用户的系统凭据或生产收件目录；它检测常见运行文件、密钥模式和技能清单不一致，不能替代完整安全审计。

打包使用明确的输入文件清单，固定 ZIP 时间与权限，不读取用户交付目录、.runtime 或任意额外文件。重复构建相同输入时包内容与 SHA-256 应一致。安装器校验清单，升级时保护用户修改和私有环境。

## GitHub 阶段

建立独立公开技能仓库，不将私有 SpaceWatch 项目作为本技能的发布仓库。使用确认的 GitHub 作者身份及隐私邮箱提交，通过现有 GitHub 授权推送。

推送后等待 Tests 工作流完成：Windows/macOS/Linux × Python 3.11/3.13。包任务依赖六组测试成功，上传明确命名的两个 ZIP 和校验文件。在线结果未产生前，不标为通过。

首个 Release 使用 v0.1.2，并标记预览版。Release 附件使用成功 CI 运行生成的包；安装链接指向该版本的 skills/agent-bridge。不要发布 .venv、.runtime、EXE、用户任务或真实 SpaceWatch 工程。

## 发布说明草稿

Agent Bridge 的首次 skill 预览版，让两个不同账号的 Codex 在可信局域网内交接执行报告、代码 ZIP 和截图。无需桌面程序、Qt 或额外模型 API Key。支持显式配对、哈希校验、固定 ID 重试和送达/收取/已读区分。

已完成 Windows 独立后台进程验证、真实 Windows ↔ Mac 基本双向交接，真实 SpaceWatch 使用试运行由用户确认。当前不自动唤醒聊天或执行收到的代码。HTTP 仅限可信网络；具体测试证据和未验证项见 TEST_REPORT.md。
