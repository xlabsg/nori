# Scripts

只放开发初始化、检查、协议生成等薄封装脚本。任务执行、回调重试和金融计算应在业务模块中实现，不放在临时脚本里。

`uv run python scripts/install-exchange.py binance|okx` 按需安装固定版本官方交易所 CLI，详见 `docs/exchanges.md`。安装仅由用户或管理员执行，不是 Agent 工具。

- `uv run python scripts/dev.py`：统一启动本地 API、Worker、Scheduler，退出时一起停止。
- `uv run python scripts/demo.py`：只在独立目录写入虚构演示对话，不连接账号、不创建任务。
- `uv run python scripts/check-secrets.py`：扫描 Git 发布候选文件中的已知密钥模式，只报告路径和类型。
