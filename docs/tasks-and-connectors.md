# 后台任务与 Connector 设计

日期：2026-10-01。状态：首版轮询实现已落地，Google OAuth、真实账号即时读取、后台摘要及新邮件提醒已验收；使用说明见 [Google 配置与任务运行](google-setup.md)。底层为通用 Assistant，Finance 为首个专业场景；邮件、日历支持个人持续跟进。新增能力见 [主动助手](proactive-assistant.md)。

## 首个可交付场景

用户在 Chatbox 中说：“每 15 分钟检查一次我的新邮件，有账单、付款期限或需要回复的内容就提醒我，并参考日历判断时间冲突。”

1. 未连接账号时，聊天显示“连接 Google”卡片；OAuth 由用户在 Google 页面完成。
2. 连接后，聊天显示任务卡片：账号、邮件范围、关注条件、15 分钟间隔、时区、首次运行时间及提醒位置。用户原始请求已经授权这个明确范围，不额外增加通用权限开关。
3. 第一次运行建立同步基线。默认从任务启用后关注新变化；用户要求回顾历史时才读取指定历史范围。
4. 后台读取新增邮件和相关日历事件。先合并、去重，再调用 Pi 分析，避免每封邮件单独唤醒一次模型。
5. 有需要处理的变化时，在原对话写入摘要和任务通知，提供邮件/日历原文链接、来源时间与建议。没有变化则更新“已检查”，不刷屏。
6. 用户在任务卡片或“任务与提醒”中暂停、修改或删除任务，查看上次成功、下次执行、错误与历史运行。

第二个场景：“每天北京时间 8:30 汇总今天的会议和昨晚的重要邮件。”必须持久保存 IANA 时区；每日墙上时间与固定秒间隔分开表示，处理夏令时变化。

首版只读取内容和生成建议；发送邮件、改日程等能力后续按用户具体指令增加，不把读取授权扩展为写入授权。

## 当前代码能做什么

| 模块 | 已实现 | 关键缺口 |
| --- | --- | --- |
| Chatbox / Pi | 前台对话与独立后台 Pi 执行，结果追加原对话；任务工具、MCP stdio | 更多生态工具与生产部署 |
| Scheduler | 一次性、固定间隔、时区每日任务；过期运行合并，避免补跑风暴 | 生产服务监督与运维可观察性 |
| Worker | 资产快照与 Agent 任务分派，租约心跳、重试、Connector 同步和模型分析 | 附件与更多任务类型 |
| Reminder / Callback | 原对话写回、站内通知、持久回调 outbox 与有限重试 | Telegram 已实现，真实投递待专用配置；更多渠道 |
| Connector | Binance / OKX 只读 CLI；MCP；Google OAuth、账号状态、同步游标与只读 API、邮件筛选与分段全文读取 | HTTP MCP、更多 Google 数据及其他生态 |
| Desktop | 按需启动、真实共享桌面、浏览器 DevTools MCP | 不是邮件/日历后台同步的依赖，不为每次同步启动桌面 |

原资产周期任务继续分析固定快照；新增 Agent 任务独立执行 Connector 读取与 Pi 分析，不替换原财务计算。

## 优先级与验收

| 顺序 | 交付 | 验收依据 |
| --- | --- | --- |
| P0-1 | 通用 Agent 任务：一次性、固定间隔、每日指定时区；持久运行记录 | API 重启后仍执行；失败重试不重复提醒；同任务不并发运行 |
| P0-2 | Google Connector：OAuth、Gmail 和 Calendar 只读 | 授权、自动刷新、撤销可验证；前台与后台使用同一个授权账号 |
| P0-3 | 新邮件增量同步 + Pi 分析 + 原对话提醒 | 新邮件只报告一次；零新增不产生模型费用；故障恢复不漏掉已取得变化 |
| P0-4 | 每日日程/邮件摘要 | 关闭浏览器仍运行；每次结果可追溯到源数据和同步范围 |
| P1 | Gmail / Calendar push、连接状态 UI、按条件提醒、外部通知渠道 | 通知重复或丢失均可恢复，订阅续期与轮询兜底可测 |
| P2 | Drive / Docs / Sheets；Microsoft 邮件和日历；其他用户指定生态 | 复用任务和连接管理，不为每个生态复制一套后台系统 |

先实现轮询可避免首版依赖公网 Webhook 和 Pub/Sub 部署；同步接口保持同一套，后续 push 只增加唤醒入口。频率是产品默认值，实际配额与规模需实测。

## Google 接入选型

建议采用 Google OAuth + 官方 Gmail/Calendar REST API 完成首版增量同步。Pi 通过应用的受控工具读取、搜索已连接账号，后台同步复用同一 Connector。凭证留在后端凭证库中，工具参数只允许连接 ID；不放进桌面镜像、模型上下文或邮件内容。

