# Nori

[English](README.md) · [简体中文](README.zh-CN.md)

一个受 **ChatGPT dots** 启发、可自行部署的持续工作助手：在对话里交代工作，
连接所需工具，让后台任务执行并带回结果。聊天、任务与可选 Linux 桌面在同一个工作区中使用。

当前聚焦**个人日常工作的持续跟进**：邮件摘要、日历提醒和周期检查。
Finance / crypto 工具作为可选扩展场景。本地目录和内部标识暂沿用 `finance-agent`，兼容已有安装。

**交代工作，让 Nori 持续跟进。**

**本地 Alpha · Apache-2.0 · Python + Pi Agent Core + MCP**

![Nori 对话工作区与 Linux 桌面](docs/assets/workspace.png)

*截图来自真实应用界面和隔离的虚构数据工作区。价格及回复仅用于演示，没有连接个人账号。*

## 核心使用方式

1. **在对话中交代一项持续工作**：例如每天汇总邮件和日程，或在日历事项开始前提醒。
2. **连接需要的数据源**：目前支持 Gmail、Google 主日历；管理员可通过 stdio MCP 配置其他工具。
3. **交给后台执行**：保存的任务按一次性、间隔或每日时间运行。浏览器可以关闭，API、Worker 和 Scheduler 需要保持在线。
4. **查看带回的结果**：在对话和提醒收件箱中查看，或接收可选 Telegram 通知与签名 Webhook。

任务由用户提出后创建。新安装和连接 Google 都不会自动添加周期任务。
Google 与交易所查询均为只读。

## 主要对齐 ChatGPT dots

