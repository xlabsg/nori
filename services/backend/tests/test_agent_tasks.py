import json
import time
from datetime import UTC, datetime

import pytest

from finance_agent.modules.agent.service import ConversationCreate
from finance_agent.modules.callbacks.delivery import CallbackDispatcher, signed_headers
from finance_agent.modules.connectors.google import ConnectorError
from finance_agent.modules.connectors.vault import CredentialVault
from finance_agent.modules.notifications.service import NotificationService
from finance_agent.modules.tasks.agent_schemas import AgentTaskCreate
from finance_agent.modules.tasks.agent_service import next_occurrence
from finance_agent.modules.tasks.agent_worker import AgentTaskWorker
from finance_agent.modules.tasks.service import Conflict, NotFound

A = {"Authorization": "Bearer test-token-a"}
B = {"Authorization": "Bearer test-token-b"}


@pytest.fixture
def world(client, tmp_path):
    chat = client.app.state.chat
    chat.connectors.vault = CredentialVault(tmp_path / "outside-repo/key")
    state = {"mail": [], "calendar": [], "calls": 0, "sync_error": None}

    class FakeGoogle:
        def __init__(self, *args):
            pass

        def sync_mail(self, cursor, since):
            if state["sync_error"]:
                raise state["sync_error"]
            return "history-2", state["mail"]

        def sync_calendar(self, cursor, since):
            return "calendar-2", state["calendar"]

        def digest(self, now, timezone, resources=None):
            return {"gmail": state["mail"], "calendar": state["calendar"], "timezone": timezone}

        def close(self):
            pass

    chat.connectors.api_factory = FakeGoogle
    conn = chat.connectors.store(
        "a",
        "test@example.invalid",
        {
            "access_token": "test-access",
            "refresh_token": "test-refresh",
            "expires_at": time.time() + 3600,
        },
    )
    cid = chat.create("a", ConversationCreate(title="测试原对话"))["id"]

    async def bridge(root, start, environment, invoke):
        state["calls"] += 1
        assert start["mcp"] == []
        assert [t["name"] for t in start["tools"]] == ["report_task_result"]
        result = invoke(
            {
                "name": "report_task_result",
                "call_id": "report",
                "args": {
                    "notify": True,
                    "text": "测试账单明天到期。[原邮件](https://mail.google.com/)",
                },
            }
        )
        assert "error" not in result
        yield {"type": "complete", "messages": [], "limited": False}

    chat.bridge = bridge
    return chat, cid, conn["id"], state


def create(world, mode="watch", key="one", schedule=None):
    chat, cid, connection, _ = world
    request = AgentTaskCreate(
        name="账单提醒",
        instruction="有账单到期就提醒我",
        mode=mode,
        connection_id=connection if mode != "prompt" else None,
        schedule=schedule or {"kind": "interval", "interval_seconds": 900},
    )
    return chat.agent_tasks.create("a", cid, request, key)


def add_mail(state):
    state["mail"] = [
        {
            "id": "m1",
            "version": "v1",
            "received_at": time.time() + 1,
            "subject": "账单",
            "text": "请于明日付款。",
            "url": "https://mail.google.com/",
        }
    ]


def test_watch_closed_browser_result_persisted_and_zero_change_skips_model(world):
    chat, cid, connection, state = world
    task = create(world)
    chat.agent_tasks.tick()
    worker = AgentTaskWorker(chat.agent_tasks, chat)
    assert worker.work_once()
    assert state["calls"] == 0
    assert chat.get("a", cid)["events"] == []
    add_mail(state)
    chat.agent_tasks.tick(time.time() + 901)
    with chat.database.transaction() as c:
        c.execute("UPDATE agent_task_runs SET next_at=0 WHERE status='queued'")
    assert worker.work_once()
    assert state["calls"] == 1
    view = chat.get("a", cid)
    assert len(view["events"]) == 1
    assert "测试账单" in view["events"][0]["payload"]["text"]
    assert len(NotificationService(chat.database).list("a")) == 1
    chat.agent_tasks.tick(time.time() + 1802)
    with chat.database.transaction() as c:
        c.execute("UPDATE agent_task_runs SET next_at=0 WHERE status='queued'")
    assert worker.work_once()
    assert state["calls"] == 1
    assert len(chat.get("a", cid)["events"]) == 1
    assert len(chat.agent_tasks.runs("a", task["id"])) == 3


