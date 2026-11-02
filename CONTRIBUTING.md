# 贡献指南

请先阅读 README、docs/ARCHITECTURE.md 和 docs/SECURITY.md。当前仅接收 V0.1 的可靠性、跨平台体验和文档改进；未来 Agent 集成先通过 Issue 明确范围。

开发前安装 `.[dev]`。提交前运行 `python -m ruff check .` 和 `python -m pytest -q`。涉及文件传输时测试错误哈希、断线、权限及重试；涉及平台行为时说明真实测试设备。不要提交 `.local`、`artifacts`、数据库、任务内容或密钥。

PR 描述应交代具体问题、修改后的行为、测试命令和限制；截图只能使用脱敏的示例数据。架构与协议有变动时同步文档。源代码按 MIT 许可贡献；第三方材料需保留原始许可。
