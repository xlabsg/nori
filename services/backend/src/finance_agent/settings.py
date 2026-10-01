import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[4]


@dataclass
class Settings:
    database: Path
    tokens: dict[str, str] = field(default_factory=dict)
    callbacks: dict[str, dict[str, str]] = field(default_factory=dict)
    root: Path = ROOT

    @classmethod
    def load(cls):
        model_env = os.environ.get("FINANCE_MODEL_ENV_FILE")
        if model_env:
            values = dotenv_values(model_env)
            deepseek_key = values.get("DEEPSEEK_API_KEY")
            if (
                not deepseek_key
                and urlparse(values.get("LLM_BASE_URL") or "").hostname == "api.deepseek.com"
            ):
                deepseek_key = values.get("LLM_API_KEY")
            if deepseek_key:
                os.environ.setdefault("DEEPSEEK_API_KEY", deepseek_key)
                os.environ.setdefault("PI_PROVIDER", "deepseek")
        root = Path(os.environ.get("FINANCE_ROOT", ROOT))
        connector_env = Path(os.environ.get("FINANCE_CONNECTOR_ENV_FILE", root / ".env.test"))
        if connector_env.exists():
            values = dotenv_values(connector_env)
            for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
                if values.get(key):
                    os.environ.setdefault(key, values[key])
        config = Path(os.environ.get("FINANCE_CONFIG_FILE", root / ".runtime/config.json"))
        legacy = Path(os.environ.get("FINANCE_AUTH_FILE", root / ".runtime/auth.json"))
        if not config.exists() and legacy.exists():
            config = legacy
        data = json.loads(config.read_text()) if config.exists() else {}
        return cls(
            database=Path(os.environ.get("FINANCE_DATABASE", root / ".runtime/finance.db")),
            callbacks=data.get("callbacks", {}),
            root=root,
        )
