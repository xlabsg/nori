import secrets

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from finance_agent.modules.tasks.agent_schemas import (
    AgentTaskCreate,
    AgentTaskToggle,
    AgentTaskUpdate,
)


def register_connectors(app, chat, tenant_dependency):
    connectors, tasks = chat.connectors, chat.agent_tasks

    @app.get("/assets/connectors.js", include_in_schema=False)
    def script():
        from fastapi.responses import FileResponse

        return FileResponse(
            chat.settings.root / "apps/web/connectors.js", media_type="text/javascript"
        )

    @app.get("/api/connectors")
    def inventory(tenant: str = tenant_dependency):
        return connectors.list(tenant)

    @app.post("/api/connectors/google/authorize")
    def authorize(request: Request, tenant: str = tenant_dependency):
        browser = secrets.token_urlsafe(32)
        url = connectors.authorize(tenant, browser)
        response = JSONResponse({"url": url})
        response.set_cookie(
            "finance_google_oauth",
            browser,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=600,
            path="/api/connectors/google/callback",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/connectors/google/callback", include_in_schema=False)
    def callback(request: Request, state: str = "", code: str = "", error: str = ""):
        if error or not code or not state:
            text = "Google 连接未完成。请返回工作区重新连接。"
        else:
            connectors.callback(state, code, request.cookies.get("finance_google_oauth", ""))
            text = "Google 已连接。可以关闭此窗口，返回对话创建任务。"
        response = HTMLResponse(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Google 连接</title><p>'
            + text
            + '</p><a href="/">返回工作区</a></html>',
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'",
            },
        )
        response.delete_cookie("finance_google_oauth", path="/api/connectors/google/callback")
        return response

    @app.post("/api/connectors/{connection_id}/disconnect")
    def disconnect(connection_id: str, tenant: str = tenant_dependency):
        connectors.disconnect(tenant, connection_id)
        return {"disconnected": True}

    @app.get("/api/agent-tasks")
    def inventory_tasks(tenant: str = tenant_dependency):
        return tasks.list(tenant)

    @app.post("/api/conversations/{conversation_id}/agent-tasks", status_code=201)
    def create_task(
        conversation_id: str,
        body: AgentTaskCreate,
        request: Request,
        tenant: str = tenant_dependency,
    ):
        key = request.headers.get("Idempotency-Key", "")
        if not key or len(key) > 120:
            raise HTTPException(422, "Idempotency-Key required (1..120 characters)")
        return tasks.create(tenant, conversation_id, body, "api:" + key)

    @app.patch("/api/agent-tasks/{task_id}")
    def toggle(
        task_id: str, body: AgentTaskToggle | AgentTaskUpdate, tenant: str = tenant_dependency
    ):
        if isinstance(body, AgentTaskToggle):
            return tasks.toggle(tenant, task_id, body.enabled)
        return tasks.update(tenant, task_id, body)

    @app.post("/api/agent-tasks/{task_id}/cancel")
    def cancel_task(task_id: str, tenant: str = tenant_dependency):
        return tasks.cancel(tenant, task_id)

    @app.post("/api/agent-tasks/{task_id}/run")
    def run_now(task_id: str, tenant: str = tenant_dependency):
        return tasks.run_now(tenant, task_id)

    @app.get("/api/agent-tasks/{task_id}/runs")
    def runs(task_id: str, tenant: str = tenant_dependency):
        return tasks.runs(tenant, task_id)
