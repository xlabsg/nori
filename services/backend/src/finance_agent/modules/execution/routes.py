import asyncio
import secrets
import time

from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response

from finance_agent.modules.execution.desktop import DesktopAction
from finance_agent.modules.execution.terminal import TerminalUnavailable
from finance_agent.modules.tasks.service import NotFound


def register_desktop(app, desktop, tenant_dependency, root):
    terminal = desktop.terminal
    desktop_sessions = {}

    @app.get("/api/conversations/{conversation_id}/desktop/connect")
    @app.post("/api/conversations/{conversation_id}/desktop/connect")
    def desktop_connect(conversation_id: str, request: Request, tenant: str = tenant_dependency):
        if request.method == "POST":
            desktop.ready(tenant, conversation_id)
        else:
            terminal.authorize(tenant, conversation_id)
            item = terminal.inspect(terminal.name(tenant, conversation_id))
            if not item or not item["State"]["Running"]:
                return JSONResponse({"connected": False}, headers={"Cache-Control": "no-store"})
        ticket = secrets.token_urlsafe(32)
        now = time.time()
        for key, session in list(desktop_sessions.items()):
            if session[2] <= now:
                desktop_sessions.pop(key, None)
        desktop_sessions[ticket] = (tenant, conversation_id, now + 1800)
        response = JSONResponse(
            {
                "connected": True,
                "image": "Debian 12 Desktop",
                "url": f"/desktop/{conversation_id}/view",
            }
        )
        response.set_cookie(
            "finance_desktop",
            ticket,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=1800,
            path=f"/desktop/{conversation_id}",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    def desktop_identity(cookies, conversation_id):
        session = desktop_sessions.get(cookies.get("finance_desktop", ""))
        if not session or session[1] != conversation_id or session[2] <= time.time():
            raise HTTPException(401, "Desktop session expired")
        terminal.authorize(session[0], conversation_id)
        return session

    @app.post("/api/desktop/disconnect")
    def desktop_disconnect(tenant: str = tenant_dependency):
        for key, session in list(desktop_sessions.items()):
            if session[0] == tenant:
                desktop_sessions.pop(key, None)
        return {"disconnected": True}

    @app.get("/api/conversations/{conversation_id}/desktop/screenshot")
    def desktop_screenshot(conversation_id: str, tenant: str = tenant_dependency):
        return Response(
            desktop.screenshot(tenant, conversation_id),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/conversations/{conversation_id}/desktop/actions")
    def desktop_action(
        conversation_id: str, action: DesktopAction, tenant: str = tenant_dependency
    ):
        return desktop.action(tenant, conversation_id, action)

    @app.get("/desktop/{conversation_id}/{asset:path}")
    async def desktop_asset(conversation_id: str, asset: str, request: Request):
        import httpx

        tenant, _, _ = desktop_identity(request.cookies, conversation_id)
        if ".." in asset or "\\" in asset or not asset or asset.startswith("/"):
            raise HTTPException(404, "Asset not found")
        if asset == "view":
            return FileResponse(
                root / "apps/web/desktop-view.html", headers={"Cache-Control": "no-store"}
            )
        endpoint = await asyncio.to_thread(desktop.endpoint, tenant, conversation_id)
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                result = await client.get(f"http://{endpoint}/{asset}")
        except httpx.HTTPError:
            raise HTTPException(503, "Desktop unavailable") from None
        return Response(
            result.content,
            status_code=result.status_code,
            media_type=result.headers.get("content-type", "application/octet-stream"),
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.websocket("/desktop/{conversation_id}/websockify")
    async def desktop_websocket(websocket: WebSocket, conversation_id: str):
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed

        try:
            tenant, _, expires = desktop_identity(websocket.cookies, conversation_id)
            expected = (
                ("https" if websocket.url.scheme == "wss" else "http")
                + "://"
                + websocket.headers.get("host", "")
            )
            if websocket.headers.get("origin") != expected:
                await websocket.close(code=1008)
                return
            endpoint = await asyncio.to_thread(desktop.endpoint, tenant, conversation_id)
        except (HTTPException, NotFound, TerminalUnavailable):
            await websocket.close(code=1008)
            return
        await websocket.accept(
            subprotocol="binary" if "binary" in websocket.scope.get("subprotocols", []) else None
        )

        async def to_desktop(upstream):
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                await upstream.send(
                    message.get("bytes") if message.get("bytes") is not None else message["text"]
                )

        async def to_user(upstream):
            async for data in upstream:
                if isinstance(data, bytes):
                    await websocket.send_bytes(data)
                else:
                    await websocket.send_text(data)

        async def session_expired():
            while (
                time.time() < expires
                and websocket.cookies.get("finance_desktop") in desktop_sessions
            ):
                await asyncio.sleep(1)

        pending = set()
        try:
            async with connect(
                f"ws://{endpoint}/websockify",
                subprotocols=["binary"],
                proxy=None,
                max_size=4_000_000,
                open_timeout=10,
            ) as upstream:
                pending = {
                    asyncio.create_task(to_desktop(upstream)),
                    asyncio.create_task(to_user(upstream)),
                    asyncio.create_task(session_expired()),
                }
                await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        except (ConnectionClosed, WebSocketDisconnect, OSError, TimeoutError):
            pass
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            try:
                await websocket.close()
            except (RuntimeError, WebSocketDisconnect):
                pass
