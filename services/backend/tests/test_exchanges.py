import json
import subprocess

import pytest
from pydantic import ValidationError

from finance_agent.modules.exchanges.service import ExchangeQuery, ExchangeService


def test_private_credentials_are_tenant_scoped_and_never_use_global_cli_profile(
    tmp_path, monkeypatch
):
    service = ExchangeService(tmp_path)
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime/exchanges.json").write_text(
        json.dumps(
            {
                "tenants": {
                    "a": {
                        "binance": {
                            "credentials_env": {
                                "BINANCE_API_KEY": "A_KEY",
                                "BINANCE_SECRET_KEY": "A_SECRET",
                            }
                        }
                    }
                }
            }
        )
    )
    monkeypatch.setenv("A_KEY", "fixture-key")
    monkeypatch.setenv("A_SECRET", "fixture-secret")
    monkeypatch.setenv("BINANCE_API_KEY", "unrelated-global-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unrelated-model-key")
    monkeypatch.setattr(service, "executable", lambda exchange: ["fixture-cli"])
    calls = []

    def run(argv, **kwargs):
        env = kwargs["env"]
        calls.append(argv)
        assert env["BINANCE_API_KEY"] == "fixture-key"
        assert env["BINANCE_SECRET_KEY"] == "fixture-secret"
        assert "A_KEY" not in env and "DEEPSEEK_API_KEY" not in env
        assert env["HOME"] == env["XDG_CONFIG_HOME"]
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "accountId": "private-id",
                    "balances": [
                        {"asset": "BTC", "free": "1", "locked": "0", "accountId": "private-id"}
                    ],
                }
            ),
            "",
        )

    monkeypatch.setattr(subprocess, "run", run)
    request = ExchangeQuery(exchange="binance", operation="balances")
    with pytest.raises(ValueError, match="no credentials"):
        service.query("b", request)
    assert calls == []
    result = service.query("a", request)
    assert result["data"] == [{"asset": "BTC", "free": "1", "locked": "0"}]
    assert calls == [["fixture-cli", "spot", "get-account"]]


def test_public_query_has_no_secrets_and_cli_errors_are_sanitized(tmp_path, monkeypatch):
    service = ExchangeService(tmp_path)
    monkeypatch.setattr(service, "executable", lambda exchange: ["fixture-cli"])
    monkeypatch.setenv("OKX_API_KEY", "fixture-secret")

    def run(argv, **kwargs):
        assert "OKX_API_KEY" not in kwargs["env"]
        assert argv == ["fixture-cli", "--json", "market", "ticker", "BTC-USDT"]
        return subprocess.CompletedProcess(argv, 1, "fixture-secret", "fixture-secret")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError) as failure:
        service.query("a", ExchangeQuery(exchange="okx", operation="ticker", symbol="BTC-USDT"))
    assert "fixture-secret" not in str(failure.value)
    for body in [
        {"exchange": "okx", "operation": "withdraw"},
        {"exchange": "binance", "operation": "ticker", "symbol": "BTC; echo hi"},
        {"exchange": "binance", "operation": "ticker", "command": "bash"},
    ]:
        with pytest.raises(ValidationError):
            ExchangeQuery.model_validate(body)


def test_exchange_api_requires_auth_and_does_not_accept_tenant_override(client, monkeypatch):
    assert client.get("/api/exchanges").status_code == 401
    seen = []
    monkeypatch.setattr(
        client.app.state.chat.exchanges, "inventory", lambda tenant: seen.append(tenant) or []
    )
    headers = {"Authorization": "Bearer test-token-a"}
    assert client.get("/api/exchanges", headers=headers).json() == []
    assert seen == ["a"]
    assert (
        client.post(
            "/api/exchanges/query",
            headers=headers,
            json={"exchange": "okx", "operation": "balances", "tenant_id": "b"},
        ).status_code
        == 422
    )


def test_model_env_imports_only_deepseek_key(tmp_path, monkeypatch):
    from finance_agent.settings import Settings

    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {"fixture": "a"}}))
    env_file = tmp_path / "model.env"
    env_file.write_text(
        "LLM_API_KEY=fixture-model\nLLM_BASE_URL=https://api.deepseek.com\nTRADING_SECRET=never-import\n"
    )
    monkeypatch.setenv("FINANCE_AUTH_FILE", str(auth))
    monkeypatch.setenv("FINANCE_MODEL_ENV_FILE", str(env_file))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-before-import")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("PI_PROVIDER", "fixture-before-import")
    monkeypatch.delenv("PI_PROVIDER", raising=False)
    Settings.load()
    import os

    assert os.environ["DEEPSEEK_API_KEY"] == "fixture-model"
    assert os.environ["PI_PROVIDER"] == "deepseek"
    assert "TRADING_SECRET" not in os.environ
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.delenv("PI_PROVIDER")
    env_file.write_text("LLM_API_KEY=unrelated\nLLM_BASE_URL=https://other.example\n")
    Settings.load()
    assert "DEEPSEEK_API_KEY" not in os.environ
