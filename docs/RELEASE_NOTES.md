Agent Bridge 的首次 skill 预览版：让不同账号的 Codex 在可信局域网内直接交接执行报告、代码 ZIP 和截图，省去手机中转。

- 两端各安装一次，由 Agent 配置 Python 环境与后台接收进程，无需 EXE、Qt 或模型 API Key。
- 显式配对与设备授权、SHA-256 校验、固定交付 ID 重试，以及送达、收取、已读回执。
- 自包含 skill 源码包与校验文件由本版本 CI 构建；发布任务依赖六组跨平台测试全部成功。
- 已完成真实 Windows ↔ Mac 基本双向交接；真实 SpaceWatch 工作流试运行由用户确认通过，公开资料不包含实际工程与交付文件。

把下面这段发给 Codex：

> 请从 https://github.com/Xiaoyu9021/agent-bridge/tree/v0.1.2/skills/agent-bridge 安装 Agent Bridge skill，并配置本机作为文件交接端。

当前范围：Codex 下的显式文件交接。HTTP 仅限可信局域网或已有加密的私有网络；不自动唤醒聊天或执行附件，无断点续传。真实 LAN 大文件和断网恢复尚未验证；DeepSeek Harness、WorkBuddy 尚未接入。详情见仓库 README 与测试报告。
