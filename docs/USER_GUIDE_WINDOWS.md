# Windows 使用说明

## 安装与启动

已有本机构建时，保留整个 `dist/CodexBridge/` 目录，双击 `CodexBridge.exe`。不能只复制一个 EXE；程序还依赖同目录的 `_internal`。这不是签名安装包。

源码启动（PowerShell，在项目根目录）：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m codex_bridge
```

首次启动选择“创建连接”→“开始使用”即可，设备名、网络和保存目录自动设置。以后启动会直接进入任务页，无需重复配置。

需要排查多网卡或本机测试时才展开“高级设置”：监听 IP 留空代表自动选择；填 `127.0.0.1` 只供本机测试；也可指定本机局域网或 Tailscale IP。端口默认 47821。拒绝公网和 `0.0.0.0`。如果没有可用网络，程序会退回本机模式并在复制连接信息时解释原因。

Windows 防火墙若提示，按实际网络只允许可信的专用网络。不要开放公网端口映射。本工具不会自动修改防火墙。

## 配对 Mac

1. Windows 点击“连接另一台电脑”→“复制连接信息”，把复制的内容传到本人的 Mac。
2. Mac 首次启动选“加入连接”，粘贴刚复制的内容，点击“连接”。已经打开过软件时，点主界面的“连接另一台电脑”再粘贴。
3. Windows 连接窗口会显示 Mac 名称，核对后点击“确认是我的电脑，允许连接”。不用手动填写 IP 或端口。
4. Mac 自动取得授权，两端设备列表可见彼此。授权优先存入系统凭据库；不可用时下次需重新配对。

连接信息 10 分钟有效且只用一次。连接窗口可取消邀请或重新生成；已连接设备可在“设置”→“管理已连接设备”解除连接。解除不删除已下载副本。

## 一次完整任务

1. Windows 新建任务，选择 Mac，填写标题和 Markdown 指令，添加 `requirements.md`、`project.zip`、截图等附件。
2. 点击发送。后台计算 SHA-256 并传输，全部校验完成后任务才对 Mac 可见。进度区“已完成”表示已提交到 Host，不等于 Mac 已人工接收。
3. Mac 点击“接收任务”→“保存任务给 Codex”，手动交给本机 Codex，再点击“开始处理”。
4. Mac 点击“回传结果”，添加 `execution-report.md`、截图、代码包。Windows 在原任务中阅读反馈，选择结果附件下载。
5. 需要继续澄清时可新建下一轮任务；Mac 同样可以向 Windows 发任务。

## 失败与恢复

网络失败时不会显示上传成功，点击“重试上次操作”，任务 UUID 保持不变。源文件在重试期间应保持内容不变。重启后仍有草稿时，选中任务点击“继续发送草稿”，重新选择全部原始附件，程序按文件名和哈希匹配。

断线时界面保留最近同步的历史；新任务、状态更新和下载需要恢复 Host 连接。Client 每 4 秒自动重连。Host 重启后任务和完整附件保留。客户端授权若已撤销/丢失，重新配对即可。

若源附件已修改或丢失，旧草稿不能用不同内容继续提交，应建立新任务；当前没有删除草稿界面。

## 配置与目录

“设置”中的“高级设置”可修改设备名、保存目录、IP/端口、大小限制，保存后下次启动生效。通常无需改动。默认单文件 1 GiB、任务输入与结果累计 2 GiB。主机关闭时停止监听。

默认数据目录由 platformdirs 根据操作系统确定，可用 `--data-dir <路径>` 或 `BRIDGE_DATA_DIR` 覆盖。环境变量还有 `BRIDGE_HOST`、`BRIDGE_PORT`、`BRIDGE_MAX_FILE_BYTES`、`BRIDGE_MAX_TASK_BYTES`。向导会优先显示上次保存的设置。

本机双实例测试，用两个 PowerShell 窗口启动：

```powershell
.\.venv\Scripts\python -m codex_bridge --data-dir .local\host --name Windows
```

```powershell
.\.venv\Scripts\python -m codex_bridge --data-dir .local\client --name Mac模拟端
```

前者选“创建连接”，在高级设置将监听 IP 明确填为 `127.0.0.1`；后者选“加入连接”。本机测试可在高级设置手动填写地址 `http://127.0.0.1:47821` 和连接码。这不能替代真实 Mac 验证。

## 构建与自检

```powershell
.\scripts\build_windows.ps1
$smokeProcess = Start-Process -FilePath .\dist\CodexBridge\CodexBridge.exe -ArgumentList '--self-check', 'artifacts\packaged-smoke.json' -WindowStyle Hidden -Wait -PassThru
$smokeProcess.ExitCode
Get-Content artifacts\packaged-smoke.json
```

自检只使用临时示例数据，创建 Qt 窗口组件并测试真实 HTTP 配对和任务，不依赖用户数据。
