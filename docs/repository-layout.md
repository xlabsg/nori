# 文件目录设计

当前仓库已实现第一阶段本地原型，包含 Web 工作台、Python API、Worker、Scheduler、SQLite 迁移和核心测试。目录树描述整体模块边界；未实现模块仍仅有说明文件。

```text
finance-agent/
├── README.md
├── AGENTS.md
├── .gitignore
├── docs/
│   ├── design.md                    # 完整产品与技术设计
│   └── repository-layout.md         # 目录与模块边界
├── apps/
│   ├── web/                        # TypeScript Web 前端
│   └── runner/                     # 用户服务器上的独立执行程序
│       ├── src/finance_runner/
│       └── tests/
├── services/
│   └── backend/                    # 同一后端包，多个进程入口
│       ├── src/finance_agent/
│       │   ├── entrypoints/        # api、worker、scheduler 启动
│       │   ├── modules/
│       │   │   ├── identity/       # 用户、租户、连接授权
│       │   │   ├── agent/          # 对话与目标编排
│       │   │   ├── memory/         # 偏好、长期笔记与更正
│       │   │   ├── tasks/          # 运行状态、检查点、事件
│       │   │   ├── monitors/       # 定时、事件和阈值触发
│       │   │   ├── notifications/  # 提醒、收件箱、降噪
│       │   │   ├── callbacks/      # 入站回调与出站 Webhook
│       │   │   ├── data/           # 数据接入、快照、资产与证据
│       │   │   ├── analytics/      # 金融计算与外部分析
│       │   │   ├── research/       # 研究卡、决策记录与报告
│       │   │   ├── execution/      # Browser、Desktop、Runner
│       │   │   ├── policy/         # 各路径共用的权限和预算检查
│       │   │   └── usage/          # 成本、用量与配额
│       │   └── adapters/           # 数据库、队列、LLM 和工具集成
│       ├── migrations/             # 唯一数据库迁移目录
│       └── tests/
├── packages/
│   └── contracts/                  # 任务、回调、分析和 Runner 消息协议
├── infra/                          # 构建、本地运行、部署与观测配置
├── scripts/                        # 开发工具的薄封装
└── examples/                       # 使用虚构数据的配置示例
```

## 模块组织规则

每个业务模块实现时按实际需要添加 models.py、service.py、schemas.py 和 routes.py。没有该职责就不建文件；不要求所有模块套相同模板。

entrypoints 只启动进程和装配依赖。Worker、Scheduler 与 API 调用同一业务服务，不分别维护状态机或金融计算。模块之间通过公开服务接口协作，适配器不自行修改其他模块业务状态。

tasks 拥有运行状态和持久事件；monitors 负责何时触发；callbacks 负责传输、认证与去重；notifications 负责向人展示与投递。回调接收成功、任务完成、用户看到结果是不同状态。

data 保存资产身份、快照、数据质量与来源；analytics 使用固定数据版本进行确定性计算；research 保存论点、证据与报告。agent 负责选择和协调这些能力，不能用模型输出替代财务计算。

execution 管理执行环境和租约；adapters 对接具体浏览器、桌面和服务器 Runner。policy 在所有路径上执行统一限制。人工接管暂停 agent 的操作权限，归还后重新检查状态。

apps/runner 独立安装并有自己的进程与测试，不导入后端业务包。只共享消息协议，避免用户服务器必须安装全部后端依赖。

## 后续源码位置

| 能力 | 计划文件位置 |
| --- | --- |
| API、Worker、Scheduler 入口 | services/backend/src/finance_agent/entrypoints/api.py、worker.py、scheduler.py |
| 任务状态与事件 | modules/tasks/service.py、models.py |
| 入站分析回调 | modules/callbacks/routes.py、service.py |
| Webhook 投递与重试 | modules/callbacks/delivery.py |
| 提醒规则与检测 | modules/monitors/service.py、rules.py |
| 消息渠道投递 | modules/notifications/delivery.py；adapters/notification_channels/ |
| 数据连接器 | adapters/data_sources/ |
| 确定性金融计算 | modules/analytics/calculations.py，复杂后再按口径拆分 |
| 外部异步分析 | adapters/analysis_services/ |
| Browser 与 Desktop | adapters/browser/、adapters/desktop/ |
| Runner 协议客户端 | adapters/runner/ |
| 服务器执行程序 | apps/runner/src/finance_runner/main.py、executor.py、heartbeat.py |
| 任务与回调消息 | packages/contracts/schemas/task-event.schema.json、callback.schema.json |
| 分析与执行消息 | packages/contracts/schemas/analysis.schema.json、runner-job.schema.json |
| 前端页面 | apps/web/src/ 下的路由、组件与 API 客户端，按所选框架生成 |

表中为完整产品的计划位置，只有部分已实现，具体进度见 implementation-status.md。Python 依赖和锁文件已生成；容器、CI、TypeScript 构建及远程执行后续加入。

## 测试安排

后端 tests 按 unit、integration、contracts 分组。重点验证现金流与收益、租户隔离、任务恢复、回调去重与乱序、提醒冷却和预算限制。Runner 验证租约失效、断线恢复、取消及产物回传。Web 后续加入任务启用、提醒查看、接管和撤销授权的流程测试。

首个实现闭环按任务状态与事件、静态数据分析、回调与提醒、真实数据连接器、浏览器与 Runner 的顺序推进。

## 已落地的对话运行时

新增 `services/agent-runtime/`（Pi Core、pi-ai、MCP、TypeScript 构建检查与测试）。Python `modules/agent/service.py` 管理会话及 stdio，`tools.py` 调用原有业务服务。前端 `apps/web/chat.js` 展示流式对话与任务卡。原有 API、Worker、Scheduler 无需引入新常驻服务。完整说明见 [agent-runtime.md](agent-runtime.md)。
