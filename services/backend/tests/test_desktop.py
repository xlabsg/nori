import os
import subprocess

import pytest
from starlette.websockets import WebSocketDisconnect

from finance_agent.modules.agent.tools import FinanceTools

A = {"Authorization": "Bearer test-token-a"}
B = {"Authorization": "Bearer test-token-b"}


def test_desktop_boundaries_without_docker(client, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unauthorized desktop access reached Docker")

    monkeypatch.setattr(client.app.state.terminal, "docker_call", forbidden)
    cid = client.post("/api/conversations", headers=A, json={}).json()["id"]
    base = f"/api/conversations/{cid}/desktop"
    assert client.post(base + "/connect").status_code == 401
    assert client.post(base + "/connect", headers=B).status_code == 404
    assert client.get(base + "/screenshot", headers=B).status_code == 404
    assert (
        client.post(
            base + "/actions", headers=B, json={"action": "click", "x": 20, "y": 20}
        ).status_code
        == 404
    )
    assert (
        client.post(base + "/actions", headers=A, json={"action": "click", "x": 2000}).status_code
        == 422
    )
    assert (
        client.post(base + "/actions", headers=A, json={"action": "key", "key": "bash"}).status_code
        == 422
    )
    assert client.get(f"/desktop/{cid}/view").status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/desktop/{cid}/websockify", headers={"Origin": "http://testserver"}
        ):
            pass


def test_real_desktop_proxy_vision_and_session(client, tasks):
    if os.environ.get("RUN_CONTAINER_TESTS") != "1":
        pytest.skip("Set RUN_CONTAINER_TESTS=1 for real Linux desktop")
    cid = client.post("/api/conversations", headers=A, json={}).json()["id"]
    other = client.post("/api/conversations", headers=B, json={}).json()["id"]
    base = f"/api/conversations/{cid}/desktop"
    terminal = client.app.state.terminal
    try:
        result = client.post(base + "/connect", headers=A)
        assert result.status_code == 200, result.text
        assert result.json()["url"] == f"/desktop/{cid}/view"
        assert "httponly" in result.headers["set-cookie"].lower()
        cookie = result.cookies.get("finance_desktop")
        headers = {"Cookie": "finance_desktop=" + cookie}
        assert client.get(f"/desktop/{cid}/view", headers=headers).status_code == 200
        assert client.get(f"/desktop/{cid}/core/rfb.js", headers=headers).status_code == 200
        assert client.get(f"/desktop/{other}/view", headers=headers).status_code == 401
        screenshot = client.get(base + "/screenshot", headers=A)
        assert screenshot.status_code == 200
        assert screenshot.content.startswith(b"\xff\xd8")
        tool = FinanceTools(tasks, "a", cid, "vision-run", terminal=terminal)
        result = tool.invoke("desktop_action", {"action": "screenshot"}, "observe")
        assert result["width"] == 1280
        assert result["screenshot_base64"]
        # Reject untrusted origins even with the legitimate desktop cookie.
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/desktop/{cid}/websockify",
                subprotocols=["binary"],
                headers={**headers, "Origin": "https://evil.invalid"},
            ):
                pass
        # The proxy connects to a real x11vnc server and receives the RFB greeting.
        with client.websocket_connect(
            f"/desktop/{cid}/websockify",
            subprotocols=["binary"],
            headers={**headers, "Origin": "http://testserver"},
        ) as ws:
            assert ws.receive_bytes().startswith(b"RFB 003.")
        assert client.post("/api/desktop/disconnect", headers=A).status_code == 200
        assert client.get(f"/desktop/{cid}/view", headers=headers).status_code == 401
    finally:
        subprocess.run(
            [terminal.docker, "rm", "-f", terminal.name("a", cid)], capture_output=True, timeout=20
        )


def test_default_desktop_can_run_finance_apps_and_python_analysis(client):
    if os.environ.get("RUN_CONTAINER_TESTS") != "1":
        pytest.skip("Set RUN_CONTAINER_TESTS=1 for the real software image")
    from finance_agent.modules.execution.desktop import DesktopAction

    cid = client.post("/api/conversations", headers=A, json={}).json()["id"]
    terminal = client.app.state.terminal
    desktop = client.app.state.desktop
    name = terminal.name("a", cid)
    try:
        desktop.ready("a", cid)
        output = terminal.docker_call(
            "exec",
            name,
            "python3",
            "-c",
            "import pandas as pd, numpy, matplotlib, scipy, requests; "
            "assert pd.Series([10,20,30]).sum() == 60; print('analysis verified')",
        )
        assert "analysis verified" in output.stdout
        terminal.docker_call(
            "exec",
            name,
            "sh",
            "-c",
            "command -v thunar mousepad evince libreoffice git curl jq rg >/dev/null",
        )
        terminal.docker_call(
            "exec",
            "--env=DISPLAY=:99",
            name,
            "sh",
            "-c",
            "libreoffice --norestore --nofirststartwizard --calc >/tmp/calc.log 2>&1 & "
            "for attempt in $(seq 1 50); do "
            "xdotool search --name 'LibreOffice Calc' >/dev/null 2>&1 && exit 0; "
            "sleep 0.2; done; exit 1",
        )
        result = desktop.action("a", cid, DesktopAction(action="screenshot"))
        assert result["screenshot_base64"]
    finally:
        subprocess.run([terminal.docker, "rm", "-f", name], capture_output=True, timeout=20)


def test_passive_desktop_connection_never_starts_a_container(client, monkeypatch):
    terminal = client.app.state.terminal
    cid = client.post("/api/conversations", headers=A, json={}).json()["id"]
    monkeypatch.setattr(
        terminal, "ensure", lambda *args: pytest.fail("Passive connection started Docker")
    )
    monkeypatch.setattr(terminal, "inspect", lambda name: None)
    base = f"/api/conversations/{cid}/desktop/connect"
    assert client.get(base, headers=B).status_code == 404
    result = client.get(base, headers=A)
    assert result.json() == {"connected": False}
    assert "set-cookie" not in result.headers
    monkeypatch.setattr(terminal, "inspect", lambda name: {"State": {"Running": True}})
    result = client.get(base, headers=A)
    assert result.json()["url"] == f"/desktop/{cid}/view"
    assert "httponly" in result.headers["set-cookie"].lower()
