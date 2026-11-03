# v0.1.3 双机验收

准备两台连在同一可信局域网的电脑，以及 Mac 和 Windows 上各一个 Codex 对话。使用候选分支 [preview-v0.1.3](https://github.com/Xiaoyu9021/agent-bridge/tree/preview-v0.1.3)。

## 首次安装和小文件交付

把候选分支链接分别发给两端 Codex，提出以下要求。

> 请从这个分支安装 Agent Bridge v0.1.3 到独立测试目录，使用 `trial-v013` 配置启动。按照技能说明配对，交接一份合成 UTF-8 报告和 ZIP，收件端读过报告后确认已读。保留原来使用的技能、配置和数据。

由 Codex 下载源码、审阅脚本并运行 `skills/agent-bridge/scripts/install.py --dest <测试技能目录>`，然后在返回的技能目录运行 bootstrap 和 bridge。后续命令统一在子命令前加 `--profile trial-v013`。Windows 与 Mac 分别使用 `trial-v013-win` 和 `trial-v013-mac` 作为设备名。用 `--version` 核对版本为 0.1.3。

Windows 生成邀请，用户交给 Mac。Mac 通过标准输入加入，别名为 `windows`。用户核对 Mac 名称后在 Windows 批准，Mac 检查 peers 确认已配对。交付使用项目 `Bridge-LAN-Trial-013`。记录收件、报告实际读取和已读结果。

## 大文件中断和恢复

1. Mac 在临时目录用 Python 标准库生成约 512 MiB 的合成 ZIP。以 ZIP_STORED 写入合成字节，同时准备简短的 UTF-8 报告。记录 ZIP 大小和 SHA-256，并为大文件交付生成固定 ID。
2. Mac 发起发送。Windows 在测试配置的 `receiver/attachments` 中观察 `.part` 文件大小。测试数据根目录可由 status 返回的 inbox 的上级目录确定。看到中断前已写入一部分文件时，由用户手动中断 Mac 网络。若发送已经完成，记录为正常大文件传输，另开一轮验证中断。
3. 确认发送端报告中断或超时，Windows 的收件箱尚无该 ID，临时文件已清理。恢复网络后查询原 ID 的 outbox 和 delivery-status。若接收地址已变，用新邀请恢复原别名配对。
4. 用原 ID retry。Windows 收取该 ID，核对 ZIP 大小、SHA-256 和 CRC，并在实际读完报告后确认已读。检查收件箱中该 ID 只出现一次，Mac 能查到收取与已读时间。

测试报告记录两端系统和 Python 版本、安装来源、每步结果、中断前已接收字节数、重试耗时与最终哈希。报告只保留脱敏结果，系统凭据保存在各自的凭据库。若物理中断未发生，报告写明实际完成的步骤。测试结束后只停止 `trial-v013` 配置。