Google 的官方远程 Workspace MCP 已有 Gmail、Calendar 等入口，但目前文档标为 Developer Preview，接入受预览资格和部分组织策略影响。适合作为可选交互路径；我们当前 MCP 仅支持 stdio，接入远程服务还需 Streamable HTTP 和 OAuth。见 [Google Workspace MCP 配置](https://developers.google.com/workspace/guides/configure-mcp-servers)。

`googleworkspace/cli` 提供 Workspace API 的动态命令与 JSON 输出，可加快开发验证；仓库明确写明不是 Google 官方支持的产品，且仍可能有破坏性更新。不能把它当成稳定的托管 Connector。若采用，固定版本，并在应用层限制账号、方法与权限，不能直接开放任意 CLI 命令。见 [项目 README](https://github.com/googleworkspace/cli)。

OAuth scopes 首版使用 `gmail.readonly` 与 `calendar.events.readonly`；需要列举用户日历时再增加 `calendar.calendarlist.readonly`。Gmail metadata 权限不足以支持邮件正文分析。`gmail.readonly` 属于 restricted scope，公开服务需要按 Google 要求处理验证与适用的安全评估，产品发布计划必须包含这项接入工作。见 [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)、[Calendar scopes](https://developers.google.com/workspace/calendar/api/auth)。本地工作区不需要登录 Token；连接私人 Google 数据仍需要 Google 自身的 OAuth 授权。

## 同步、去重与故障恢复

- Gmail：建立 `historyId` 基线，通过 `history.list` 获取增量，再按任务范围读取邮件正文。历史过期返回 404 时做有界重新同步，保留已处理 message ID，避免重复通知。见 [Gmail 同步指南](https://developers.google.com/workspace/gmail/api/guides/sync)。
- Calendar：初始分页同步后保存 `nextSyncToken`；后续使用固定查询条件增量同步，处理删除事件，令牌失效（410）时重新同步。事件以日历 ID + event ID 标识，按更新时间识别修改。见 [Calendar 同步指南](https://developers.google.com/workspace/calendar/api/guides/sync)。
- Gmail push 通过 Pub/Sub 通知变化，使用 history 再获取实际数据；watch 需要续期。Calendar push 通知也需要重新查询数据，且 channel 需更新。见 [Gmail push](https://developers.google.com/workspace/gmail/api/guides/push)、[Calendar push](https://developers.google.com/workspace/calendar/api/guides/push)。推送只作为“有变化”的提示，不直接当成完整邮件或日历事件。
- 每次完整分页的变化先持久化到同步 inbox，原子保存游标；模型消费 inbox 时再创建 analysis run。模型失败不得让取得的数据消失，也不阻塞 Connector 继续同步。
- 幂等键：同步记录按 connection/resource/version 去重；运行按 task/scheduled occurrence 去重；提醒按 task/source version/condition 去重。重试复用同一键。多个任务可以分析同一邮件，账号游标不能被一个任务推进后导致其他任务漏数据。
- OAuth 失效显示“需要重新连接”，暂停相关任务调用，不自动循环重试登录。429 尊重 Retry-After；临时 5xx 指数退避；错误记录不保存 token 或完整正文。
- 用户断开账号后撤销/删除凭证，停止订阅、暂停相关任务，拒绝已排队任务的后续读取。授权回调绑定单次 state、用户/工作区和固定重定向地址；账号连接不依赖 Agent 自己操作登录页面。

## 最小数据与模块扩展

沿用 Python API、Scheduler、Worker 和 SQLite，不新增工作流平台。

- `connections`：工作区、provider、账号显示名、授权 scopes、credential_ref、状态、最近成功同步时间。
- `connector_cursors`：connection + resource 的同步游标；独立于任务调度状态。
- `connector_changes`：资源 ID、版本、有限内容引用、来源时间、消费状态；可设置保留期限。
- `agent_tasks`：原对话、指令、connection IDs、过滤范围、schedule、时区、预算、状态、next_run_at。
- `agent_task_runs`：计划发生时间、执行租约、同步批次、状态、结果、错误、耗时、模型用量。
- 通知继续复用现有通知/回调模块，用唯一键关联 run 与原对话。后端 completion 事件先落库再投递，不能仅依赖浏览器 SSE。

建议模块位置：`modules/connectors/` 管连接、OAuth 与 provider 适配；`modules/tasks/` 增加 Agent 任务定义与运行；`modules/agent/` 提供前后台共享执行入口；`entrypoints/worker.py` 按任务类型分派，不将所有任务都解析为 `AnalysisInput`。保留已有快照分析类型，不做破坏性替换。

后台与前台对话不能竞争同一 `active_run`。后台以任务的有界上下文运行，把结果作为独立消息事件追加到原对话；下一轮前台对话加载该结果。按任务设置超时、最大工具数和模型预算，预算失败仍记录运行状态。

## 必要产品能力

除了任务与 Connector，首版补齐三个小而关键的能力：

1. **连接状态**：Google 是否已连接、可以读哪些数据、最近同步是否成功，以及断开入口。通过聊天连接卡片进入，后续可有简洁“连接”列表，不恢复独立导入分析页面。
2. **任务可观察性**：下次运行、上次成功、最近结果、暂停/恢复、错误与重新连接提示。任务卡片内直接操作。
3. **可追溯提醒**：提醒说明为什么触发，链接原邮件/日历，并显示数据时间与具体建议。通知去重、每日汇总和用户指定的免打扰时段避免刷屏。

邮件、网页、附件都是不可信内容；其中的命令不能改变任务、授权或读取别的账号。模型只见实现当前任务必需的内容。写入邮件和日历、附件执行、跨账号操作不包含在首版只读任务能力中。

## 第一阶段验收场景

使用合成 mailbox/calendar 测试同步、分页、重复通知、历史过期、删除事件、OAuth 失效、429 与模型失败；之后由用户授权专用 Google 测试账号进行真实接入验收。

闭环演示：连接账号 → 在聊天创建任务 → 关闭网页 → 测试账号收到邮件 → 后台取得新增内容 → Pi 总结 → 对话/通知持久保存 → 重新打开页面看到结果 → 第二次调度不重复提醒。桌面容器数量不增加。完成这个闭环后，再拓展 Drive、Sheets 和其他生态。
