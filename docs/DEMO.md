# 三分钟演示：两个 Codex 之间交接文件

## 场景

Mac 上的 Codex 完成一轮 iOS 工作，Windows 上另一个账号的 Codex 需要阅读报告并准备下一轮需求。两台电脑已连接可信局域网，用户希望避免手机或聊天软件中转附件。

该场景已完成合成资料真实双向联调，原始脱敏回执在 evidence/real-lan.0.1.2.json；真实 SpaceWatch 使用结果由用户在 2026-11-03 确认。以下演示只用合成资料，不展示真实工程或凭据。

## 安装与配对

在两端分别给 Codex 仓库链接并说：“从 skills/agent-bridge 安装技能，配置本机交接端。”Agent 阅读技能与脚本，安装独立环境。第一次配对需要用户把短时 invitation 交给另一端，并在接收端核对设备名称后批准。

拍摄公开演示时不要展示真实连接码、凭据或实际工程路径；可以在连接码过期后录制，或遮住短时连接信息。

## 日常交接

Mac 对话：

> 使用 agent-bridge，把测试报告、测试 ZIP 和 PNG 发给 windows，项目 SpaceWatch-Test。

展示返回的 delivery_id 和 delivered_to_receiver，说明它只表示对方后台已收件校验。

Windows 对话：

> 使用 agent-bridge，收取 SpaceWatch-Test 最新交付，实际阅读 UTF-8 报告，检查 ZIP、PNG 和哈希，再确认已读。

展示独立收件目录、读取的报告和校验结论。原始测试中 Windows 收到 316 B 报告、170 B ZIP 与 99 B PNG，ZIP CRC 正常，PNG 为 32×32；这些是特定合成样本，不是容量限制。

Mac 对话：

> 查询刚才交付的 delivery-status，确认 received_at 和 read_at。

随后用同样的机制将下一轮测试执行单从 Windows 发回 Mac。反向配对只需要首次做一次。

## 演示结论与限制

用户在 Agent 对话里调用技能；文件通过 LAN 传输，接收方按需收取并读取。它不会自动唤醒聊天、接管账号或执行收到的项目代码。普通 HTTP 只用于可信网络；后台接收需要电脑开机、联网且进程运行。