def test_retry_retains_batch_after_sync_cursor_advanced(world):
    chat, cid, connection, state = world
    task = create(world)
    add_mail(state)
    good_bridge = chat.bridge

    async def fail(*args):
        yield {"type": "error"}

    chat.bridge = fail
    chat.agent_tasks.tick()
    worker = AgentTaskWorker(chat.agent_tasks, chat)
    assert worker.work_once()
    assert chat.agent_tasks.runs("a", task["id"])[0]["status"] == "retrying"
    with chat.database.connect() as c:
        assert (
            c.execute(
                "SELECT cursor FROM connector_cursors WHERE connection_id=? AND resource='gmail'",
                (connection,),
            ).fetchone()[0]
            == "history-2"
        )
        assert c.execute("SELECT count(*) FROM agent_task_consumed").fetchone()[0] == 0
    state["mail"] = []
    chat.bridge = good_bridge
    with chat.database.transaction() as c:
        c.execute("UPDATE agent_task_runs SET next_at=0")
    assert worker.work_once()
    assert chat.agent_tasks.runs("a", task["id"])[0]["attempts"] == 2
    assert len(chat.get("a", cid)["events"]) == 1


def test_multiple_tasks_consume_shared_changes_independently(world):
    chat, _, _, state = world
    first, second = create(world, key="a"), create(world, key="b")
    add_mail(state)
    chat.agent_tasks.tick()
    worker = AgentTaskWorker(chat.agent_tasks, chat)
    assert worker.work_once() and worker.work_once()
    assert state["calls"] == 2
    assert chat.agent_tasks.runs("a", first["id"])[0]["status"] == "succeeded"
    assert chat.agent_tasks.runs("a", second["id"])[0]["status"] == "succeeded"
    with chat.database.connect() as c:
        assert c.execute("SELECT count(*) FROM connector_changes").fetchone()[0] == 1


def test_task_idempotency_tenant_boundaries_and_lease_fencing(world, client):
    chat, cid, connection, _ = world
    task = create(world)
    assert create(world)["id"] == task["id"]
    assert client.get(f"/api/agent-tasks/{task['id']}/runs", headers=B).status_code == 404
    assert (
        client.patch(
            f"/api/agent-tasks/{task['id']}", headers=B, json={"enabled": False}
        ).status_code
        == 404
    )
    assert client.post(f"/api/connectors/{connection}/disconnect", headers=B).status_code == 404
    request = AgentTaskCreate(
        name="别人的任务",
        instruction="读取",
        mode="watch",
        connection_id=connection,
        schedule={"kind": "interval", "interval_seconds": 900},
    )
    with pytest.raises(NotFound):
        chat.agent_tasks.create("b", cid, request, "foreign")
    with pytest.raises(Conflict):
        chat.agent_tasks.create("a", cid, request, "one")
    chat.agent_tasks.tick()
    run = chat.agent_tasks.claim()
    assert chat.agent_tasks.claim() is None
    chat.agent_tasks.toggle("a", task["id"], False)
    with pytest.raises(Conflict):
        chat.agent_tasks.finish(run, {"notify": True, "text": "stale"})
    assert chat.get("a", cid)["events"] == []


def test_expired_worker_cannot_publish_after_reclaim(world):
    chat, cid, _, _ = world
    create(world, mode="prompt")
    chat.agent_tasks.tick()
    old = chat.agent_tasks.claim()
    with chat.database.transaction() as c:
        c.execute("UPDATE agent_task_runs SET lease_until=0")
    replacement = chat.agent_tasks.claim()
    assert replacement["id"] == old["id"]
    assert replacement["lease_token"] != old["lease_token"]
    with pytest.raises(Conflict):
        chat.agent_tasks.finish(old, {"notify": True, "text": "stale"})
    chat.agent_tasks.finish(replacement, {"notify": True, "text": "fresh"})
    assert len(chat.get("a", cid)["events"]) == 1


