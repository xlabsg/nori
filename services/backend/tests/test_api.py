from finance_agent.entrypoints.worker import work_once

A = {"Authorization": "Bearer test-token-a"}
B = {"Authorization": "Bearer test-token-b"}


def test_auth_and_tenant_boundary(client, tasks, input_data):
    assert client.get("/api/tasks").status_code == 401
    body = {"name": "API report", "idempotency_key": "api", "input": input_data}
    response = client.post("/api/tasks", headers=A, json=body)
    assert response.status_code == 202
    task_id = response.json()["id"]
    assert client.post("/api/tasks", headers=A, json=body).json()["id"] == task_id
    assert client.get(f"/api/tasks/{task_id}", headers=B).status_code == 404
    assert client.get(f"/api/tasks/{task_id}/events", headers=B).status_code == 404
    assert client.post(f"/api/tasks/{task_id}/cancel", headers=B).status_code == 404
    assert client.get("/api/tasks", headers=B).json() == []
    work_once(tasks)
    note = client.get("/api/notifications", headers=A).json()[0]
    assert client.post(f"/api/notifications/{note['id']}/read", headers=B).status_code == 404
    assert client.post(f"/api/notifications/{note['id']}/read", headers=A).status_code == 200


def test_input_validation_and_idempotency(client, input_data):
    body = {"name": "Report", "idempotency_key": "conflict", "input": input_data}
    assert client.post("/api/tasks", headers=A, json=body).status_code == 202
    input_data["closing_equity"] = "9999"
    assert client.post("/api/tasks", headers=A, json=body).status_code == 409
    input_data["closing_equity"] = "NaN"
    assert client.post("/api/tasks", headers=A, json=body).status_code == 422


def test_web_and_health(client):
    assert client.get("/healthz").status_code == 200
    assert "交代工作，让 Nori 持续跟进" in client.get("/").text
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "javascript" in asset.headers["content-type"]


def test_csv_requires_auth_and_rejects_extra_columns(client):
    body = {
        "csv": "asset_id,quantity,price,extra\nBTC,1,2,x",
        "observed_at": "2026-10-01T00:00:00Z",
        "source": "fixture",
    }
    assert client.post("/api/import/csv", json=body).status_code == 401
    assert client.post("/api/import/csv", headers=A, json=body).status_code == 422


def test_default_workspace_requires_no_credentials(database):
    from fastapi.testclient import TestClient

    from finance_agent.entrypoints.api import create_app
    from finance_agent.settings import Settings

    with TestClient(create_app(Settings(database.path))) as local:
        assert local.get("/api/tasks").status_code == 200
        conversation = local.post("/api/conversations", json={})
        assert conversation.status_code == 201
        identifier = conversation.json()["id"]
        assert local.get(f"/api/conversations/{identifier}").status_code == 200
        with database.connect() as connection:
            row = connection.execute(
                "SELECT tenant_id FROM conversations WHERE id=?", (identifier,)
            ).fetchone()
        assert row["tenant_id"] == "local"
        assert local.post("/api/conversations", json={"tenant_id": "other"}).status_code == 422


def test_default_settings_ignore_legacy_workspace_tokens(tmp_path, monkeypatch):
    import json

    from finance_agent.settings import Settings

    monkeypatch.setenv("FINANCE_ROOT", str(tmp_path))
    monkeypatch.delenv("FINANCE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("FINANCE_AUTH_FILE", raising=False)
    assert Settings.load().tokens == {}
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime/auth.json").write_text(
        json.dumps({"tokens": {"old-fixture": "local"}, "callbacks": {}})
    )
    assert Settings.load().tokens == {}
