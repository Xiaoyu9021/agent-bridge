# Mac Codex：安装 Agent Bridge skill 并准备 SpaceWatch 联调

用户已将产品入口改为 Codex 内的 skill。当前不需要 `.app`、Qt 或重新构建桌面程序。Windows 已完成本机模拟测试；真实跨设备仍需本次配对验证。

收到 agent-bridge-mac-skill.zip 后：

1. 解压，读取 agent-bridge/SKILL.md，检查 scripts/install.py、bootstrap.py 和 bridge.py。
2. 找到 Python 3.11+。此前 Mac 验证安装过独立 3.13，可检查 python3.13 或 uv python find 3.13；不要改系统 Python 3.9。
3. 运行解压目录的 scripts/install.py，将技能安装到 Codex 本地技能目录。不覆盖已有不同技能；若确有旧版，先对照校验清单保留用户修改，再说明升级操作。
4. 使用返回的安装目录运行 scripts/bootstrap.py，再运行 scripts/bridge.py setup --name mac-codex。安装程序配置私有 .runtime，不需要用户填写端口或目录。凭据库不可用时明确说明，不明文回退。
5. 返回“Mac skill 已安装，接收进程已启动”，等待用户从 Windows 带来新的 invitation。不要猜 IP、扫描网络、重用历史连接码或宣称跨机通过。
6. 用户带来连接信息后，通过 stdin 交给 join --alias windows。让 Windows 查询 pending，用户核对名称后批准。Mac 用 peers 确认 paired。
7. 先发送一份明确标为“联调测试”的 UTF-8 报告，以及合成 ZIP 和 PNG（不要包含真实私钥或整个项目）。project 使用 SpaceWatch-Test。Windows receive 并实际读取报告后 read，Mac delivery-status 应区分 received_at 与 read_at。
8. 确认收发成功后，再按用户明确指定发送真实 SpaceWatch 本轮报告和执行包，不自动扫描全工程，不自动应用或运行收到的代码。

将实际命令、Python/系统版本、三附件校验与收取/已读结果记录为 MAC_SKILL_REPORT.md，提供错误的脱敏信息和待完成项。不要把 Windows 模拟结果写成 Mac 实测；新 skill 不沿用旧 `.app` 的测试结论。

常用命令由 SKILL.md 和 references/commands.md 提供。用户只在两个 Codex 对话里提出自然语言要求，无需手动操作命令行或手机中转。
