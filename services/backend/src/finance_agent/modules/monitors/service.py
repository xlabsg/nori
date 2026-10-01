import json
import time

from finance_agent.modules.analytics.schemas import TaskCreate
from finance_agent.modules.tasks.service import NotFound, new_id


class MonitorService:
    def __init__(self, tasks):
        self.tasks = tasks
        self.database = tasks.database

    def create(self, tenant, request, now=None):
        now = time.time() if now is None else now
        with self.database.transaction() as connection:
            monitor_id = new_id()
            connection.execute(
                "INSERT INTO monitors VALUES (?,?,?,?,?,?,1,?)",
                (
                    monitor_id,
                    tenant,
                    request.name,
                    request.input.model_dump_json(),
                    request.interval_seconds,
                    now,
                    now,
                ),
            )
        return monitor_id

    def list(self, tenant):
        with self.database.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT id,name,interval_seconds,next_at,enabled,created_at FROM monitors "
                    "WHERE tenant_id=? ORDER BY created_at DESC LIMIT 100",
                    (tenant,),
                )
            ]

    def set_enabled(self, tenant, monitor_id, enabled):
        with self.database.transaction() as connection:
            monitor = connection.execute(
                "SELECT * FROM monitors WHERE tenant_id=? AND id=?", (tenant, monitor_id)
            ).fetchone()
            if monitor is None:
                raise NotFound("Monitor not found")
            now = time.time()
            connection.execute(
                "UPDATE monitors SET enabled=?,next_at=? WHERE id=?",
                (int(enabled), now if enabled else monitor["next_at"], monitor_id),
            )
            if not enabled:
                for row in connection.execute(
                    "SELECT * FROM tasks WHERE monitor_id=? AND tenant_id=? "
                    "AND status IN ('queued','running')",
                    (monitor_id, tenant),
                ).fetchall():
                    self.tasks._cancel(connection, row, now)

    def tick(self, now=None):
        now = time.time() if now is None else now
        count = 0
        with self.database.transaction() as connection:
            due = connection.execute(
                "SELECT * FROM monitors WHERE enabled=1 AND next_at<=? ORDER BY next_at LIMIT 100",
                (now,),
            ).fetchall()
            for monitor in due:
                # One catch-up run; skip missed intervals, never create an unbounded backlog.
                request = TaskCreate.model_validate(
                    {
                        "name": monitor["name"],
                        "idempotency_key": f"{monitor['id']}:{monitor['next_at']}",
                        "input": json.loads(monitor["input_json"]),
                    }
                )
                self.tasks._create(connection, monitor["tenant_id"], request, now, monitor["id"])
                connection.execute(
                    "UPDATE monitors SET next_at=? WHERE id=?",
                    (now + monitor["interval_seconds"], monitor["id"]),
                )
                count += 1
        return count
