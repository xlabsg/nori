import base64
import time
from types import SimpleNamespace

import httpx
import pytest

from finance_agent.modules.connectors.google import SCOPES, ConnectorError, GoogleAPI
from finance_agent.modules.connectors.vault import CredentialVault
from finance_agent.modules.tasks.service import Conflict

A = {"Authorization": "Bearer test-token-a"}
B = {"Authorization": "Bearer test-token-b"}


def transport(handler, credentials=None, save=None):
    credentials = credentials or {"access_token": "fixture", "expires_at": time.time() + 3600}
    return GoogleAPI(
        credentials,
        save or (lambda _: None),
        "client",
        "secret",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )


def mail(identifier="m1"):
    return {
        "id": identifier,
        "internalDate": str(int(time.time() * 1000)),
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "Subject", "value": "测试账单"}],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "data": base64.urlsafe_b64encode("账单正文".encode()).decode().rstrip("=")
                    },
                }
            ],
        },
    }


def test_gmail_baseline_history_pagination_duplicate_and_deleted_message():
    calls = []

    def handler(request):
        calls.append(request)
        path = request.url.path
        if path.endswith("/profile"):
            return httpx.Response(200, json={"historyId": "10"})
        if path.endswith("/messages"):
            assert "after:" in request.url.params["q"]
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        if path.endswith("/history"):
            assert request.url.params["startHistoryId"] == "10"
            if "pageToken" not in request.url.params:
                return httpx.Response(
                    200,
                    json={
                        "historyId": "12",
                        "nextPageToken": "p2",
                        "history": [
                            {
                                "messagesAdded": [
                                    {"message": {"id": "m1"}},
                                    {"message": {"id": "deleted"}},
                                ]
                            }
                        ],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "historyId": "13",
                    "history": [{"messagesAdded": [{"message": {"id": "m1"}}]}],
                },
            )
        if path.endswith("/deleted"):
            return httpx.Response(404, json={})
        return httpx.Response(200, json=mail())

    api = transport(handler)
    cursor, first = api.sync_mail(None, time.time() - 1)
    assert cursor == "10" and first[0]["text"] == "账单正文"
    cursor, changes = api.sync_mail(cursor, time.time() - 1)
    assert cursor == "13" and len(changes) == 1
    assert changes[0]["subject"] == "测试账单"
    api.close()


def test_gmail_expired_history_falls_back_to_bounded_resync():
    def handler(request):
        if request.url.path.endswith("/history"):
            return httpx.Response(404, json={})
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"historyId": "new"})
        return httpx.Response(200, json={"messages": []})

    api = transport(handler)
    assert api.sync_mail("expired", time.time() - 100) == ("new", [])
    api.close()


def test_calendar_sync_token_expiry_pagination_and_tombstones():
    def handler(request):
        params = request.url.params
        assert "timeMin" not in params
        if params.get("syncToken") == "expired":
            return httpx.Response(410, json={})
        if "pageToken" not in params:
            return httpx.Response(
                200,
                json={
                    "nextPageToken": "p2",
                    "items": [{"id": "a", "summary": "会议", "updated": "2026-10-01T00:00:00Z"}],
                },
            )
        return httpx.Response(
            200,
            json={
                "nextSyncToken": "new",
                "items": [{"id": "b", "status": "cancelled", "updated": "2026-10-01T00:00:00Z"}],
            },
        )

    api = transport(handler)
    cursor, records = api.sync_calendar("expired", 0)
    assert cursor == "new"
    assert records[1]["status"] == "cancelled"
    api.close()


def test_refresh_token_persisted_without_exposing_credentials():
    saved = []

    def handler(request):
        if request.method == "POST":
            assert request.url.host == "oauth2.googleapis.com"
            return httpx.Response(200, json={"access_token": "refreshed", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer refreshed"
        return httpx.Response(200, json={"historyId": "1"})

    api = transport(
        handler,
        {"refresh_token": "fixture-refresh", "expires_at": 0},
        lambda data: saved.append(dict(data)),
    )
    assert api.get("gmail", "profile")["historyId"] == "1"
    assert saved[0]["access_token"] == "refreshed"
    assert saved[0]["refresh_token"] == "fixture-refresh"
    api.close()


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "needs_reconnect"),
        (403, "permission_denied"),
        (429, "rate_limited"),
        (500, "connector_unavailable"),
    ],
)
def test_google_errors_are_sanitized(status, expected):
    api = transport(
        lambda _: httpx.Response(
            status, json={"error": "raw provider details"}, headers={"Retry-After": "120"}
        )
    )
    with pytest.raises(ConnectorError) as error:
        api.get("gmail", "profile")
    assert str(error.value) == expected
    assert "raw provider details" not in str(error.value)
    if status == 429:
        assert error.value.retry_after == 120
    api.close()


def test_invalid_refresh_requires_reconnection():
    api = transport(
        lambda _: httpx.Response(400, json={"error": "invalid_grant"}),
        {"refresh_token": "fixture", "expires_at": 0},
    )
    with pytest.raises(ConnectorError, match="needs_reconnect"):
        api.get("gmail", "profile")
    api.close()


