import hmac
import json
import sqlite3
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from finance_agent.adapters.database import Database
from finance_agent.modules.agent.service import (
    AgentUnavailable,
    ChatRequest,
    ChatService,
    ConversationCreate,
)
from finance_agent.modules.analytics.calculations import import_csv
from finance_agent.modules.analytics.schemas import (
    ImportCSV,
    MonitorCreate,
    StrictModel,
    TaskCreate,
)
from finance_agent.modules.callbacks.delivery import CallbackDispatcher
from finance_agent.modules.connectors.google import ConnectorError
from finance_agent.modules.connectors.routes import register_connectors
from finance_agent.modules.exchanges.service import ExchangeQuery
from finance_agent.modules.execution.desktop import DesktopService
from finance_agent.modules.execution.terminal import (
    CommandRequest,
    TerminalService,
    TerminalUnavailable,
)
from finance_agent.modules.monitors.service import MonitorService
from finance_agent.modules.notifications.routes import register_assistant
from finance_agent.modules.notifications.service import NotificationService
from finance_agent.modules.tasks.service import Conflict, NotFound, TaskService
from finance_agent.settings import Settings


class MonitorToggle(StrictModel):
    enabled: bool


def create_app(settings: Settings | None = None):
    settings = settings or Settings.load()
    app = FastAPI(title="Nori", version="0.1.0")
    database = Database(settings.database)
    tasks = TaskService(database, settings.callbacks)
    terminal = TerminalService(database)
    chat = ChatService(settings, tasks)
    chat.terminal = terminal
    app.state.terminal = terminal
    desktop = DesktopService(terminal)
    app.state.desktop = desktop
    app.state.chat = chat
    monitors = MonitorService(tasks)
    notifications = NotificationService(database)
    callbacks = CallbackDispatcher(database, settings.callbacks)
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if not settings.tokens:
            return "local"
        if credentials and credentials.scheme.lower() == "bearer":
            for token, tenant in settings.tokens.items():
                if hmac.compare_digest(credentials.credentials.encode(), token.encode()):
                    return tenant
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})

    tenant_dependency = Depends(authenticate)

    @app.exception_handler(NotFound)
    def not_found(request, error):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(Conflict)
    def conflict(request, error):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    register_connectors(app, chat, tenant_dependency)
    register_assistant(app, chat, tenant_dependency)

    @app.exception_handler(ConnectorError)
    def connector_error(request, error):
        labels = {
            "google_not_configured": "Google 尚未配置，请在服务端设置 OAuth Client ID 和 Secret",
            "needs_reconnect": "Google 连接已失效，请重新连接",
            "insufficient_scopes": "请授权邮件和日历只读访问后重新连接",
            "gmail_api_disabled": "请在 OAuth 所属项目启用 Gmail API，然后重新连接",
            "calendar_api_disabled": "请在 OAuth 所属项目启用 Google Calendar API",
            "domain_policy_denied": "Google Workspace 管理员限制了此应用访问，请联系管理员",
            "permission_denied": "Google 拒绝访问，请检查 API、账号授权和 Workspace 管理策略",
        }
        return JSONResponse(
            status_code=503,
            content={
                "detail": labels.get(error.code, "Google 读取未完成，请稍后重试"),
                "code": error.code,
            },
            headers={"Retry-After": str(error.retry_after)},
        )

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(settings.root / "apps/web/index.html")

    @app.get("/assets/app.js", include_in_schema=False)
    def javascript():
        return FileResponse(settings.root / "apps/web/app.js", media_type="text/javascript")

    @app.get("/assets/vendor/markdown-it.min.js", include_in_schema=False)
    def markdown_library():
        return FileResponse(
            settings.root / "apps/web/vendor/markdown-it.min.js", media_type="text/javascript"
        )

    @app.get("/assets/markdown.js", include_in_schema=False)
    def markdown_javascript():
        return FileResponse(settings.root / "apps/web/markdown.js", media_type="text/javascript")

    @app.get("/assets/chat.js", include_in_schema=False)
    def chat_javascript():
        return FileResponse(settings.root / "apps/web/chat.js", media_type="text/javascript")

    @app.get("/assets/workspace.css", include_in_schema=False)
    def workspace_styles():
        return FileResponse(settings.root / "apps/web/workspace.css", media_type="text/css")

    @app.get("/assets/workspace.js", include_in_schema=False)
    def workspace_javascript():
        return FileResponse(settings.root / "apps/web/workspace.js", media_type="text/javascript")

    @app.get("/assets/desktop.js", include_in_schema=False)
    def desktop_javascript():
        return FileResponse(settings.root / "apps/web/desktop.js", media_type="text/javascript")

    @app.get("/api/conversations")
    def list_conversations(tenant: str = tenant_dependency):
        return chat.list(tenant)

    @app.post("/api/conversations", status_code=201)
    def create_conversation(request: ConversationCreate, tenant: str = tenant_dependency):
        return chat.create(tenant, request)

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str, tenant: str = tenant_dependency):
        return chat.get(tenant, conversation_id)

    @app.post("/api/conversations/{conversation_id}/messages")
    def send_message(conversation_id: str, request: ChatRequest, tenant: str = tenant_dependency):
        chat.get(tenant, conversation_id)
        try:
            run_id, start, environment, invoke = chat.begin(tenant, conversation_id, request)
        except AgentUnavailable:
            raise HTTPException(
                503,
                "Agent 未配置：请安装 Node 运行时，并在服务端配置 DeepSeek 或 Anthropic API Key",
            ) from None
        return StreamingResponse(
            chat.stream(conversation_id, run_id, start, environment, invoke),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    from finance_agent.modules.execution.routes import register_desktop

    register_desktop(app, desktop, tenant_dependency, settings.root)

    @app.exception_handler(TerminalUnavailable)
    def terminal_unavailable(request, error):
        return JSONResponse(status_code=503, content={"detail": "Linux 执行服务不可用"})

    @app.get("/api/conversations/{conversation_id}/terminal")
    def terminal_status(conversation_id: str, tenant: str = tenant_dependency):
        return terminal.status(tenant, conversation_id)

    @app.post("/api/conversations/{conversation_id}/terminal/connect")
    def terminal_connect(conversation_id: str, tenant: str = tenant_dependency):
        terminal.ensure(tenant, conversation_id)
        return terminal.status(tenant, conversation_id)

    @app.post("/api/conversations/{conversation_id}/terminal/commands")
    def terminal_command(
        conversation_id: str, request: CommandRequest, tenant: str = tenant_dependency
    ):
        terminal.authorize(tenant, conversation_id)

        def events():
            try:
                for event in terminal.execute(tenant, conversation_id, request):
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            except Conflict as error:
                yield json.dumps({"type": "error", "message": str(error)}) + "\n"

        return StreamingResponse(
            events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/exchanges")
    def exchange_inventory(tenant: str = tenant_dependency):
        return chat.exchanges.inventory(tenant)

    @app.post("/api/exchanges/query")
    def exchange_query(request: ExchangeQuery, tenant: str = tenant_dependency):
        try:
            return chat.exchanges.query(tenant, request)
        except ValueError:
            raise HTTPException(503, "交易所查询不可用，请检查 CLI、连接状态或本租户凭证") from None

    @app.get("/healthz")
    def health():
        try:
            with database.connect() as connection:
                connection.execute("SELECT id FROM tasks LIMIT 1")
        except sqlite3.Error:
            raise HTTPException(503, "Database unavailable or migrations missing") from None
        return {"status": "ok", "mode": "local_prototype"}

    @app.get("/api/tasks")
    def list_tasks(tenant: str = tenant_dependency):
        return tasks.list(tenant)

    @app.post("/api/tasks", status_code=202)
    def create_task(request: TaskCreate, tenant: str = tenant_dependency):
        return tasks.create(tenant, request)

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str, tenant: str = tenant_dependency):
        return tasks.get(tenant, task_id)

    @app.get("/api/tasks/{task_id}/events")
    def task_events(task_id: str, tenant: str = tenant_dependency):
        return tasks.events(tenant, task_id)

    @app.post("/api/tasks/{task_id}/cancel")
    def cancel_task(task_id: str, tenant: str = tenant_dependency):
        return tasks.cancel(tenant, task_id)

    @app.post("/api/import/csv")
    def preview_csv(request: ImportCSV, tenant: str = tenant_dependency):
        try:
            return import_csv(request)
        except (ValueError, ValidationError):
            raise HTTPException(
                422, "Invalid CSV: check columns, values and duplicate assets"
            ) from None

    @app.get("/api/monitors")
    def list_monitors(tenant: str = tenant_dependency):
        return monitors.list(tenant)

    @app.post("/api/monitors", status_code=201)
    def create_monitor(request: MonitorCreate, tenant: str = tenant_dependency):
        return {"id": monitors.create(tenant, request)}

    @app.patch("/api/monitors/{monitor_id}")
    def toggle_monitor(monitor_id: str, request: MonitorToggle, tenant: str = tenant_dependency):
        monitors.set_enabled(tenant, monitor_id, request.enabled)
        return {"id": monitor_id, "enabled": request.enabled}

    @app.get("/api/notifications")
    def list_notifications(tenant: str = tenant_dependency):
        return notifications.list(tenant)

    @app.post("/api/notifications/{notification_id}/read")
    def read_notification(notification_id: str, tenant: str = tenant_dependency):
        notifications.mark_read(tenant, notification_id)
        return {"id": notification_id, "read": True}

    @app.get("/api/callbacks/deliveries")
    def list_deliveries(tenant: str = tenant_dependency):
        return callbacks.list(tenant) + CallbackDispatcher(
            database, settings.callbacks, agent_tasks=True
        ).list(tenant)

    return app
