# 交易所 CLI 接入

Pi 调用 `exchange_connections` 查看本租户接入状态，调用 `exchange_query` 查询数据。后端通过固定参数执行官方 CLI，不向模型提供任意 CLI 命令或安装权限。当前已接入 Binance CLI 2.1.1 和 OKX Trade CLI 1.4.8。行情、订单簿、K 线、资金费率为公共查询；余额、持仓、历史需要租户凭证。当前接口均只读，没有下单、撤单、转账能力。

## 按需安装

在仓库根目录执行，只安装指定交易所，不修改全局 CLI：

```sh
uv run python scripts/install-exchange.py binance
uv run python scripts/install-exchange.py okx
```

Binance 下载固定官方发布并校验仓库固定 SHA256，支持 macOS/Linux ARM64/x86_64。OKX 使用已提交的 npm lockfile 执行 `npm ci --ignore-scripts`。扩展交易所时增加固定适配和操作白名单，不能只把任意命令交给模型。

## 后端账户配置

复制 `examples/exchanges.example.json` 为被 Git 忽略的 `.runtime/exchanges.json`。当前本地工作区使用 `local`；每个交易所 `credentials_env` 只保存环境变量名称，真实值由服务启动环境注入。采用交易所只读权限的密钥；OKX 示例默认模拟盘，实盘查询需要管理员显式将 `demo` 设为 `false`。不要把密钥发到 chatbox、MCP 参数、Linux 桌面或 Git。

服务只向一次 CLI 进程传入当前租户、当前交易所的必要凭证，并使用临时 HOME 避免读取用户全局 CLI 配置。私有查询响应去掉账户和订单 ID，只把选定财务字段送给模型分析。当前未配置用户真实交易所账户，因此私有查询尚未实测。

API：`GET /api/exchanges`、`POST /api/exchanges/query` 默认使用 `local` 工作区，无需工作区 Token。请求例：

```json
{"exchange":"okx","operation":"ticker","symbol":"BTC-USDT"}
```

Binance 使用 `BTCUSDT`；OKX 现货 `BTC-USDT`，永续 `BTC-USDT-SWAP`。查询失败返回不可用，不能当作余额为零。响应包括交易所、操作、UTC 观测时间、只读模式、来源和数据。财务计算仍由确定性分析模块完成，不能把报价当成交价。当前会话会持久化所选返回数据；这仍是本地原型，没有生产级加密和账户授权管理。

官方来源：[Binance CLI](https://github.com/binance/binance-cli)、[OKX Agent Trade Kit](https://github.com/okx/agent-trade-kit)。
