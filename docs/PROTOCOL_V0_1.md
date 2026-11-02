# REST 协议 v0.1

所有业务接口以 `/api/v1` 为前缀。除 health、pair、pair/status 外需要 `Authorization: Bearer <设备令牌>`。受保护的 OpenAPI 文档在 `/api/v1/openapi.json`，与实际实现同步生成。

错误格式：`{"error":{"code":"incomplete","message":"附件尚未完整上传并校验"}}`。常见状态：401 未授权、403 无操作权限/配对码无效、404 不存在或不可见、409 状态或 UUID 冲突、410 已过期/丢失、413 超限、422 校验失败、429 频率限制、507 存储失败。

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | /health | 协议版本与健康状态 |
| POST | /pair | 设备元数据 + code，返回待本机确认的 request_id |
| POST | /pair/status | 请求体 request_id，返回 pending/rejected/approved；成功附一次性 token |
| GET | /devices | 有效设备名称、平台、角色与 last_seen |
| GET | /settings | 单文件和单任务总量上限 |
| GET | /openapi.json | 鉴权后的 OpenAPI schema |
| POST | /tasks | TaskInput，创建草稿；UUID 幂等 |
| GET | /tasks | 当前设备可见任务，q、offset、limit，limit≤200 |
| GET | /tasks/{id} | 完整任务、可见结果、附件清单和事件 |
| PUT | /tasks/{id}/attachments/{attachment_id}/content | 原始字节流；附件必须提前声明 |
| POST | /tasks/{id}/publish | 附件校验齐全后发布任务 |
| GET | /attachments/{id}/download | 已校验文件流；X-SHA256 响应头 |
| PATCH | /tasks/{id}/status | 接收设备更新 status |
| POST | /tasks/{id}/results | ResultInput，创建结果草稿 |
| GET | /tasks/{id}/results | 当前设备可见结果 |
| POST | /tasks/{id}/results/{result_id}/publish | 原子发布结果并更新任务状态 |

TaskInput：id(UUID)、title、description_md、recipient_device_id、source_agent/target_agent（纯元数据）、attachments。身份由令牌确定，不允许 sender_device_id 输入。

附件声明：id(UUID)、original_filename、size_bytes、sha256(小写十六进制)、mime_type。V0.1 一次最多 100 个输入附件和每条结果最多 100 个产物，默认单文件 1 GiB、任务累计 2 GiB。上传完整内容后若哈希不符则不发布，清理 `.part`。

ResultInput：id(UUID)、summary_md、outcome(completed/failed)、artifacts。只有任务接收者可以提交。先 accepted → in_progress，再完成或失败。failed 可回到 in_progress，completed 为终态；可追加同 outcome 的交付记录。

重试必须复用原任务/结果/附件 UUID 及相同内容；新 UUID 表示新任务。服务端不会依据标题自动去重。上传失败从头再传，不能宣称支持断点续传。

导出 manifest 记录 schema_version、完整可见任务、附件哈希和 export_files（attachment_id、原名、安全相对路径、大小、哈希）。未发布的结果草稿不应作为交付内容使用。
