import hashlib
import json
import time
import uuid

from finance_agent.adapters.database import Database
from finance_agent.modules.analytics.schemas import TaskCreate

TERMINAL = {"succeeded", "partial", "failed", "cancelled"}


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def new_id():
    return str(uuid.uuid4())


def as_task(row):
    data = dict(row)
    data["input"] = json.loads(data.pop("input_json"))
    result = data.pop("result_json")
    data["result"] = json.loads(result) if result else None
    for key in ("lease_token", "lease_until", "request_hash"):
        data.pop(key)
    return data


class TaskService:
    def __init__(self, database: Database, callback_tenants=()):
        self.database = database
        self.callback_tenants = set(callback_tenants)

    def _event(self, connection, task, kind, now):
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE task_id=?", (task["id"],)
        ).fetchone()[0]
        event_id = new_id()
        payload = {
            "schema_version": 1,
            "event_id": event_id,
            "event_type": kind,
            "task_id": task["id"],
            "run_id": task["id"],
            "sequence": sequence,
            "occurred_at": now,
            "result_ref": f"/api/tasks/{task['id']}",
        }
        connection.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
            (event_id, task["tenant_id"], task["id"], kind, sequence, json.dumps(payload), now),
        )
        if kind.removeprefix("task.") in TERMINAL:
            label = {
                "task.succeeded": "分析完成",
                "task.partial": "部分结果已就绪",
                "task.failed": "任务执行失败",
                "task.cancelled": "任务已取消",
            }[kind]
            connection.execute(
                "INSERT INTO notifications VALUES (?,?,?,?,?,?,NULL)",
                (
                    new_id(),
                    task["tenant_id"],
                    event_id,
                    task["id"],
                    f"{task['name']} · {label}",
                    now,
                ),
            )
        if task["tenant_id"] in self.callback_tenants:
            connection.execute(
                "INSERT INTO deliveries(event_id,tenant_id,next_at,created_at) VALUES (?,?,?,?)",
                (event_id, task["tenant_id"], now, now),
            )

    def _create(self, connection, tenant, request, now, monitor_id=None):
        serialized = request.input.model_dump_json()
        fingerprint = hashlib.sha256(
            json.dumps(
                {"name": request.name, "input": json.loads(serialized)}, sort_keys=True
            ).encode()
        ).hexdigest()
        existing = connection.execute(
            "SELECT * FROM tasks WHERE tenant_id=? AND idempotency_key=?",
            (tenant, request.idempotency_key),
        ).fetchone()
        if existing:
            if existing["request_hash"] != fingerprint:
                raise Conflict("Idempotency key already used for a different request")
            return as_task(existing)
        task_id = new_id()
        connection.execute(
            "INSERT INTO tasks(id,tenant_id,name,idempotency_key,request_hash,input_json,"
            "created_at,updated_at,monitor_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                tenant,
                request.name,
                request.idempotency_key,
                fingerprint,
                serialized,
                now,
                now,
                monitor_id,
            ),
        )
        row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        self._event(connection, row, "task.queued", now)
        return as_task(row)

    def create(self, tenant, request: TaskCreate, now=None):
        with self.database.transaction() as connection:
            return self._create(connection, tenant, request, time.time() if now is None else now)

    def get(self, tenant, task_id):
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE tenant_id=? AND id=?", (tenant, task_id)
            ).fetchone()
            if row is None:
                raise NotFound("Task not found")
            return as_task(row)

    def list(self, tenant):
        with self.database.connect() as connection:
            return [
                as_task(row)
                for row in connection.execute(
                    "SELECT * FROM tasks WHERE tenant_id=? ORDER BY created_at DESC LIMIT 100",
                    (tenant,),
                )
            ]

    def events(self, tenant, task_id):
        self.get(tenant, task_id)
        with self.database.connect() as connection:
            return [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT payload_json FROM events WHERE tenant_id=? AND task_id=? "
                    "ORDER BY sequence",
                    (tenant, task_id),
                )
            ]

    def _cancel(self, connection, row, now):
        if row["status"] not in TERMINAL:
            connection.execute(
                "UPDATE tasks SET status='cancelled',updated_at=?,"
                "lease_token=NULL,lease_until=NULL "
                "WHERE id=?",
                (now, row["id"]),
            )
            self._event(connection, row, "task.cancelled", now)

    def cancel(self, tenant, task_id):
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE tenant_id=? AND id=?", (tenant, task_id)
            ).fetchone()
            if row is None:
                raise NotFound("Task not found")
            self._cancel(connection, row, time.time())
        return self.get(tenant, task_id)

    def claim(self, now=None, lease_seconds=60):
        now = time.time() if now is None else now
        with self.database.transaction() as connection:
            while True:
                row = connection.execute(
                    "SELECT * FROM tasks WHERE status='queued' OR "
                    "(status='running' AND lease_until<=?) ORDER BY created_at LIMIT 1",
                    (now,),
                ).fetchone()
                if row is None:
                    return None
                if row["attempts"] >= 3:
                    connection.execute(
                        "UPDATE tasks SET status='failed',error_code='attempts_exhausted',"
                        "updated_at=?,lease_token=NULL,lease_until=NULL WHERE id=?",
                        (now, row["id"]),
                    )
                    self._event(connection, row, "task.failed", now)
                    continue
                token = new_id()
                connection.execute(
                    "UPDATE tasks SET status='running',lease_token=?,lease_until=?,"
                    "attempts=attempts+1,updated_at=? WHERE id=?",
                    (token, now + lease_seconds, now, row["id"]),
                )
                self._event(connection, row, "task.started", now)
                return {**as_task(row), "lease_token": token, "status": "running"}

    def finish(self, tenant, task_id, lease_token, result=None, error_code=None, now=None):
        now = time.time() if now is None else now
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id=? AND tenant_id=? AND status='running' "
                "AND lease_token=? AND lease_until>?",
                (task_id, tenant, lease_token, now),
            ).fetchone()
            if row is None:
                return False
            if error_code:
                status = "failed"
            elif result and result.get("portfolio", {}).get("complete") is False:
                status = "partial"
            else:
                status = "succeeded"
            connection.execute(
                "UPDATE tasks SET status=?,result_json=?,error_code=?,updated_at=?,"
                "lease_token=NULL,lease_until=NULL WHERE id=?",
                (
                    status,
                    json.dumps(result) if result is not None else None,
                    error_code,
                    now,
                    task_id,
                ),
            )
            self._event(connection, row, f"task.{status}", now)
            return True
