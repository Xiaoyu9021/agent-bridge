# 命令参考

入口 scripts/bridge.py；先运行 scripts/bootstrap.py，再 setup。由 Agent 执行，用户无需手工操作命令行。所有命令返回 JSON。

全局 `--profile <name>` 放在子命令前：同机不同 Agent 用不同 profile，并在后续命令保持一致。`--home <绝对目录>` 覆盖整个数据根目录，通常只用于测试。每个根目录独立身份、凭据和收件箱。

| 命令 | 用途 |
|---|---|
| setup --name windows-codex | 初始化并启动；重复调用幂等 |
| status / start / stop | 查看、启动、停止后台进程；stop 保留历史 |
| invite | 生成 10 分钟、一次性连接信息，仅分享给本人的另一端 |
| join --alias windows | 从 stdin 读取完整 invitation，等待批准 |
| pending | 查看申请设备名称、平台和 device_id，不输出内部请求密钥 |
| approve DEVICE_UUID / reject DEVICE_UUID | 用户核对后批准或拒绝申请 |
| peers | 查询能发送到的别名及配对进度 |
| revoke DEVICE_UUID | 撤销该设备访问本端的权限 |
| send --to windows --project SpaceWatch --title "本轮交付" --report REPORT --file ZIP | 发送报告及附件，附件重复 --file |
| outbox / retry DELIVERY_UUID | 查看发送历史，用同一份清单重试 |
| inbox --project SpaceWatch | 查看本端完整收到的交付和阅读时间 |
| receive --project SpaceWatch / receive --id DELIVERY_UUID | 导出最新未收取交付或指定交付，重复收取复用且复核 |
| read DELIVERY_UUID | 当前 Agent 实际阅读报告后确认已读 |
| delivery-status DELIVERY_UUID | 发送端查看 received_at / read_at，不等于代码验收 |

setup 支持 --listen auto（默认）、--listen 127.0.0.1（仅本机），或具体私有 IP。首选端口 47821，被占用时选择可用端口；实际地址见 status/invite。已有配置不会被重复 setup 覆盖。跨机地址变化后需重新邀请配对。

连接信息用安全的 stdin 传递，由 Agent 根据实际 shell 操作。例如 PowerShell 单引号 here-string，或 shell 单引号 heredoc；不要把用户内容直接拼入可执行 shell 代码，也不存入工程。

报告为 UTF-8，不超过 200 KiB。附件只接受明确选择的普通文件，不接受目录；默认单文件 1 GiB，累计 2 GiB。工具不自动打包目录或解压收到的 ZIP。

每轮收件在独立目录保存 TASK.md、manifest.json、attachments/、results/；receive 返回实际报告的 report_path，用户不需要手工找到文件再交给 Agent。

命令非零或 ok:false 时报告原因。超时先 outbox，再用原 ID retry。源文件改变时应新建交付。系统凭据库锁定时请用户解锁，严禁明文回退。后台进程已停止时 start。

HTTP 仅用于可信 LAN 或已有加密的私有网络。不做公网映射、自动执行代码、会话接管或账号共享。配对只授予向该接收端提交/读取相关任务的能力，不授予远程命令执行能力。
