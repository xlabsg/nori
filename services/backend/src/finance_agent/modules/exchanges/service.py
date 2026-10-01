"""Read-only operations over official CLIs. Secrets are never sent to Pi or the desktop."""

import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from finance_agent.modules.analytics.schemas import StrictModel


class ExchangeQuery(StrictModel):
    exchange: Literal["binance", "okx"]
    operation: Literal[
        "ticker", "orderbook", "candles", "funding_rate", "balances", "positions", "history"
    ]
    symbol: str = Field(default="", max_length=40, pattern=r"^[A-Z0-9][A-Z0-9-]*$|^$")
    interval: Literal["1m", "1h", "1d"] = "1h"
    limit: int = Field(default=10, ge=1, le=50)


ENV_NAMES = {
    "binance": ("BINANCE_API_KEY", "BINANCE_SECRET_KEY"),
    "okx": ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE"),
}


class ExchangeService:
    def __init__(self, root):
        self.root = root

    def executable(self, exchange):
        if exchange == "okx":
            cli = (
                self.root
                / "services/exchange-tools/node_modules/@okx_ai/okx-trade-cli/dist/index.js"
            )
            return [shutil.which("node") or "node", str(cli)] if cli.is_file() else None
        matches = sorted((self.root / ".runtime/exchange-bin").glob("*/binance-cli"))
        return [str(matches[0])] if matches else None

    def config(self, tenant, exchange):
        path = self.root / ".runtime/exchanges.json"
        data = json.loads(path.read_text()) if path.exists() else {}
        return data.get("tenants", {}).get(tenant, {}).get(exchange, {})

    def credentials(self, tenant, exchange):
        config = self.config(tenant, exchange)
        mapping = config.get("credentials_env", {})
        # Environment references are admin configuration, never model arguments.
        result = {name: os.environ.get(mapping.get(name, ""), "") for name in ENV_NAMES[exchange]}
        if not all(result.values()):
            raise ValueError("This exchange has no credentials configured for this tenant")
        return result

    def inventory(self, tenant):
        result = []
        for exchange in ENV_NAMES:
            try:
                self.credentials(tenant, exchange)
                configured = True
            except ValueError:
                configured = False
            result.append(
                {
                    "exchange": exchange,
                    "installed": self.executable(exchange) is not None,
                    "credentials_configured": configured,
                    "mode": "read_only",
                    "public_market_data_requires_key": False,
                }
            )
        return result

    @staticmethod
    def arguments(request):
        operation, symbol, limit = request.operation, request.symbol, str(request.limit)
        if operation in {"ticker", "orderbook", "candles", "funding_rate"} and not symbol:
            raise ValueError("An exchange-native instrument symbol is required")
        if request.exchange == "okx":
            if operation in {"ticker", "orderbook", "candles", "funding_rate"}:
                action = {"funding_rate": "funding-rate"}.get(operation, operation)
                args = ["--json", "market", action, symbol]
                if operation == "orderbook":
                    args += ["--sz", limit]
                if operation == "candles":
                    args += [
                        "--bar",
                        {"1m": "1m", "1h": "1H", "1d": "1D"}[request.interval],
                        "--limit",
                        limit,
                    ]
            else:
                args = [
                    "--json",
                    "account",
                    {"balances": "balance", "positions": "positions", "history": "bills"}[
                        operation
                    ],
                ]
                if operation == "history":
                    args += ["--limit", limit]
                if operation == "positions" and symbol:
                    args += ["--instId", symbol]
            return args
        if operation == "balances":
            return ["spot", "get-account"]
        if operation == "positions":
            return ["futures-usds", "position-information-v3"] + (
                ["--symbol", symbol] if symbol else []
            )
        if operation == "history" and not symbol:
            raise ValueError("Binance trade history requires a symbol")
        args = [
            "futures-usds" if operation == "funding_rate" else "spot",
            {
                "ticker": "ticker-price",
                "orderbook": "depth",
                "candles": "klines",
                "funding_rate": "get-funding-rate-history",
                "history": "my-trades",
            }[operation],
            "--symbol",
            symbol,
        ]
        if operation in {"orderbook", "candles", "funding_rate", "history"}:
            args += ["--limit", limit]
        if operation == "candles":
            args += ["--interval", request.interval]
        return args

    @staticmethod
    def project(data, exchange, operation):
        if operation not in {"balances", "positions", "history"}:
            return data
        fields = {
            "balances": {
                "asset",
                "free",
                "locked",
                "ccy",
                "eq",
                "cashBal",
                "availBal",
                "frozenBal",
            },
            "positions": {
                "symbol",
                "positionAmt",
                "entryPrice",
                "markPrice",
                "unRealizedProfit",
                "positionSide",
                "instId",
                "instType",
                "pos",
                "posSide",
                "avgPx",
                "upl",
                "margin",
                "mgnMode",
            },
            "history": {
                "symbol",
                "price",
                "qty",
                "quoteQty",
                "commission",
                "commissionAsset",
                "time",
                "isBuyer",
                "isMaker",
                "ts",
                "ccy",
                "balChg",
                "pnl",
                "fee",
                "type",
                "subType",
            },
        }[operation]
        if exchange == "binance" and operation == "balances":
            data = data.get("balances", [])
        if exchange == "okx" and operation == "balances":
            data = [detail for account in data for detail in account.get("details", [])]
        if not isinstance(data, list):
            raise ValueError("Unexpected private account response format")
        return [{key: value for key, value in row.items() if key in fields} for row in data[:200]]

    def query(self, tenant, request):
        executable = self.executable(request.exchange)
        if not executable:
            raise ValueError("Exchange CLI not installed; use the documented installer")
        args = self.arguments(request)
        private = request.operation in {"balances", "positions", "history"}
        credentials = self.credentials(tenant, request.exchange) if private else {}
        config = self.config(tenant, request.exchange)
        with tempfile.TemporaryDirectory(prefix="finance-exchange-") as home:
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": home,
                "XDG_CONFIG_HOME": home,
                "OKX_UPDATE_CHECK": "false",
                "OKX_TIMEOUT_MS": "15000",
                "LANG": "C.UTF-8",
                **credentials,
            }
            if request.exchange == "okx" and config.get("demo", False):
                environment["OKX_DEMO"] = "true"
            try:
                result = subprocess.run(
                    [*executable, *args],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise ValueError("Exchange CLI unavailable or timed out") from None
            if result.returncode or len(result.stdout) > 200000:
                # Never return raw CLI errors or verbose output that could include credentials.
                raise ValueError(
                    "Exchange query failed; check availability, credentials and permissions"
                )
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                raise ValueError("Exchange CLI did not return structured JSON") from None
            if request.exchange == "okx" and isinstance(data, dict) and "code" in data:
                if str(data["code"]) != "0":
                    raise ValueError("Exchange rejected the query")
                data = data["data"]
            data = self.project(data, request.exchange, request.operation)

            def redact(value):
                if isinstance(value, dict):
                    return {k: redact(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [redact(v) for v in value]
                if isinstance(value, str):
                    for secret in credentials.values():
                        if secret:
                            value = value.replace(secret, "[redacted]")
                return value

            return {
                "exchange": request.exchange,
                "operation": request.operation,
                "source": "official_exchange_cli",
                "observed_at": datetime.now(UTC).isoformat(),
                "data": redact(data),
                "mode": "read_only",
            }