def test_sync_failure_does_not_commit_cursor_and_auth_failure_pauses_tasks(world):
    chat, _, connection, state = world
    task = create(world)
    state["sync_error"] = ConnectorError("needs_reconnect")
    chat.agent_tasks.tick()
    AgentTaskWorker(chat.agent_tasks, chat).work_once()
    assert chat.connectors.list("a")["connections"][0]["status"] == "needs_reconnect"
    assert chat.agent_tasks.get("a", task["id"])["status"] == "needs_connection"
    with chat.database.connect() as c:
        assert c.execute("SELECT count(*) FROM connector_cursors").fetchone()[0] == 0
    with pytest.raises(ConnectorError):
        chat.agent_tasks.toggle("a", task["id"], True)


def test_google_credentials_encrypted_and_disconnect_invalidates_inflight(world, monkeypatch):
    chat, cid, connection, _ = world
    task = create(world)
    chat.agent_tasks.tick()
    run = chat.agent_tasks.claim()
    public = json.dumps(chat.connectors.list("a"))
    assert "test-access" not in public and "test-refresh" not in public
    with chat.database.connect() as c:
        stored = c.execute("SELECT credentials FROM connections").fetchone()[0]
        assert "test-refresh" not in stored
    monkeypatch.setattr("httpx.post", lambda *a, **kw: None)
    chat.connectors.disconnect("a", connection)
    with pytest.raises(Conflict):
        chat.agent_tasks.finish(run, {"notify": True, "text": "late"})
    assert chat.agent_tasks.get("a", task["id"])["status"] == "needs_connection"
    assert chat.get("a", cid)["events"] == []
    with chat.database.connect() as c:
        assert c.execute("SELECT credentials FROM connections").fetchone()[0] == ""


def test_background_result_does_not_overwrite_foreground_context(world):
    chat, cid, _, state = world
    create(world)
    add_mail(state)
    with chat.database.transaction() as c:
        c.execute(
            "UPDATE conversations SET active_run='foreground',transcript_json='[1]' WHERE id=?",
            (cid,),
        )
    chat.agent_tasks.tick()
    AgentTaskWorker(chat.agent_tasks, chat).work_once()
    with chat.database.connect() as c:
        row = c.execute(
            "SELECT active_run,transcript_json FROM conversations WHERE id=?", (cid,)
        ).fetchone()
        assert tuple(row) == ("foreground", "[1]")


def test_completion_callback_signed_durable_and_retried(world):
    chat, cid, _, state = world
    chat.agent_tasks.callbacks = {"a": {"url": "https://example.com/hook", "secret": "test-secret"}}
    create(world, mode="prompt")
    chat.agent_tasks.tick()
    AgentTaskWorker(chat.agent_tasks, chat).work_once()
    sent = []

    def transport(url, body, headers):
        sent.append((body, headers))
        assert (
            signed_headers("test-secret", body, int(headers["X-Finance-Timestamp"]))[
                "X-Finance-Signature"
            ]
            == headers["X-Finance-Signature"]
        )
        assert json.loads(body)["type"] == "agent_task.completed"
        return 500 if len(sent) == 1 else 200

    dispatcher = CallbackDispatcher(
        chat.database, chat.agent_tasks.callbacks, transport, agent_tasks=True
    )
    assert dispatcher.tick()
    assert dispatcher.list("a")[0]["status"] == "pending"
    assert dispatcher.tick(time.time() + 60)
    assert dispatcher.list("a")[0]["status"] == "delivered"
    assert sent[0][1]["X-Finance-Event-Id"] == sent[1][1]["X-Finance-Event-Id"]
    assert dispatcher.list("b") == []


