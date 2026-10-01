from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from finance_agent.modules.notifications.preferences import Preferences, PreferenceService
from finance_agent.modules.notifications.telegram import (
    TelegramConfig,
    TelegramError,
    TelegramService,
)
from finance_agent.modules.tasks.health import service_status


def register_assistant(app, chat, tenant_dependency):
    preferences = PreferenceService(chat.database)
    telegram = TelegramService(chat.database)

    @app.get("/assets/assistant.js", include_in_schema=False)
    def script():
        return FileResponse(
            chat.settings.root / "apps/web/assistant.js", media_type="text/javascript"
        )

    @app.get("/api/assistant/preferences")
    def get_preferences(tenant: str = tenant_dependency):
        return preferences.get(tenant).model_dump()

    @app.put("/api/assistant/preferences")
    def save_preferences(body: Preferences, tenant: str = tenant_dependency):
        return preferences.save(tenant, body)

    @app.get("/api/assistant/status")
    def status(tenant: str = tenant_dependency):
        return {"services": service_status(chat.database), "telegram": telegram.status(tenant)}

    @app.put("/api/assistant/telegram")
    async def configure(request: Request, tenant: str = tenant_dependency):
        # Do not let validation responses echo a submitted secret.
        try:
            body = TelegramConfig.model_validate(await request.json())
            return telegram.configure(tenant, body)
        except (ValidationError, ValueError, TelegramError):
            raise HTTPException(422, "请检查 Telegram bot token 和数字 chat ID") from None

    @app.delete("/api/assistant/telegram")
    def disconnect(tenant: str = tenant_dependency):
        telegram.disconnect(tenant)
        return {"disconnected": True}

    @app.post("/api/assistant/telegram/test")
    def test(tenant: str = tenant_dependency):
        try:
            return telegram.test(tenant)
        except TelegramError:
            raise HTTPException(409, "请先配置 Telegram") from None
