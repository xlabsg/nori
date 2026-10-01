# Shared contracts

跨进程和跨语言的协议定义：TaskEvent、CallbackEnvelope、AnalysisRequest、AnalysisResult、RunnerJob、RunnerHeartbeat、ArtifactManifest。

计划用 JSON Schema 管理这些消息，生成或验证 Python 与 TypeScript 类型。普通 Web REST 接口由后端生成 OpenAPI；不手工维护第二份相同定义。

协议包含版本、事件身份、租户、运行与配置版本。示例只能使用虚构数据。当前尚无协议实现。
