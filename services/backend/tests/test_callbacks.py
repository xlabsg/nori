import hashlib
import hmac

import pytest

from finance_agent.modules.analytics.schemas import TaskCreate
from finance_agent.modules.callbacks.delivery import CallbackDispatcher, public_target
from finance_agent.modules.tasks.service import TaskService


def test_signature_retry_and_dedupe(database, input_data):
    tasks = TaskService(database, ["a"])
    task = tasks.create(
        "a", TaskCreate(name="Report", idempotency_key="cb", input=input_data), now=100
    )
    calls = []
    secret = "synthetic-signing-secret"

    def transport(url, body, headers):
        calls.append(headers["X-Finance-Event-Id"])
        expected = hmac.new(
            secret.encode(), headers["X-Finance-Timestamp"].encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        assert headers["X-Finance-Signature"] == "sha256=" + expected
        return 500 if len(calls) == 1 else 204

    dispatcher = CallbackDispatcher(
        database, {"a": {"url": "https://example.com/hook", "secret": secret}}, transport
    )
    assert dispatcher.tick(now=101)
    assert dispatcher.list("a")[0]["status"] == "pending"
    assert not dispatcher.tick(now=102)
    assert dispatcher.tick(now=200)
    assert calls[0] == calls[1]
    assert dispatcher.list("a")[0]["status"] == "delivered"
    assert not dispatcher.tick(now=201)
    assert dispatcher.list("b") == []
    assert tasks.events("a", task["id"])[0]["event_id"] == calls[0]


def test_retry_exhaustion(database, input_data):
    tasks = TaskService(database, ["a"])
    tasks.create("a", TaskCreate(name="Report", idempotency_key="cb", input=input_data), now=0)
    dispatcher = CallbackDispatcher(
        database, {"a": {"url": "https://example.com", "secret": "test"}}, lambda *args: 503
    )
    for index in range(8):
        assert dispatcher.tick(now=index * 4000)
    assert dispatcher.list("a")[0]["status"] == "dead_letter"
    assert dispatcher.list("a")[0]["attempts"] == 8


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com:444",
        "https://example.com/#fragment",
    ],
)
def test_callback_invalid_targets(url):
    with pytest.raises(ValueError):
        public_target(url)


def test_callback_private_dns_rejected(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        public_target("https://example.com")
