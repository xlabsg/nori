import asyncio
import json

import pytest

from finance_agent.modules.agent.service import ChatRequest, ConversationCreate
from finance_agent.modules.agent.tools import FinanceTools
from finance_agent.modules.analytics.schemas import AnalysisInput, TaskCreate
from finance_agent.modules.tasks.service import Conflict, NotFound

A = {"Authorization": "Bearer test-token-a"}
B = {"Authorization": "Bearer test-token-b"}


async def fake_bridge(root, start, environment, invoke):
    yield {"type": "tool_start", "name": "create_analysis", "call_id": "call-1"}
    result = invoke({"name": "create_analysis", "args": {"name": "聊天分析"}, "call_id": "call-1"})
    assert "result" in result
    yield {"type": "tool_end", "name": "create_analysis", "call_id": "call-1", "is_error": False}
    yield {"type": "text_delta", "text": "分析已入队。"}
    yield {"type": "assistant", "text": "分析已入队。"}
    yield {
        "type": "complete",
        "messages": [{"role": "user", "content": start["prompt"], "timestamp": 1}],
        "limited": False,
    }


def test_chat_stream_persistence_and_tenant_isolation(client, input_data):
    client.app.state.chat.bridge = fake_bridge
    assert client.post("/api/conversations", json={}).status_code == 401
    response = client.post("/api/conversations", headers=A, json={"title": "财务对话"})
    identifier = response.json()["id"]
    assert client.get(f"/api/conversations/{identifier}", headers=B).status_code == 404
    body = {"request_id": "request-1", "message": "提交分析", "snapshot": input_data}
    assert (
        client.post(f"/api/conversations/{identifier}/messages", headers=B, json=body).status_code
        == 404
    )
    stream = client.post(f"/api/conversations/{identifier}/messages", headers=A, json=body)
    events = [json.loads(line) for line in stream.text.splitlines()]
    assert events[-1]["type"] == "run_complete"
    view = client.get(f"/api/conversations/{identifier}", headers=A).json()
    assert [event["type"] for event in view["events"]] == [
        "user",
        "tool_start",
        "tool_end",
        "assistant",
    ]
    assert len(view["tasks"]) == 1 and view["tasks"][0]["status"] == "queued"
    assert not view["running"]
    assert (
        client.post(f"/api/conversations/{identifier}/messages", headers=A, json=body).status_code
        == 409
    )
    assert len(client.get("/api/tasks", headers=A).json()) == 1
    assert client.get("/api/conversations", headers=B).json() == []