@pytest.mark.parametrize(
    "now,at,expected",
    [
        ("2026-03-08T06:00:00+00:00", "02:30", "2026-03-09T06:30:00+00:00"),
        ("2026-11-01T04:00:00+00:00", "01:30", "2026-11-01T05:30:00+00:00"),
        ("2026-11-01T05:45:00+00:00", "01:30", "2026-11-02T06:30:00+00:00"),
    ],
)
def test_daily_timezone_and_dst(now, at, expected):
    schedule = {"kind": "daily", "at": at, "timezone": "America/New_York"}
    result = next_occurrence(schedule, datetime.fromisoformat(now).timestamp())
    assert datetime.fromtimestamp(result, UTC).isoformat() == expected


def test_oneoff_executes_once_and_scheduling_is_idempotent(world):
    chat, _, _, _ = world
    task = create(
        world, mode="prompt", schedule={"kind": "once", "run_at": datetime.now(UTC).isoformat()}
    )
    assert chat.agent_tasks.tick() == 1
    assert chat.agent_tasks.tick() == 0
    AgentTaskWorker(chat.agent_tasks, chat).work_once()
    assert chat.agent_tasks.get("a", task["id"])["status"] == "completed"
    assert chat.agent_tasks.tick(time.time() + 86400) == 0


def test_api_requires_explicit_idempotency_and_no_docker_for_tasks(world, client, monkeypatch):
    chat, cid, _, _ = world
    monkeypatch.setattr(
        chat.terminal, "docker_call", lambda *a, **kw: pytest.fail("Background task touched Docker")
    )
    body = {
        "name": "提醒",
        "instruction": "提醒我复盘",
        "mode": "prompt",
        "schedule": {"kind": "interval", "interval_seconds": 900},
    }
    path = f"/api/conversations/{cid}/agent-tasks"
    assert client.post(path, headers=A, json=body).status_code == 422
    response = client.post(path, headers={**A, "Idempotency-Key": "api-one"}, json=body)
    assert response.status_code == 201
    assert (
        client.post(path, headers={**A, "Idempotency-Key": "api-one"}, json=body).json()["id"]
        == response.json()["id"]
    )
    chat.agent_tasks.tick()
    assert AgentTaskWorker(chat.agent_tasks, chat).work_once()


def test_edit_cancels_old_lease_and_replaces_next_schedule(world, client):
    chat, cid, _, _ = world
    task = create(world, mode="prompt")
    chat.agent_tasks.tick()
    old = chat.agent_tasks.claim()
    path = f"/api/agent-tasks/{task['id']}"
    assert client.patch(path, headers=B, json={"name": "foreign"}).status_code == 404
    edited = client.patch(
        path,
        headers=A,
        json={
            "name": "新提醒",
            "schedule": {"kind": "interval", "interval_seconds": 1800},
        },
    )
    assert edited.status_code == 200
    assert edited.json()["schedule"]["interval_seconds"] == 1800
    with pytest.raises(Conflict):
        chat.agent_tasks.finish(old, {"notify": True, "text": "stale instruction"})
    chat.agent_tasks.tick()
    assert AgentTaskWorker(chat.agent_tasks, chat).work_once()
    assert len(chat.get("a", cid)["events"]) == 1
    assert client.post(path + "/cancel", headers=A).json()["status"] == "cancelled"
    assert chat.agent_tasks.tick(time.time() + 90000) == 0
    assert client.patch(path, headers=A, json={"enabled": True}).status_code == 409


def test_task_mutation_tools_not_available_for_read_only_user_query(world):
    from finance_agent.modules.agent.service import ChatRequest

    chat, cid, _, _ = world
    _, start, _, invoke = chat.begin(
        "a", cid, ChatRequest(request_id="read-only", message="我有哪些任务？")
    )
    names = {t["name"] for t in start["tools"]}
    assert "list_agent_tasks" in names
    assert "create_agent_task" not in names
    assert "update_agent_task" not in names
    assert "error" in invoke({"name": "create_agent_task", "args": {}, "call_id": "injected"})
