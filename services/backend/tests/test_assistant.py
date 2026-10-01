import json
import time
from datetime import UTC, datetime

import httpx
import pytest

from finance_agent.modules.agent.service import ChatRequest, ConversationCreate
from finance_agent.modules.connectors.google import GoogleAPI
from finance_agent.modules.notifications.preferences import (
    Preferences,
    PreferenceService,
    next_allowed,
)
from finance_agent.modules.notifications.telegram import TelegramConfig, TelegramService
from finance_agent.modules.tasks.agent_schemas import AgentTaskCreate, AgentTaskUpdate
from finance_agent.modules.tasks.calendar_reminders import calendar_reminder_result
from finance_agent.modules.tasks.health import service_heartbeat, service_status

A = {"Authorization": "Bearer test-token-a"}
B = {"Authorization": "Bearer test-token-b"}


def configure(service, tenant="a"):
    service.configure(tenant, TelegramConfig(bot_token="123:fixture", chat_id="42"))


def test_preferences_isolated_and_secret_validation_redacted(client):
    payload = Preferences(
        quiet_enabled=True, important_contacts=["contact@example.invalid"]
    ).model_dump()
    assert client.put("/api/assistant/preferences", headers=A, json=payload).status_code == 200
    assert client.get("/api/assistant/preferences", headers=B).json()["important_contacts"] == []
    response = client.put(
        "/api/assistant/telegram",
        headers=A,
        json={"bot_token": "raw-private-secret", "chat_id": "wrong"},
    )
    assert response.status_code == 422
    assert "raw-private-secret" not in response.text
    response = client.put(
        "/api/assistant/telegram", headers=A, json={"bot_token": "123:fixture", "chat_id": "42"}
    )
    assert response.status_code == 200
    assert "fixture" not in response.text
    assert not client.get("/api/assistant/status", headers=B).json()["telegram"]["configured"]