def test_oauth_pkce_state_one_use_browser_binding_and_tenant(client, tmp_path, monkeypatch):
    service = client.app.state.chat.connectors
    service.client_id, service.client_secret = "fixture-id", "fixture-secret"
    service.vault = CredentialVault(tmp_path / "key")
    service.redirect_uri = "http://testserver/api/connectors/google/callback"
    # Authorization test uses a valid loopback redirect but no real Google exchange.
    service.redirect_uri = "http://127.0.0.1:8767/api/connectors/google/callback"
    response = client.post("/api/connectors/google/authorize", headers=A)
    assert response.status_code == 200
    url = httpx.URL(response.json()["url"])
    assert url.params["code_challenge_method"] == "S256"
    assert "fixture-secret" not in response.text
    state = url.params["state"]
    browser = response.cookies["finance_google_oauth"]
    with pytest.raises(Conflict):
        service.callback(state, "code", "another-browser")

    class FakeFlow:
        credentials = SimpleNamespace(
            token="test-access", refresh_token="test-refresh", granted_scopes=SCOPES, scopes=SCOPES
        )

        def fetch_token(self, **kwargs):
            assert kwargs["code"] == "code"

    class FakeAPI:
        def __init__(self, *args):
            pass

        def get(self, *args):
            return {"emailAddress": "fixture@example.invalid"}

        def close(self):
            pass

    monkeypatch.setattr(service, "flow", lambda _: FakeFlow())
    service.api_factory = FakeAPI
    result = service.callback(state, "code", browser)
    assert service.list("a")["connections"][0]["id"] == result["id"]
    assert service.list("b")["connections"] == []
    with pytest.raises(Conflict):
        service.callback(state, "code", browser)
    assert "test-refresh" not in client.get("/api/connectors", headers=A).text


def test_google_unconfigured_and_no_credentials_in_ui(client):
    service = client.app.state.chat.connectors
    service.client_id = ""
    assert (
        client.post("/api/connectors/google/authorize", headers=A).json()["code"]
        == "google_not_configured"
    )
    assert client.get("/api/connectors").status_code == 401
    assert client.get("/api/connectors", headers=B).json()["connections"] == []


def test_local_env_loads_only_connector_keys(tmp_path, monkeypatch):
    from finance_agent.settings import Settings

    env_file = tmp_path / ".env.test"
    env_file.write_text(
        "GOOGLE_CLIENT_ID=test\nGOOGLE_CLIENT_SECRET=fixture\nUNRELATED_SECRET=ignored\n"
    )
    monkeypatch.setenv("FINANCE_ROOT", str(tmp_path))
    monkeypatch.delenv("FINANCE_CONNECTOR_ENV_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("UNRELATED_SECRET", raising=False)
    Settings.load()
    import os

    assert os.environ["GOOGLE_CLIENT_ID"] == "test"
    assert "UNRELATED_SECRET" not in os.environ
    # setdefault changes are not tracked by monkeypatch unless explicitly restored.
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")


def test_digest_reads_only_requested_resource_and_bounds_body_fetches():
    methods = []

    def handler(request):
        methods.append(request.url.path)
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": str(i)} for i in range(105)]})
        return httpx.Response(200, json=mail(request.url.path.rsplit("/", 1)[-1]))

    api = transport(handler)
    result = api.digest(time.time(), "Asia/Shanghai", resources=["gmail"])
    assert result["calendar"] == []
    assert len(result["gmail"]) == 100
    assert result["truncated"]
    assert not any("calendars" in path for path in methods)
    api.close()


def test_calendar_incremental_deleted_event_without_updated_is_preserved():
    api = transport(
        lambda _: httpx.Response(
            200,
            json={
                "nextSyncToken": "next",
                "items": [{"id": "deleted", "status": "cancelled"}],
            },
        )
    )
    _, records = api.sync_calendar("previous", 0)
    assert records[0]["version"] == "cancelled"
    assert records[0]["updated"]
    api.close()


@pytest.mark.parametrize(
    "resource,reasons,expected",
    [
        ("gmail", {"errors": [{"reason": "accessNotConfigured"}]}, "gmail_api_disabled"),
        ("calendar", {"details": [{"reason": "SERVICE_DISABLED"}]}, "calendar_api_disabled"),
        (
            "gmail",
            {"details": [{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]},
            "insufficient_scopes",
        ),
        ("gmail", {"errors": [{"reason": "insufficientPermissions"}]}, "insufficient_scopes"),
        ("gmail", {"errors": [{"reason": "domainPolicy"}]}, "domain_policy_denied"),
        ("gmail", {"errors": [{"reason": "userRateLimitExceeded"}]}, "rate_limited"),
        ("gmail", {"errors": [{"reason": "unknown"}]}, "permission_denied"),
        ("gmail", {"details": None}, "permission_denied"),
    ],
)
def test_google_permission_reasons_are_actionable_and_sanitized(resource, reasons, expected):
    api = transport(
        lambda _: httpx.Response(
            403, json={"error": {"message": "private provider message", **reasons}}
        )
    )
    with pytest.raises(ConnectorError) as error:
        api.get(resource, "profile")
    assert error.value.code == expected
    assert "private" not in str(error.value)
    api.close()
