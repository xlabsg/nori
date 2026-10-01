# Web application

同源对话工作台，无构建步骤。`app.js` 管理工作区自动连接、快照导入、任务和提醒；`chat.js` 管理历史对话、NDJSON 回复流、工具活动与关联任务卡。无需工作区凭证，用户消息使用 textContent；助手回复通过本地 markdown-it 渲染，禁用原始 HTML、远程图片和危险链接。周期变更需要本轮显式授权。

模型与最终授权在服务端处理。TypeScript 前端框架、生产级的接管锁与任务恢复后续接入。

界面以对话和底部输入框为主，任务、提醒和数据导入放在弹窗中。右侧展示平台自动分配的真实 Linux 图形桌面；`desktop.js` 自动连接，`desktop-view.html` 通过 noVNC RFB 显示画面并提供鼠标键盘。用户不配置执行镜像，不提供独立终端入口；脚本执行保留为 Agent 内部工具。见 `docs/desktop.md`。

工作区无需凭证或登录。页面加载自动连接本地 API 和默认桌面；重连按钮直接连接，无授权弹窗。验证：`node --test apps/web/tests/*.test.cjs`。

回复显示：提交问题立即出现等待卡片、旋转指示和已等待秒数；工具执行时显示当前阶段，收到回复后转为 Markdown 内容。表格、列表、加粗、链接和代码块支持流式输出与历史回看；停止和失败清理等待卡片。解析器固定版本见 `package-lock.json` 和 `vendor/README.md`。