def test_missing_model_configuration_is_explicit(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    identifier = client.post("/api/conversations", headers=A, json={}).json()["id"]
    response = client.post(
        f"/api/conversations/{identifier}/messages",
        headers=A,
        json={"request_id": "one", "message": "你好"},
    )
    assert response.status_code == 503
    assert client.get(f"/api/conversations/{identifier}", headers=A).json()["events"] == []


def test_finance_tool_boundary_and_idempotency(client, tasks, input_data):
    chat = client.app.state.chat
    identifier = chat.create("a", ConversationCreate())["id"]
    tools = FinanceTools(
        chat.tasks, "a", identifier, "run", AnalysisInput.model_validate(input_data)
    )
    result = tools.invoke("analyze_snapshot", {}, "math")
    assert result["equity"]["profit"] == "500"
    created = tools.invoke("create_analysis", {"name": "Report"}, "queued")
    assert tools.invoke("create_analysis", {"name": "Report"}, "queued") == created
    with pytest.raises(ValueError):
        tools.invoke("create_analysis", {"name": "Changed"}, "queued")
    foreign = tasks.create(
        "b",
        TaskCreate(
            name="private",
            idempotency_key="private",
            input=AnalysisInput.model_validate(input_data),
        ),
    )
    with pytest.raises(NotFound):
        tools.invoke("get_task", {"task_id": foreign["id"]}, "foreign")
    with pytest.raises(ValueError):
        tools.invoke("bash", {"command": "pwd"}, "shell")
    with pytest.raises(ValueError):
        tools.invoke("list_tasks", {"tenant_id": "b"}, "tenant")


def test_failed_runtime_releases_conversation_and_preserves_error(client):
    async def failing(root, start, environment, invoke):
        yield {"type": "error", "code": "agent_unavailable"}

    client.app.state.chat.bridge = failing
    identifier = client.post("/api/conversations", headers=A, json={}).json()["id"]
    response = client.post(
        f"/api/conversations/{identifier}/messages",
        headers=A,
        json={"request_id": "one", "message": "你好"},
    )
    assert "agent_run_failed" in response.text
    view = client.get(f"/api/conversations/{identifier}", headers=A).json()
    assert not view["running"] and view["events"][-1]["type"] == "error"


def test_active_run_prevents_overlap_and_cancel_releases_lease(client):
    chat = client.app.state.chat
    chat.bridge = fake_bridge
    identifier = chat.create("a", ConversationCreate())["id"]
    args = chat.begin("a", identifier, ChatRequest(request_id="one", message="hello"))
    with pytest.raises(Conflict):
        chat.begin("a", identifier, ChatRequest(request_id="two", message="other"))

    async def stop():
        stream = chat.stream(identifier, *args)
        await anext(stream)
        await stream.aclose()

    asyncio.run(stop())
    assert not chat.get("a", identifier)["running"]


def test_real_pi_subprocess_bridge_calls_python_finance_tools(client, input_data):
    from finance_agent.modules.agent.service import pi_bridge

    async def bridge(root, start, environment, invoke):
        async for event in pi_bridge(
            root, start, environment, invoke, entry="test/fixture-runtime.ts"
        ):
            yield event

    client.app.state.chat.bridge = bridge
    identifier = client.post("/api/conversations", headers=A, json={}).json()["id"]
    stream = client.post(
        f"/api/conversations/{identifier}/messages",
        headers=A,
        json={"request_id": "pi-integration", "message": "分析并提交任务", "snapshot": input_data},
    )
    events = [json.loads(line) for line in stream.text.splitlines()]
    assert events[-1]["type"] == "run_complete"
    assert [e["name"] for e in events if e["type"] == "tool_end"] == [
        "analyze_snapshot",
        "create_analysis",
    ]
    assert "500 USD" in stream.text
    view = client.get(f"/api/conversations/{identifier}", headers=A).json()
    assert len(view["tasks"]) == 1
    with client.app.state.chat.database.connect() as connection:
        transcript = connection.execute(
            "SELECT transcript_json FROM conversations WHERE id=?", (identifier,)
        ).fetchone()[0]
    assert '"toolResult"' in transcript and '"500"' in transcript


def test_monitor_tools_require_explicit_turn_permission(client, input_data):
    chat = client.app.state.chat
    chat.bridge = fake_bridge
    identifier = chat.create("a", ConversationCreate())["id"]
    run_id, start, environment, invoke = chat.begin(
        "a",
        identifier,
        ChatRequest(
            request_id="one", message="查看快照", snapshot=AnalysisInput.model_validate(input_data)
        ),
    )
    assert "create_monitor" not in {tool["name"] for tool in start["tools"]}
    denied = invoke(
        {
            "name": "create_monitor",
            "args": {"name": "Monitor", "interval_seconds": 60},
            "call_id": "monitor",
        }
    )
    assert "error" in denied
    with chat.database.transaction() as connection:
        connection.execute("UPDATE conversations SET active_run=NULL WHERE id=?", (identifier,))
    args = chat.begin(
        "a",
        identifier,
        ChatRequest(
            request_id="two",
            message="每分钟分析固定快照",
            snapshot=AnalysisInput.model_validate(input_data),
            allow_monitor_changes=True,
        ),
    )
    assert "create_monitor" in {tool["name"] for tool in args[1]["tools"]}
    result = args[3](
        {
            "name": "create_monitor",
            "args": {"name": "Monitor", "interval_seconds": 60},
            "call_id": "monitor",
        }
    )
    assert result["result"]["mode"] == "fixed_snapshot"


def test_stream_closes_inner_bridge_on_disconnect(client):
    closed = []

    async def bridge(root, start, environment, invoke):
        try:
            yield {"type": "text_delta", "text": "partial"}
            await asyncio.sleep(100)
        finally:
            closed.append(True)

    chat = client.app.state.chat
    chat.bridge = bridge
    identifier = chat.create("a", ConversationCreate())["id"]
    args = chat.begin("a", identifier, ChatRequest(request_id="one", message="hello"))

    async def disconnect():
        stream = chat.stream(identifier, *args)
        await anext(stream)
        await anext(stream)
        await stream.aclose()

    asyncio.run(disconnect())
    assert closed == [True]
    assert not chat.get("a", identifier)["running"]


def test_mcp_gate_is_tenant_scoped_and_rejects_expired_run(client, tmp_path):
    chat = client.app.state.chat
    chat.bridge = fake_bridge
    from finance_agent.settings import ROOT

    (tmp_path / "infra/desktop").mkdir(parents=True)
    (tmp_path / "infra/desktop/chrome-tools.json").write_text(
        (ROOT / "infra/desktop/chrome-tools.json").read_text()
    )
    chat.settings.root = tmp_path
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime/agent.json").write_text(
        json.dumps(
            {
                "mcp": {
                    "a": [
                        {
                            "name": "demo",
                            "command": "/usr/bin/node",
                            "allowed_tools": ["get_snapshot"],
                        }
                    ]
                }
            }
        )
    )
    identifier = chat.create("a", ConversationCreate())["id"]
    run_id, start, environment, invoke = chat.begin(
        "a", identifier, ChatRequest(request_id="one", message="读取数据")
    )
    assert chat.runtime_config("b")[0] == []
    assert invoke({"gate": True, "name": "mcp_demo_get_snapshot", "call_id": "gate-1"})["result"][
        "allowed"
    ]
    assert "error" in invoke(
        {"gate": True, "name": "mcp_foreign_get_snapshot", "call_id": "gate-2"}
    )
    with chat.database.transaction() as connection:
        connection.execute("UPDATE conversations SET lease_until=0 WHERE id=?", (identifier,))
    assert "error" in invoke({"gate": True, "name": "mcp_demo_get_snapshot", "call_id": "gate-3"})


