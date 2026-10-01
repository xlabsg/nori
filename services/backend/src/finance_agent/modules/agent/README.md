# agent

`service.py` 管理认证租户下的持久会话、单轮运行租约、请求去重和 Node Pi stdio 桥接。`tools.py` 将本地财务与任务能力注册为受限工具。真正的模型与工具循环位于 services/agent-runtime。长期记忆、后台自动续跑和自主研究尚未实现。
