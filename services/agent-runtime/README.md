# Pi Agent Runtime

Node >= 22.19.0。采用锁定版本的 Pi Agent Core、pi-ai 与官方 MCP SDK。Python API 每轮启动 `src/cli.ts`，通过 NDJSON stdio 发送上下文并处理本地工具调用；独立运行 npm start 时仍须由宿主提供此协议。

`npm run check` 与 `npm test` 验证类型、真实 Pi 工具循环和本地 MCP。`test/fixture-runtime.ts` 仅用于测试模拟 provider，生产 CLI 不接收模拟配置。模型和 MCP 配置见 ../../docs/agent-runtime.md。