主要产品参考是 [ChatGPT dots](https://learn.chatgpt.com/docs/dots)：通过对话交代工作，
连接工具，在后台持续推进，再把结果带回给用户。本项目采用 Pi Agent Core 和本地后端，
独立实现其中一部分体验，与 OpenAI 无隶属关系。

当前的持久能力包括对话记录、偏好、定时任务和执行结果。
**自主规划长期目标、通用跨对话记忆、自主决定何时唤醒、主动研究、双向消息渠道尚未实现。**
目前是本地 Alpha，未达到 dots 的完整能力；运行主机或后台服务离线后，任务也会停止。
方向与差距见 [产品方向](docs/product-direction.md)。

## 当前可用能力

- **聊天与工具**：流式回复、工具活动、持久对话，基于 Pi Agent Core 和管理员配置的 stdio MCP。
- **后台任务与结果投递**：一次性、间隔和每日任务，持久执行，提醒收件箱，可选 Telegram 和签名 Webhook。
- **Google 只读连接**：搜索和读取 Gmail、查看主日历，用于用户指定的摘要、变化监控和会前提醒。
- **可选 Linux 桌面**：按需启动 Debian / XFCE，包含 Chromium、LibreOffice、PDF 阅读器和文件工具；用户可直接操作，视觉模型可使用截图和桌面工具，镜像预配置 Chrome DevTools MCP。
- **可选 Finance 工具**：Binance / OKX 官方 CLI 只读查询、导入资产快照的确定性计算，作为扩展能力展示。

## 快速开始

需要 **Python 3.12+、uv、Node 22.19+**。聊天和任务不需要 Docker；Linux 桌面需要 Docker。
统一启动脚本支持 macOS / Linux。

Clone 仓库并配置本地模型密钥：

```sh
git clone https://github.com/xlabsg/nori.git
cd nori
cp .env.example .env
# 在本地编辑 .env，填写 DEEPSEEK_API_KEY，或配置 Anthropic。
uv run python scripts/dev.py
```

打开 **http://127.0.0.1:8767**。侧栏语言选项支持 English / 简体中文切换，偏好保存在当前浏览器。脚本会安装缺失的 Pi 运行时依赖、初始化数据库，
并启动 API、Worker 和 Scheduler；Ctrl+C 一起停止。端口被占用时用 `--port 8768`，
用 `--data-dir` 可指定独立的数据库和配置目录；脚本不会替换已有服务。

`.env` 只加载已列出的模型与 Google 配置，进程环境变量优先。
模型对话需要密钥，确定性计算和虚构预览不需要。Anthropic 可配置
`PI_PROVIDER=anthropic`、`ANTHROPIC_API_KEY`；`PI_MODEL` 可选择支持的模型。
Agent 操作桌面需要视觉模型。不要在聊天、截图或提交记录中填写密钥。

可选：构建桌面镜像。

```sh
docker build -t finance-agent-desktop:local infra/desktop
```

桌面镜像默认使用英文（`en_US.UTF-8`），包括应用入口和 Chromium 欢迎页。
在对话右侧点击 **启动桌面**。构建镜像不会启动容器。
详见 [Linux 桌面](docs/desktop.md)。Google OAuth 和 Telegram 都需要自己的配置，
见 [Google 接入](docs/google-setup.md) 和 [任务与提醒](docs/proactive-assistant.md)。

## 无凭证演示

```sh
uv run python scripts/demo.py
uv run python scripts/dev.py --port 8768 --data-dir .runtime/demo
```

演示只在**独立数据库**中保存一段明确标注的虚构对话，不调用模型、不连接账号、
不创建后台任务。演示目录已存在时，请使用新的 `--data-dir`。
启动这个演示对话的可选桌面即可复现截图；继续与模型对话仍需配置密钥。

连接自己的账号后，可以尝试：

> “汇总我的未读邮件和今天的日程。”  
> “每天 8:30 汇总我的邮件和日程。”  
> “在日历事项开始前 10 分钟提醒我。”

## 架构与范围

```text
对话工作区 → FastAPI / SQLite → Pi Agent Core → 工具 / stdio MCP
                    ↓
             Scheduler + Worker → 结果 / 提醒 / Telegram / Webhook
                    ↓
             可选 Docker Linux 桌面
```

API、Worker、Scheduler 共享同一个 Python 包，Pi 在每轮对话的 Node 子进程里运行。
SQLite 保存对话、任务、结果和投递状态。Google 和 Telegram 凭证在本地加密保存，
加密密钥位于仓库之外。外部邮件、网页和文件作为数据处理。

当前是**单用户本地原型**，默认绑定本机且无需工作区登录，请勿直接暴露公网。
生产认证、多用户托管隔离、远程服务器 Runner、外部异步分析尚未实现。
MCP 目前支持管理员配置的 stdio tools，不支持远程 OAuth Connector。
日历读取主日历；导入快照的周期分析重复分析固定快照，不代表实时资产监控。

`.env*`、`.runtime/` 已忽略，只提交占位配置示例。不要提交账号数据、数据库或日志。
详见 [安全说明](SECURITY.md)。

## 开发与文档

```sh
uv sync --locked
npm ci --prefix services/agent-runtime --ignore-scripts
npm ci --prefix apps/web --ignore-scripts
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
npm run check --prefix services/agent-runtime
npm test --prefix services/agent-runtime
npm test --prefix apps/web
uv run python scripts/check-secrets.py
```

默认测试不需要外部凭证，Docker 集成测试按需开启；GitHub Actions 在 push 和 PR 时
运行常规检查。密钥模式扫描是基础发布检查，不替代完整审计。

| 文档 | 内容 |
| --- | --- |
| [Agent 运行时](docs/agent-runtime.md) | Pi、模型、MCP 与工具边界 |
| [任务与提醒](docs/proactive-assistant.md) | Google 监控、偏好、Telegram 和常驻服务 |
| [交易所接入](docs/exchanges.md) | 按需安装 CLI、只读查询 |
| [Linux 桌面](docs/desktop.md) | 镜像与 Browser / Computer Use |
| [目录结构](docs/repository-layout.md) | 模块职责 |
| [产品方向](docs/product-direction.md) | Dots 对标、当前重点与能力差距 |
| [设计](docs/design.md) / [路线图](docs/roadmap.md) | 历史 Finance 调研与暂缓能力 |
| [贡献指南](CONTRIBUTING.md) / [版本记录](CHANGELOG.md) | 开发规范与发布说明 |

服务启动后可访问 `/docs` 查看 API。设计文档包含规划，不代表全部能力已经实现。

## 许可证

[Apache License 2.0](LICENSE)。归属声明见 [NOTICE](NOTICE) 和
[第三方许可说明](THIRD_PARTY_NOTICES.md)；依赖及桌面软件保留各自许可证。
