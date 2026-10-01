# Google 只读 Connector 本地配置

首版连接 Gmail 收件箱和主日历，支持即时读取、周期新增变化检查、每日摘要。邮件发送、修改日程、其他日历选择、Drive 和 push 通知不包含在此版本。

## OAuth 配置

1. 在 Google Cloud 项目启用 Gmail API 和 Google Calendar API。
2. OAuth Client 选择 Web application。在“已授权重定向 URI”中新增：

   `http://127.0.0.1:8767/api/connectors/google/callback`

   原来用于其他应用的回调可以保留。此服务通过后端 OAuth 接入，不依赖浏览器端 Google SDK 的 JavaScript origin。打开本地工作区时使用同一个 `127.0.0.1` 地址，避免与 `localhost` 混用导致回调 Cookie 不匹配。
3. 配置 Google Auth Platform 的 Audience/Test users；测试模式加入自己的 Google 账号。只读 scopes 为 `gmail.readonly` 和 `calendar.events.readonly`。公开服务的审核要求见 [Google scopes 文档](https://developers.google.com/workspace/gmail/api/auth/scopes)。
4. 在本地 `.env.test` 填写 Client ID 与 Client Secret，格式参考 `.env.test.example`。该文件由 `.gitignore` 排除，不提交或推送。不要将真实值写入 example、文档、聊天示例或日志。

后端默认读取 `.env.test`，只导入三个 Google OAuth 配置项。可用 `FINANCE_CONNECTOR_ENV_FILE` 指定另一个本地路径。修改配置后重启 API 和 Worker。环境变量优先于文件。OAuth 不要求用户输入工作区 Token。

授权采用 PKCE 和一次性 state，并绑定发起授权的浏览器 Cookie。成功后，刷新凭证加密存入本地 SQLite；加密主密钥默认在 `~/.local/share/finance-agent/credential.key`，权限 600，位于仓库外，可用 `FINANCE_CREDENTIAL_KEY_FILE` 配置。数据库与密钥共同属于敏感备份；密钥丢失需重新授权。

即时 `google_read` 返回邮件正文和日程描述的前 500 字预览，并将结果限制在工具容量内。`text_truncated`、`description_truncated` 和 `truncated` 标注截断；`fetched_counts` 表示本次取得的记录数，`returned_counts` 表示实际提供给模型的记录数，不等于邮箱全部邮件数。后台任务分析继续使用单独的输入限制。

## 连接错误排查

- `redirect_uri_mismatch`：在同一个 OAuth 客户端登记上面的完整回调地址。
- 测试模式 `access_denied`：把登录邮箱加入 Audience → Test users。
- `gmail_api_disabled` / `calendar_api_disabled`：在 OAuth 客户端所属项目启用对应 API，等待配置生效，再重试连接或读取。
- `insufficient_scopes`：重新连接，授权邮件和日历只读访问。
- `domain_policy_denied`：联系 Google Workspace 管理员开放应用访问。
- `permission_denied`：Google 未提供已识别的错误原因；检查 API、账号授权及管理员策略。此错误不保证稍后重试即可恢复。

后端只返回已识别的错误分类，不返回 Google 原始错误内容或凭证。连接回调需要先读 Gmail 账号资料；若 Gmail API 未启用，账号不会保存为已连接。

## 启动三个进程

先安装依赖并迁移：

```sh
uv sync
uv run finance-admin migrate
npm --prefix services/agent-runtime ci
```

在三个终端分别运行（都从仓库根目录启动）：

```sh
uv run uvicorn finance_agent.entrypoints.api:create_app --factory --host 127.0.0.1 --port 8767 --no-access-log
uv run finance-worker
uv run finance-scheduler
```

API 和 Worker 需配置同一个模型 provider。可以导出 `DEEPSEEK_API_KEY`，或设置 `FINANCE_MODEL_ENV_FILE` 指向已授权的模型配置文件；模型凭证不会传入 Google Connector 或桌面镜像。Scheduler 不需要模型密钥。

浏览器打开 `http://127.0.0.1:8767`，点击“连接” → “连接 Google”，由用户完成 Google 授权。回调成功后返回原工作区，连接状态会自动刷新。

## 对话中的使用方式

- “每 15 分钟检查新邮件，有账单到期或需要回复就提醒我。”
- “每天北京时间 8:30 汇总我的最近 24 小时邮件和今天的日程。”
- “明天上午 9 点提醒我复盘。”（无账号的 prompt 提醒不会读取外部数据。）
- “暂停账单提醒任务。”或在任务卡片点“暂停”。也可以在对话中要求修改执行时间/指令，或者取消任务。

任务卡片和“任务与提醒”展示下次执行、上次成功、最近错误、暂停/恢复和执行历史。后台结果写回原对话并产生站内提醒，网页关闭期间也能执行，前提是 Worker/Scheduler 正在运行。

Watch 从任务创建之后的新收件箱邮件和主日历变化开始，不自动汇报创建前的旧消息。邮件 `historyId` 与日历 `syncToken` 持久保存；游标过期时有界重新同步，按任务去重。一次最多分析 30 个新变化，剩余变化留到后续运行。Digest 显示当日主日历和最近 24 小时收件箱邮件，最多各 100 条并返回截断标志。日历增量删除事件也会处理。

后台任务最多重试 3 次；执行租约带心跳，旧 Worker 无法覆盖新 Worker 的结果。每日墙上时间使用 IANA 时区：夏令时不存在的时间跳过当天，重复时间只执行第一遍。暂停或断开连接会撤销未完成运行的写回权；重连后需显式恢复暂停的任务。

已有租户 callback 配置也适用于后台 Agent 任务完成事件：独立持久 outbox、HMAC 签名、有限重试和 dead-letter，与站内结果事务一致。没有配置外部回调时只产生站内记录，不发送外部消息。

## 验证与目前范围

- 合成测试覆盖调度、DST、租约、增量同步、分页、游标失效、OAuth state/PKCE、凭证加密、账号断开、多任务共享游标、提醒去重和签名回调重试。
- 已通过真实 Pi + DeepSeek 验证对话创建 watch 任务，并使用合成邮箱数据完成后台分析和站内提醒；验证数据库与凭证均临时隔离，没有向真实邮箱发送邮件。
- 真实 Google 账号已完成 consent、token exchange、即时邮件/日历读取、后台 Pi 摘要、新邮件提醒及后续零新增检查。会议的提前触发、改期和取消另由合成测试覆盖；没有新增或修改真实日历事件。
- 首版轮询同步；Google push 订阅、其他日历、附件获取、更多生态和生产服务监督/密钥管理仍待实现。分析上下文有大小限制，超限任务记录错误，不静默丢弃数据或游标。

实现依据：[OAuth Web server flow](https://developers.google.com/identity/protocols/oauth2/web-server)、[Gmail 增量同步](https://developers.google.com/workspace/gmail/api/guides/sync)、[Calendar 增量同步](https://developers.google.com/workspace/calendar/api/guides/sync)。
