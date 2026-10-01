"""Bounded commands in an automatically provisioned, conversation-scoped container."""

import codecs
import hashlib
import json
import os
import selectors
import shutil
import sqlite3
import subprocess
import time
import uuid
from contextlib import suppress

from pydantic import Field

from finance_agent.modules.analytics.schemas import StrictModel
from finance_agent.modules.tasks.service import Conflict, NotFound

IMAGE = "finance-agent-desktop:local"
OUTPUT_LIMIT = 65536


class TerminalUnavailable(Exception):
    pass


class CommandRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=120)
    command: str = Field(min_length=1, max_length=8000)
    timeout_seconds: int = Field(default=30, ge=1, le=30)


class TerminalService:
    def __init__(self, database):
        self.database = database
        self.docker = shutil.which("docker") or "docker"

    def authorize(self, tenant, conversation):
        with self.database.connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM conversations WHERE id=? AND tenant_id=?", (conversation, tenant)
            ).fetchone():
                raise NotFound("Conversation not found")

    def name(self, tenant, conversation):
        identity = f"{self.database.path.resolve()}:{tenant}:{conversation}"
        return "finance-desktop-" + hashlib.sha256(identity.encode()).hexdigest()[:32]

    def docker_call(self, *args, check=True):
        try:
            result = subprocess.run(
                [self.docker, *args],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise TerminalUnavailable("Docker unavailable") from None
        if check and result.returncode:
            raise TerminalUnavailable("Container operation failed; check Docker and default image")
        return result

    def inspect(self, name):
        result = self.docker_call("inspect", name, check=False)
        if result.returncode:
            return None
        item = json.loads(result.stdout)[0]
        if item["Config"].get("Labels", {}).get("finance.owner") != name:
            raise TerminalUnavailable("Container ownership mismatch")
        return item

    def ensure(self, tenant, conversation):
        self.authorize(tenant, conversation)
        name = self.name(tenant, conversation)
        item = self.inspect(name)
        if item is None:
            result = self.docker_call(
                "run",
                "-d",
                "--name",
                name,
                "--label",
                f"finance.owner={name}",
                "--pull=never",
                "--network=bridge",
                "--publish=127.0.0.1::6080",
                "--shm-size=256m",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user=1000:1000",
                "--cpus=2",
                "--memory=4g",
                "--memory-swap=4g",
                "--pids-limit=256",
                "--tmpfs=/workspace:rw,nosuid,size=512m,uid=1000,gid=1000,mode=0700",
                "--tmpfs=/tmp:rw,nosuid,noexec,size=64m,uid=1000,gid=1000,mode=0700",
                "--workdir=/workspace",
                "--env=HOME=/workspace",
                "--log-driver=none",
                IMAGE,
                check=False,
            )
            if result.returncode and self.inspect(name) is None:
                raise TerminalUnavailable("Default image unavailable; prepare the documented image")
        elif not item["State"]["Running"]:
            self.docker_call("start", name)
        return name

    def status(self, tenant, conversation):
        self.authorize(tenant, conversation)
        item = self.inspect(self.name(tenant, conversation))
        with self.database.connect() as connection:
            history = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM terminal_commands WHERE conversation_id=? "
                    "ORDER BY created_at DESC LIMIT 20",
                    (conversation,),
                )
            ]
        return {
            "connected": bool(item and item["State"]["Running"]),
            "image": "Debian 12 Desktop",
            "cwd": "/workspace",
            "history": history[::-1],
        }

    def begin(self, tenant, conversation, request):
        self.authorize(tenant, conversation)
        with self.database.transaction() as connection:
            stale = connection.execute(
                "SELECT id FROM terminal_commands WHERE conversation_id=? "
                "AND status='running' AND created_at<?",
                (conversation, time.time() - 120),
            ).fetchone()
            if stale:
                self.docker_call("stop", "-t", "1", self.name(tenant, conversation), check=False)
                connection.execute(
                    "UPDATE terminal_commands SET status='interrupted',finished_at=? WHERE id=?",
                    (time.time(), stale["id"]),
                )
            previous = connection.execute(
                "SELECT * FROM terminal_commands WHERE conversation_id=? AND request_id=?",
                (conversation, request.request_id),
            ).fetchone()
            if previous:
                if previous["command"] != request.command:
                    raise Conflict("Request ID reused with a different command")
                if previous["status"] == "running":
                    raise Conflict("Command still running; view terminal history")
                return dict(previous), False
            identifier = str(uuid.uuid4())
            try:
                connection.execute(
                    "INSERT INTO terminal_commands(id,conversation_id,request_id,command,status,"
                    "created_at) VALUES (?,?,?,?,'running',?)",
                    (identifier, conversation, request.request_id, request.command, time.time()),
                )
            except sqlite3.IntegrityError:
                raise Conflict("This conversation already has a running command") from None
        return {"id": identifier}, True

    def update(self, identifier, output, status="running", exit_code=None):
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE terminal_commands SET output=?,status=?,exit_code=?,finished_at=? "
                "WHERE id=?",
                (
                    output,
                    status,
                    exit_code,
                    None if status == "running" else time.time(),
                    identifier,
                ),
            )

    def execute(self, tenant, conversation, request):
        record, fresh = self.begin(tenant, conversation, request)
        if not fresh:
            yield {"type": "output", "text": record["output"], "replayed": True}
            yield {"type": "exit", "exit_code": record["exit_code"], "status": record["status"]}
            return
        identifier = record["id"]
        process = None
        output = ""
        final = "failed"
        code = None
        name = self.name(tenant, conversation)
        try:
            self.ensure(tenant, conversation)
            yield {"type": "start", "id": identifier, "cwd": "/workspace"}
            process = subprocess.Popen(
                [
                    self.docker,
                    "exec",
                    name,
                    "timeout",
                    "--signal=TERM",
                    "--kill-after=2",
                    str(request.timeout_seconds),
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-c",
                    request.command,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            deadline = time.monotonic() + request.timeout_seconds + 3
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if time.monotonic() > deadline:
                        final = "timed_out"
                        break
                    if not selector.select(0.5):
                        yield {"type": "heartbeat"}
                        continue
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        code = process.wait(timeout=2)
                        final = "timed_out" if code in {124, 137} else "completed"
                        break
                    text = decoder.decode(chunk)
                    remaining = OUTPUT_LIMIT - len(output)
                    output += text[:remaining]
                    self.update(identifier, output)
                    yield {"type": "output", "text": text[:remaining]}
                    if len(text) > remaining:
                        final = "output_limit"
                        break
        except (TerminalUnavailable, OSError, subprocess.SubprocessError):
            yield {
                "type": "error",
                "message": "无法连接默认 Linux 环境，请检查服务端 Docker 和镜像。",
            }
        finally:
            if process:
                if process.poll() is None or final in {"timed_out", "output_limit"}:
                    # Stop the sandbox, including detached children, on timeout or disconnect.
                    with suppress(TerminalUnavailable):
                        self.docker_call("stop", "-t", "1", name, check=False)
                if process.poll() is None:
                    process.kill()
                process.wait()
                process.stdout.close()
            self.update(identifier, output, final, code)
        yield {"type": "exit", "exit_code": code, "status": final}

    def invoke(self, tenant, conversation, command, request_id, timeout_seconds=30):
        for _ in self.execute(
            tenant,
            conversation,
            CommandRequest(
                command=command,
                request_id=request_id,
                timeout_seconds=timeout_seconds,
            ),
        ):
            pass
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT output,status,exit_code FROM terminal_commands "
                "WHERE conversation_id=? AND request_id=?",
                (conversation, request_id),
            ).fetchone()
        result = dict(row)
        result["truncated"] = len(result["output"]) > 12000
        result["output"] = result["output"][:12000]
        return result