@pytest.mark.parametrize(
    "code", ["calendar_api_disabled", "insufficient_scopes", "connector_unavailable"]
)
def test_chat_connector_errors_preserve_sanitized_reason(client, monkeypatch, code):
    from finance_agent.modules.connectors.google import ConnectorError

    chat = client.app.state.chat
    chat.bridge = fake_bridge
    identifier = chat.create("a", ConversationCreate())["id"]
    _, _, _, invoke = chat.begin(
        "a", identifier, ChatRequest(request_id="google-error", message="查看我的邮件")
    )

    def fail(*args, **kwargs):
        raise ConnectorError(code)

    monkeypatch.setattr(chat.connectors, "read", fail)
    result = invoke(
        {"name": "google_read", "args": {"connection_id": "fixture"}, "call_id": "google"}
    )
    assert result["error"] == "Google connector request failed: " + code
    assert "invalid arguments" not in result["error"]


def test_large_google_read_returns_explicitly_bounded_previews(client, monkeypatch):
    chat = client.app.state.chat
    tools = FinanceTools(chat.tasks, "a", "conversation", "run", None, connectors=chat.connectors)
    payload = {
        "gmail": [{"id": str(i), "subject": "账单", "text": "内容" * 8000} for i in range(100)],
        "calendar": [{"id": "event", "description": "日程" * 4000}],
        "truncated": False,
    }
    monkeypatch.setattr(chat.connectors, "read", lambda *args, **kwargs: payload)
    result = tools.invoke("google_read", {"connection_id": "fixture"}, "google")
    assert len(json.dumps(result)) <= 100000
    assert result["truncated"] is True
    assert result["fetched_counts"] == {"gmail": 100, "calendar": 1}
    assert result["returned_counts"] == {
        "gmail": len(result["gmail"]),
        "calendar": len(result["calendar"]),
    }
    assert result["gmail"][0]["text_truncated"] is True
    assert len(payload["gmail"][0]["text"]) == 16000
    assert tools.invoke("google_read", {"connection_id": "fixture"}, "google") == result


def test_small_google_read_preserves_complete_content():
    from finance_agent.modules.agent.tools import bounded_google_read

    payload = {"gmail": [{"text": "完整内容"}], "calendar": [], "truncated": False}
    result = bounded_google_read(payload)
    assert result["gmail"] == payload["gmail"]
    assert result["truncated"] is False
    assert result["returned_counts"] == {"gmail": 1, "calendar": 0}
