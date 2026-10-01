# 主动助手：邮件、日程和通知

当前支持对话创建持久任务、后台分析 Google 数据、写回原对话和站内通知。Finance 是首个专业场景，任务和连接能力通用。保持只读 Google 权限。

## 任务创建与使用

任务由用户通过对话明确交代，或主动调用任务创建 API 添加。连接账号、启动后台服务和安装应用不会自动创建用户任务。Scheduler 只调度已有任务，Worker 只执行已有运行记录。

使用示例：「每天北京时间 8:30 汇总邮件和日程」「每 15 分钟检查重要新邮件」「会议开始前 10 分钟提醒」。这些是用户主动创建任务的示例，不会随应用安装或账号连接自动启用。

任务卡支持立即检查、暂停、恢复、取消与执行记录。即时执行复用已有排队/运行任务，不改变每日计划。时区或提前量可通过对话修改任务。

## Telegram

打开工作区「连接」→「Telegram」→「配置 Telegram」，填写项目专用 Bot token 和数字 chat ID。先向自己的 bot 发送 `/start`。保存后点击「发送测试通知」，Worker 将按免打扰设置发送。

凭证使用现有 CredentialVault 加密保存；不写入聊天、前端存储、日志或 Git。状态接口不返回 token 和 chat ID。配置只负责发送通知，不消费 Telegram 更新，不把收到的消息当作 Agent 指令。

任务结果与通知队列在同一事务中落库。外部发送最多尝试 5 次，429 采用服务端退避信息，永久权限错误直接失败。更换或断开 Telegram 取消旧配置尚未发送的队列；配置前的历史通知不会自动补发。摘要超过消息容量时明确标注截断，完整结果保存在原对话。网络超时或发送成功后本地进程退出时存在重复投递可能，不能把 Telegram 通道描述为 exactly-once。

## 提醒偏好

在「连接」→「提醒偏好」保存时区、免打扰时段、重点联系人与关注条件；也可以明确要求 Agent 记住偏好。偏好按工作区隔离，在前台对话和后台分析中使用。

免打扰只延后 Telegram，站内通知即时保存；结束时发送待投递提醒。默认免打扰关闭。时区偏好影响后续对话设定和外部通知；已创建任务的计划时区需单独修改，避免静默变更。

## 会议提前提醒

`calendar_reminder` 任务每 60 秒读取未来 24 小时的主日历，按开始时间和 `reminder_minutes` 判断，直接生成提醒，不调用模型。默认提前 10 分钟，触发精度受轮询和服务在线状态影响。

按任务、事件 ID、开始时间持久去重，提醒标记与消息在同一事务提交。未触发的改期和取消在下一次检查中生效；已提醒事件改期到另一个开始时间后允许再次提醒。跳过全天事件和已开始事件；不补发已经结束的会议。长时间离线期间无法保证准时提醒。首次查询与周期错误会显示在任务卡。

创建示例：「会议开始前 10 分钟提醒我。」对应 calendar-only、60 秒 interval。修改示例：「把会议提醒提前量改为 5 分钟。」

## 邮件查询和全文

- `google_read`：最近 24 小时收件箱和当天日历，返回有界预览及覆盖标记。
- `google_search_mail`：未读、发件人邮箱、带时区的日期范围，最多 50 封；`has_more` 明确表示还有匹配数据。
- `google_mail_detail`：按 message ID 分段读取明文，每段 4000 字符；通过 `next_offset` 继续直到末尾。支持明文和 HTML 正文提取；若只能取得 Google 短摘要，`text_source=snippet` 明确表示全文不可用。不读取附件、不改已读状态、不发送邮件。

后台分析遇到较大内容时缩短正文并说明预览覆盖，仍保留事件与来源链接；超出最终容量记录可见失败，不伪装成无邮件。

## macOS 常驻服务

安装前完成 `uv sync`、数据库迁移和 Agent Runtime 安装。停止同端口手动启动的旧实例后运行：

```sh
uv run python scripts/background-services.py install --model-env /absolute/path/to/private-model.env
uv run python scripts/background-services.py status
uv run python scripts/background-services.py restart
uv run python scripts/background-services.py uninstall
```

安装当前用户的三个 LaunchAgent：API、Worker、Scheduler，登录后启动，异常退出自动恢复。plist 只含程序路径和私有 env 路径，不含密钥。日志位于忽略提交的 `.runtime/services/`。这些是用户登录服务，关机、睡眠或退出用户会话期间不会执行；需要真正全天在线时再部署到常驻服务器。

「任务与提醒」展示 Worker/Scheduler 心跳健康，任务卡展示最近运行、下一次计划和错误；`/healthz` 只表示 API/数据库可用，不替代后台心跳。

## 验收

真实账号已验证 Google 读取 → 后台 Pi 摘要 → 原对话/站内通知，以及一条新增 Gmail 数据触发提醒、后续零新增不再次通知。实际终止 Worker 后由 launchd 自动恢复，页面关闭不影响后台进程。

合成测试覆盖会议触发/改期/取消/全天事件/去重、跨租户隔离、免打扰、Telegram 429 重试和凭证更换/断开、手动执行去重及消息正文分段。没有在真实日历创建事件或发送测试邮件。Telegram 接口与队列已完成，真实 Telegram 投递仍需项目专用凭证。

实现参考：[Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)、[Calendar events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)、[Gmail messages.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)。
