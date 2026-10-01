import json
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from finance_agent.modules.agent.service import ChatService, ConversationCreate
from finance_agent.modules.agent.tools import FinanceTools
from finance_agent.modules.execution.terminal import CommandRequest, TerminalService
from finance_agent.modules.tasks.service import Conflict
from finance_agent.settings import Settings

A = {"Authorization": "Bearer test-token-a"}
B = {"Authorization": "Bearer test-token-b"}


def test_terminal_auth_before_docker(client, monkeypatch):
    terminal = client.app.state.terminal

    def forbidden(*args, **kwargs):
        pytest.fail("Cross-tenant request reached Docker")

    monkeypatch.setattr(terminal, "docker_call", forbidden)
    cid = client.post("/api/conversations", headers=A, json={}).json()["id"]
    base = f"/api/conversations/{cid}/terminal"
    assert client.get(base).status_code == 401
    assert client.get(base, headers=B).status_code == 404
    assert client.post(base + "/connect", headers=B).status_code == 404
    assert (
        client.post(
            base + "/commands", headers=B, json={"request_id": "x", "command": "id"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            base + "/commands",
            headers=A,
            json={"request_id": "x", "command": "id", "timeout_seconds": 31},
        ).status_code
        == 422
    )


@pytest.fixture
def real_terminal(database, tasks):
    if os.environ.get("RUN_CONTAINER_TESTS") != "1":
        pytest.skip("Set RUN_CONTAINER_TESTS=1 for real Docker integration")
    chat = ChatService(Settings(database.path, {"test": "a"}), tasks)
    terminal = TerminalService(database)
    ids = [chat.create("a", ConversationCreate())["id"] for _ in range(2)]
    try:
        yield terminal, ids
    finally:
        for cid in ids:
            subprocess.run(
                [terminal.docker, "rm", "-f", terminal.name("a", cid)],
                capture_output=True,
                timeout=20,
            )


def run(terminal, cid, command, **kwargs):
    request = CommandRequest(request_id=uuid.uuid4().hex, command=command, **kwargs)
    return terminal.invoke("a", cid, request.command, request.request_id, request.timeout_seconds)


def test_real_shared_files_isolation_and_tool(real_terminal, tasks):
    terminal, (first, second) = real_terminal
    result = run(terminal, first, "id -u; pwd; printf '真实文件' > result.txt; cat result.txt")
    assert result["exit_code"] == 0
    assert "1000\n/workspace\n真实文件" in result["output"]
    tool = FinanceTools(tasks, "a", first, "run", terminal=terminal)
    result = tool.invoke("terminal_exec", {"command": "cat result.txt"}, "call")
    assert result["output"] == "真实文件"
    assert run(terminal, second, "cat result.txt")["exit_code"] != 0
    item = terminal.inspect(terminal.name("a", first))
    host = item["HostConfig"]
    assert host["NetworkMode"] == "bridge"
    assert host["ReadonlyRootfs"]
    assert host["CapDrop"] == ["ALL"]
    assert item["Mounts"] == []
    environment = run(terminal, first, "env")["output"]
    for name in (
        "FINANCE_AUTH_FILE",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "BINANCE_API_KEY",
        "OKX_API_KEY",
    ):
        assert name + "=" not in environment


def test_real_idempotency_and_nonzero_exit(real_terminal):
    terminal, (cid, _) = real_terminal
    request = CommandRequest(request_id="once", command="echo x >> lines; cat lines")
    events = list(terminal.execute("a", cid, request))
    again = list(terminal.execute("a", cid, request))
    assert again[0]["replayed"]
    assert run(terminal, cid, "wc -l < lines")["output"].strip() == "1"
    assert events[-1]["exit_code"] == 0
    assert run(terminal, cid, "echo fail >&2; exit 7")["exit_code"] == 7
    with pytest.raises(Conflict):
        list(terminal.execute("a", cid, CommandRequest(request_id="once", command="echo other")))


def test_real_timeout_output_budget_and_concurrency(real_terminal):
    terminal, (cid, _) = real_terminal
    stream = terminal.execute(
        "a", cid, CommandRequest(request_id="busy", command="sleep 10", timeout_seconds=1)
    )
    assert next(stream)["type"] == "start"
    with ThreadPoolExecutor() as pool:
        future = pool.submit(run, terminal, cid, "echo overlap")
        with pytest.raises(Conflict):
            future.result()
    final = list(stream)[-1]
    assert final["status"] == "timed_out"
    assert not terminal.status("a", cid)["connected"]
    result = run(terminal, cid, "yes x")
    assert result["status"] == "output_limit"
    assert result["truncated"]
    assert not terminal.status("a", cid)["connected"]


def test_real_api_ndjson(client):
    if os.environ.get("RUN_CONTAINER_TESTS") != "1":
        pytest.skip("Real Docker integration")
    cid = client.post("/api/conversations", headers=A, json={}).json()["id"]
    terminal = client.app.state.terminal
    try:
        base = f"/api/conversations/{cid}/terminal"
        assert client.post(base + "/connect", headers=A).json()["connected"]
        response = client.post(
            base + "/commands",
            headers=A,
            json={"request_id": "api", "command": "uname -s; printf api-real"},
        )
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]["type"] == "start"
        assert "Linux\napi-real" in "".join(e.get("text", "") for e in events)
        assert events[-1]["exit_code"] == 0
        assert client.get(base, headers=A).json()["history"][0]["status"] == "completed"
    finally:
        subprocess.run(
            [terminal.docker, "rm", "-f", terminal.name("a", cid)], capture_output=True, timeout=20
        )