def test_telegram_outbox_retry_quiet_hours_and_disconnect(database):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(429, json={"parameters": {"retry_after": 60}})
        return httpx.Response(200, json={"ok": True})

    telegram = TelegramService(
        database, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    configure(telegram)
    now = datetime(2026, 10, 2, 15, tzinfo=UTC).timestamp()  # 23:00 Shanghai
    PreferenceService(database).save("a", Preferences(quiet_enabled=True))
    with database.transaction() as c:
        TelegramService.enqueue(c, "a", "notification", "text", now)
        TelegramService.enqueue(c, "a", "notification", "duplicate", now)
    assert telegram.tick(now)
    assert not calls
    with database.connect() as c:
        row = c.execute("SELECT * FROM notification_outbox").fetchone()
        assert row["attempts"] == 0
        due = row["next_at"]
    assert telegram.tick(due)
    assert not telegram.tick(due + 1)
    assert telegram.tick(due + 60)
    assert telegram.status("a")["last_delivery"]["status"] == "sent"
    assert len(calls) == 2 and calls[-1]["text"] == "text"
    telegram.test("a")
    telegram.disconnect("a")
    assert not telegram.tick(time.time() + 100)


def test_telegram_config_replacement_cancels_old_recipient(database):
    service = TelegramService(database)
    configure(service)
    service.test("a")
    service.configure("a", TelegramConfig(bot_token="456:replacement", chat_id="99"))
    with database.connect() as c:
        assert c.execute("SELECT status FROM notification_outbox").fetchone()[0] == "cancelled"
        row = c.execute("SELECT credentials FROM notification_channels").fetchone()
        assert "replacement" not in row[0]


@pytest.mark.parametrize(
    "start,end,hour,expected", [("22:00", "08:00", 12, False), ("09:00", "17:00", 12, True)]
)
def test_quiet_hours_same_day_and_overnight(start, end, hour, expected):
    now = datetime(2026, 10, 2, hour, tzinfo=UTC).timestamp()
    prefs = Preferences(timezone="UTC", quiet_enabled=True, quiet_start=start, quiet_end=end)
    assert (next_allowed(prefs, now) > now) is expected


def test_calendar_reminder_dedup_reschedule_cancellation_and_outbox(client, monkeypatch):
    chat = client.app.state.chat
    now = time.time()
    connection = chat.connectors.store(
        "a",
        "fixture@example.invalid",
        {"access_token": "fixture", "refresh_token": "fixture", "expires_at": now + 3600},
    )
    cid = chat.create("a", ConversationCreate())["id"]
    configure(TelegramService(chat.database))
    task = chat.agent_tasks.create(
        "a",
        cid,
        AgentTaskCreate(
            name="会议提醒",
            instruction="会议前10分钟提醒",
            mode="calendar_reminder",
            connection_id=connection["id"],
            resources=["calendar"],
            schedule={"kind": "interval", "interval_seconds": 60},
        ),
        "calendar",
    )
    event = {
        "id": "meeting",
        "title": "测试会议",
        "start": {"dateTime": datetime.fromtimestamp(now + 500, UTC).isoformat()},
        "status": "confirmed",
        "url": "https://calendar.google.com/fixture",
    }

    class API:
        def upcoming(self, *args):
            return [event]

        def close(self):
            pass

    monkeypatch.setattr(chat.connectors, "api", lambda *args: API())
    chat.agent_tasks.tick(now + 1)
    run = chat.agent_tasks.claim(now + 1)
    result = calendar_reminder_result(chat.agent_tasks, run, now)
    assert result["notify"]
    chat.agent_tasks.finish(run, result)
    chat.agent_tasks.tick(now + 62)
    run = chat.agent_tasks.claim(now + 62)
    assert not calendar_reminder_result(chat.agent_tasks, run, now)["notify"]
    event["start"]["dateTime"] = datetime.fromtimestamp(now + 550, UTC).isoformat()
    assert calendar_reminder_result(chat.agent_tasks, run, now)["notify"]
    event["status"] = "cancelled"
    assert not calendar_reminder_result(chat.agent_tasks, run, now)["notify"]
    event["status"] = "confirmed"
    event["start"] = {"date": "2026-10-02"}
    assert not calendar_reminder_result(chat.agent_tasks, run, now)["notify"]
    with chat.database.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 1
    with pytest.raises(ValueError):
        chat.agent_tasks.update(
            "a", task["id"], AgentTaskUpdate(schedule={"kind": "interval", "interval_seconds": 900})
        )


def test_search_filters_use_readonly_api_and_mail_chunking(client, monkeypatch):
    queries = []

    def handler(request):
        queries.append(dict(request.url.params))
        return httpx.Response(200, json={"messages": []})

    api = GoogleAPI(
        {"access_token": "fixture", "expires_at": time.time() + 3600},
        lambda _: None,
        "client",
        "secret",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert (
        api.search_mail(unread=True, sender="contact@example.invalid", after=100, before=200)[
            "gmail"
        ]
        == []
    )
    assert queries[0]["q"] == "in:inbox is:unread from:contact@example.invalid after:100 before:200"
    api.close()
    chat = client.app.state.chat

    class API:
        def mail(self, identifier, max_text):
            assert max_text is None
            return {
                "text": "a" * 9000,
                "subject": "fixture",
                "from": "fixture",
                "url": "https://mail.google.com",
            }

        def close(self):
            pass

    monkeypatch.setattr(chat.connectors, "api", lambda *args: API())
    monkeypatch.setattr(chat.connectors, "get", lambda *args: {})
    first = chat.connectors.mail_detail("a", "id", "message")
    last = chat.connectors.mail_detail("a", "id", "message", 8000)
    assert len(first["text"]) == 4000 and first["next_offset"] == 4000
    assert len(last["text"]) == 1000 and last["next_offset"] is None


def test_preference_tools_are_not_mutable_from_read_only_query(client):
    chat = client.app.state.chat

    async def bridge(*args):
        yield {}

    chat.bridge = bridge
    cid = chat.create("a", ConversationCreate())["id"]
    _, start, _, invoke = chat.begin(
        "a", cid, ChatRequest(request_id="prefs", message="查看我的邮件")
    )
    assert "get_preferences" in {tool["name"] for tool in start["tools"]}
    assert "save_preferences" not in {tool["name"] for tool in start["tools"]}
    assert "error" in invoke({"name": "save_preferences", "args": {}, "call_id": "unsafe"})


def test_service_health_heartbeats(database):
    assert not any(s["healthy"] for s in service_status(database))
    with service_heartbeat(database, "worker"):
        for _ in range(100):
            if service_status(database)[0]["healthy"]:
                break
            time.sleep(0.01)
        assert service_status(database)[0]["healthy"]


def test_manual_run_is_deduplicated_and_pause_fences_pending(client):
    chat = client.app.state.chat
    cid = chat.create("a", ConversationCreate())["id"]
    task = chat.agent_tasks.create(
        "a",
        cid,
        AgentTaskCreate(
            name="fixture",
            instruction="提醒",
            mode="prompt",
            schedule={"kind": "daily", "at": "08:30"},
        ),
        "manual",
    )
    first = chat.agent_tasks.run_now("a", task["id"])
    assert chat.agent_tasks.run_now("a", task["id"]) == first
    chat.agent_tasks.toggle("a", task["id"], False)
    assert chat.agent_tasks.runs("a", task["id"])[0]["status"] == "cancelled"
    assert client.post("/api/agent-tasks/" + task["id"] + "/run", headers=A).status_code == 409
    assert client.post("/api/agent-tasks/" + task["id"] + "/run", headers=B).status_code == 404


def test_calendar_reminder_lead_time_can_be_edited(client):
    chat = client.app.state.chat
    connection = chat.connectors.store(
        "a", "fixture@example.invalid", {"access_token": "fixture", "refresh_token": "fixture"}
    )
    cid = chat.create("a", ConversationCreate())["id"]
    task = chat.agent_tasks.create(
        "a",
        cid,
        AgentTaskCreate(
            name="fixture",
            instruction="会议提醒",
            mode="calendar_reminder",
            connection_id=connection["id"],
            resources=["calendar"],
            schedule={"kind": "interval", "interval_seconds": 60},
        ),
        "lead",
    )
    result = chat.agent_tasks.update("a", task["id"], AgentTaskUpdate(reminder_minutes=5))
    assert result["reminder_minutes"] == 5


def test_html_mail_extracts_body_without_scripts_and_marks_snippet():
    import base64

    data = {
        "id": "fixture",
        "snippet": "short",
        "payload": {
            "mimeType": "text/html",
            "body": {
                "data": base64.urlsafe_b64encode(
                    b"<style>hidden</style><p>Invoice &amp; due</p><script>unsafe()</script>"
                ).decode()
            },
        },
    }
    api = GoogleAPI(
        {"access_token": "fixture", "expires_at": time.time() + 3600},
        lambda _: None,
        "client",
        "secret",
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))),
    )
    result = api.mail("fixture", max_text=None)
    assert result["text"] == "Invoice & due"
    assert result["text_source"] == "html" and not result["text_truncated"]
    data["payload"] = {}
    result = api.mail("fixture", max_text=None)
    assert result["text"] == "short"
    assert result["text_source"] == "snippet" and result["text_truncated"]
    api.close()
