import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from finance_agent.modules.connectors.google import ConnectorError
from finance_agent.modules.tasks.agent_schemas import Schedule
from finance_agent.modules.tasks.service import Conflict, NotFound


def next_occurrence(schedule, now, initial=False):
    schedule = Schedule.model_validate(schedule)
    if schedule.kind == "once":
        return max(schedule.run_at.timestamp(), now) if initial else None
    if schedule.kind == "interval":
        return now if initial else now + schedule.interval_seconds
    zone = ZoneInfo(schedule.timezone)
    local = datetime.fromtimestamp(now, zone)
    hour, minute = map(int, schedule.at.split(":"))
    for offset in range(370):
        candidate = (local + timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0, fold=0
        )
        stamp = candidate.timestamp()
        # Skip nonexistent DST wall times; choose only the first fold of a repeated time.
        roundtrip = datetime.fromtimestamp(stamp, zone)
        if roundtrip.hour == hour and roundtrip.minute == minute and stamp > now:
            return stamp
    raise ValueError("Unable to schedule daily task")


class AgentTaskService:
    def __init__(self, database, connectors, callbacks=None):
        self.database = database
        self.connectors = connectors
        self.callbacks = callbacks or {}

    def create(self, tenant, conversation, request, key):
        payload = request.model_dump(mode="json")
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        now = time.time()
        if request.connection_id:
            self.connectors.get(tenant, request.connection_id)
        with self.database.transaction() as c:
            if not c.execute(
                "SELECT 1 FROM conversations WHERE id=? AND tenant_id=?", (conversation, tenant)
            ).fetchone():
                raise NotFound("Conversation not found")
            if (
                request.connection_id
                and not c.execute(
                    "SELECT 1 FROM connections WHERE id=? AND tenant_id=? AND status='connected'",
                    (request.connection_id, tenant),
                ).fetchone()
            ):
                raise ConnectorError("needs_reconnect")
            existing = c.execute(
                "SELECT * FROM agent_tasks WHERE tenant_id=? AND idempotency_key=?", (tenant, key)
            ).fetchone()
            if existing:
                if (
                    existing["request_hash"] != fingerprint
                    or existing["conversation_id"] != conversation
                ):
                    raise Conflict("Task request reused with different content")
                return self.view(existing)
            identifier = str(uuid.uuid4())
            c.execute(
                "INSERT INTO agent_tasks(id,tenant_id,conversation_id,name,instruction,mo"
                "de,connection_id,resources_json,schedule_json,status,next_at,created_at,"
                "idempotency_key,request_hash,reminder_minutes) VALUES "
                "(?,?,?,?,?,?,?,?,?,'enabled',?,?,?,?,?)",
                (
                    identifier,
                    tenant,
                    conversation,
                    request.name,
                    request.instruction,
                    request.mode,
                    request.connection_id,
                    json.dumps(request.resources),
                    json.dumps(payload["schedule"]),
                    next_occurrence(payload["schedule"], now, True),
                    now,
                    key,
                    fingerprint,
                    request.reminder_minutes,
                ),
            )
            return self.view(
                c.execute("SELECT * FROM agent_tasks WHERE id=?", (identifier,)).fetchone()
            )

    @staticmethod
    def view(row):
        result = dict(row)
        result["resources"] = json.loads(result.pop("resources_json"))
        result["schedule"] = json.loads(result.pop("schedule_json"))
        for key in ("tenant_id", "idempotency_key", "request_hash"):
            result.pop(key, None)
        return result

    def list(self, tenant, conversation=None):
        with self.database.connect() as c:
            rows = c.execute(
                "SELECT * FROM agent_tasks WHERE tenant_id=? AND (? IS NULL OR "
                "conversation_id=?) ORDER BY created_at DESC LIMIT 100",
                (tenant, conversation, conversation),
            ).fetchall()
            result = []
            for row in rows:
                item = self.view(row)
                run = c.execute(
                    "SELECT id,status,attempts,occurrence,result_json,error_code,finished"
                    "_at FROM agent_task_runs WHERE task_id=? ORDER BY created_at DESC "
                    "LIMIT 1",
                    (row["id"],),
                ).fetchone()
                item["last_run"] = dict(run) if run else None
                if run:
                    item["last_run"]["result"] = json.loads(
                        item["last_run"].pop("result_json") or "null"
                    )
                result.append(item)
            return result

    def get(self, tenant, identifier):
        with self.database.connect() as c:
            row = c.execute(
                "SELECT * FROM agent_tasks WHERE id=? AND tenant_id=?", (identifier, tenant)
            ).fetchone()
        if not row:
            raise NotFound("Agent task not found")
        return dict(row)

    def toggle(self, tenant, identifier, enabled):
        row = self.get(tenant, identifier)
        if enabled and row["status"] in {"completed", "cancelled"}:
            raise Conflict("Completed one-off task cannot be resumed")
        if enabled and row["connection_id"]:
            self.connectors.get(tenant, row["connection_id"])
        with self.database.transaction() as c:
            if (
                enabled
                and row["connection_id"]
                and not c.execute(
                    "SELECT 1 FROM connections WHERE id=? AND tenant_id=? AND status='connected'",
                    (row["connection_id"], tenant),
                ).fetchone()
            ):
                raise ConnectorError("needs_reconnect")
            c.execute(
                "UPDATE agent_tasks SET status=?,next_at=?,error_code=NULL WHERE id=? "
                "AND tenant_id=?",
                (
                    "enabled" if enabled else "paused",
                    next_occurrence(json.loads(row["schedule_json"]), time.time(), True)
                    if enabled
                    else None,
                    identifier,
                    tenant,
                ),
            )
            if enabled and json.loads(row["schedule_json"])["kind"] == "once":
                c.execute(
                    "UPDATE agent_task_runs SET status='queued',attempts=0,next_at=?,"
                    "lease_token=NULL,lease_until=NULL,finished_at=NULL WHERE task_id=? "
                    "AND status='cancelled'",
                    (time.time(), identifier),
                )
            if not enabled:
                c.execute(
                    "UPDATE agent_task_runs SET status='cancelled',lease_token=NULL,lease"
                    "_until=NULL,finished_at=? WHERE task_id=? AND status IN "
                    "('queued','retrying','running')",
                    (time.time(), identifier),
                )
        return {"id": identifier, "enabled": enabled}

    def cancel(self, tenant, identifier):
        self.toggle(tenant, identifier, False)
        with self.database.transaction() as c:
            c.execute(
                "UPDATE agent_tasks SET status='cancelled',next_at=NULL WHERE id=? AND tenant_id=?",
                (identifier, tenant),
            )
        return {"id": identifier, "status": "cancelled"}

    def update(self, tenant, identifier, request):
        self.get(tenant, identifier)
        with self.database.transaction() as c:
            row = c.execute(
                "SELECT * FROM agent_tasks WHERE id=? AND tenant_id=?", (identifier, tenant)
            ).fetchone()
            if row["status"] in {"completed", "cancelled"}:
                raise Conflict("Completed or cancelled task cannot be edited")
            schedule = (
                request.schedule.model_dump(mode="json")
                if request.schedule
                else json.loads(row["schedule_json"])
            )
            if row["mode"] == "calendar_reminder" and (
                schedule["kind"] != "interval" or schedule["interval_seconds"] > 300
            ):
                raise ValueError("Meeting reminder polling must stay within 60–300 seconds")
            c.execute(
                "UPDATE agent_tasks SET "
                "name=?,instruction=?,schedule_json=?,next_at=?,reminder_minutes=?,"
                "error_code=NULL WHERE "
                "id=?",
                (
                    request.name or row["name"],
                    request.instruction or row["instruction"],
                    json.dumps(schedule),
                    next_occurrence(schedule, time.time(), True)
                    if row["status"] == "enabled"
                    else None,
                    request.reminder_minutes
                    if request.reminder_minutes is not None
                    else row["reminder_minutes"],
                    identifier,
                ),
            )
            c.execute(
                "UPDATE agent_task_runs SET "
                "status='cancelled',lease_token=NULL,lease_until=NULL,finished_at=? "
                "WHERE task_id=? AND status IN ('queued','retrying','running')",
                (time.time(), identifier),
            )
            return self.view(
                c.execute("SELECT * FROM agent_tasks WHERE id=?", (identifier,)).fetchone()
            )

    def runs(self, tenant, identifier):
        self.get(tenant, identifier)
        with self.database.connect() as c:
            rows = [
                dict(r)
                for r in c.execute(
                    "SELECT id,occurrence,status,attempts,result_json,error_code,created_"
                    "at,finished_at FROM agent_task_runs WHERE task_id=? ORDER BY "
                    "created_at DESC LIMIT 50",
                    (identifier,),
                )
            ]
        for row in rows:
            row["result"] = json.loads(row.pop("result_json") or "null")
        return rows

    def run_now(self, tenant, identifier):
        self.get(tenant, identifier)
        now = time.time()
        with self.database.transaction() as c:
            task = c.execute(
                "SELECT * FROM agent_tasks WHERE id=? AND tenant_id=?", (identifier, tenant)
            ).fetchone()
            if task["status"] != "enabled":
                raise Conflict("Resume the task before running it")
            existing = c.execute(
                "SELECT id FROM agent_task_runs WHERE task_id=? "
                "AND status IN ('queued','retrying','running')",
                (identifier,),
            ).fetchone()
            if existing:
                return {"run_id": existing[0], "queued": True}
            run_id = str(uuid.uuid4())
            c.execute(
                "INSERT INTO agent_task_runs(id,task_id,occurrence,status,next_at,created_at) "
                "VALUES (?,?,?,'queued',?,?)",
                (run_id, identifier, now, now, now),
            )
            return {"run_id": run_id, "queued": True}

    def tick(self, now=None):
        now = time.time() if now is None else now
        with self.database.transaction() as c:
            due = c.execute(
                "SELECT * FROM agent_tasks WHERE status='enabled' AND next_at<=? ORDER "
                "BY next_at LIMIT 100",
                (now,),
            ).fetchall()
            count = 0
            for task in due:
                if c.execute(
                    "SELECT 1 FROM agent_task_runs WHERE task_id=? AND status IN "
                    "('queued','retrying','running')",
                    (task["id"],),
                ).fetchone():
                    continue
                c.execute(
                    "INSERT OR IGNORE INTO agent_task_runs(id,task_id,occurrence,status,n"
                    "ext_at,created_at) VALUES (?,?,?,'queued',?,?)",
                    (str(uuid.uuid4()), task["id"], task["next_at"], now, now),
                )
                following = next_occurrence(json.loads(task["schedule_json"]), now)
                c.execute("UPDATE agent_tasks SET next_at=? WHERE id=?", (following, task["id"]))
                count += 1
        return count

    def claim(self, now=None):
        now = time.time() if now is None else now
        with self.database.transaction() as c:
            c.execute(
                "UPDATE agent_task_runs SET status='failed',error_code='lease_expired',fi"
                "nished_at=? WHERE status='running' AND lease_until<? AND attempts>=3",
                (now, now),
            )
            row = c.execute(
                "SELECT r.* FROM agent_task_runs r JOIN agent_tasks t ON t.id=r.task_id "
                "WHERE t.status='enabled' AND r.attempts<3 AND ((r.status IN "
                "('queued','retrying') AND r.next_at<=?) OR (r.status='running' AND "
                "r.lease_until<?)) ORDER BY r.created_at LIMIT 1",
                (now, now),
            ).fetchone()
            if not row:
                return None
            lease = secrets.token_hex(16)
            c.execute(
                "UPDATE agent_task_runs SET status='running',lease_token=?,lease_until=?,"
                "attempts=attempts+1 WHERE id=?",
                (lease, now + 180, row["id"]),
            )
            run = dict(
                c.execute("SELECT * FROM agent_task_runs WHERE id=?", (row["id"],)).fetchone()
            )
            run["task"] = dict(
                c.execute("SELECT * FROM agent_tasks WHERE id=?", (row["task_id"],)).fetchone()
            )
            return run

    def assert_active(self, run, connection=None):
        def check(c):
            row = c.execute(
                "SELECT 1 FROM agent_task_runs r JOIN agent_tasks t ON t.id=r.task_id "
                "WHERE r.id=? AND r.status='running' AND r.lease_token=? AND "
                "r.lease_until>? AND t.status='enabled'",
                (run["id"], run["lease_token"], time.time()),
            ).fetchone()
            if not row:
                raise Conflict("Task cancelled or lease expired")
            if run["task"]["connection_id"]:
                if not c.execute(
                    "SELECT 1 FROM connections WHERE id=? AND tenant_id=? AND status='connected'",
                    (run["task"]["connection_id"], run["task"]["tenant_id"]),
                ).fetchone():
                    raise Conflict("Connection disconnected")

        if connection is not None:
            check(connection)
        else:
            with self.database.connect() as c:
                check(c)

    def heartbeat(self, run):
        with self.database.transaction() as c:
            c.execute(
                "UPDATE agent_task_runs SET lease_until=? WHERE id=? AND lease_token=? "
                "AND status='running'",
                (time.time() + 180, run["id"], run["lease_token"]),
            )

    def batch(self, run):
        task = run["task"]
        with self.database.transaction() as c:
            self.assert_active(run, c)
            assigned = c.execute(
                "SELECT ch.* FROM connector_changes ch JOIN agent_task_batches b ON "
                "b.change_id=ch.id WHERE b.run_id=? ORDER BY ch.id",
                (run["id"],),
            ).fetchall()
            if not assigned:
                changes = c.execute(
                    "SELECT ch.* FROM connector_changes ch WHERE ch.connection_id=? AND "
                    "NOT EXISTS (SELECT 1 FROM agent_task_consumed done WHERE "
                    "done.task_id=? AND done.change_id=ch.id) ORDER BY ch.id LIMIT 500",
                    (task["connection_id"], task["id"]),
                ).fetchall()
                resources = set(json.loads(task["resources_json"]))
                for change in changes:
                    data = json.loads(change["payload_json"])
                    timestamp = data.get("received_at", 0)
                    if change["resource"] == "calendar":
                        try:
                            timestamp = datetime.fromisoformat(
                                data.get("updated", "").replace("Z", "+00:00")
                            ).timestamp()
                        except ValueError:
                            timestamp = 0
                    if change["resource"] not in resources or timestamp < task["created_at"]:
                        c.execute(
                            "INSERT OR IGNORE INTO agent_task_consumed VALUES (?,?)",
                            (task["id"], change["id"]),
                        )
                        continue
                    if len(assigned) >= 30:
                        break
                    c.execute(
                        "INSERT INTO agent_task_batches VALUES (?,?)", (run["id"], change["id"])
                    )
                    assigned.append(change)
            return [
                {"resource": row["resource"], **json.loads(row["payload_json"])} for row in assigned
            ]

    def finish(self, run, result):
        task = run["task"]
        now = time.time()
        with self.database.transaction() as c:
            self.assert_active(run, c)
            c.execute(
                "UPDATE agent_task_runs SET status='succeeded',result_json=?,finished_at="
                "?,lease_token=NULL,lease_until=NULL,error_code=NULL WHERE id=?",
                (json.dumps(result), now, run["id"]),
            )
            c.execute(
                "INSERT OR IGNORE INTO agent_task_consumed SELECT ?,change_id FROM "
                "agent_task_batches WHERE run_id=?",
                (task["id"], run["id"]),
            )
            status = (
                "completed" if json.loads(task["schedule_json"])["kind"] == "once" else "enabled"
            )
            c.execute(
                "UPDATE agent_tasks SET last_success_at=?,error_code=NULL,status=? WHERE id=?",
                (now, status, task["id"]),
            )
            if task["tenant_id"] in self.callbacks:
                payload = {
                    "event_id": run["id"],
                    "type": "agent_task.completed",
                    "task_id": task["id"],
                    "conversation_id": task["conversation_id"],
                    "result": result,
                    "created_at": now,
                }
                c.execute(
                    "INSERT INTO agent_deliveries(event_id,tenant_id,payload_json,next_at"
                    ",created_at) VALUES (?,?,?,?,?)",
                    (run["id"], task["tenant_id"], json.dumps(payload), now, now),
                )
            for event in result.get("reminder_keys", []):
                c.execute(
                    "INSERT OR IGNORE INTO calendar_reminder_sent VALUES (?,?,?,?)",
                    (task["id"], event["id"], event["starts_at"], now),
                )
            if result.get("notify") and result.get("text"):
                self.publish(c, run, result["text"], now)

    def publish(self, c, run, text, now):
        task = run["task"]
        chat_run = "background:" + run["id"]
        c.execute(
            "INSERT OR IGNORE INTO chat_runs VALUES (?,?,?,?,?,?)",
            (chat_run, task["conversation_id"], chat_run, run["id"], "completed", now),
        )
        c.execute(
            "INSERT INTO chat_events(conversation_id,run_id,type,payload_json,cre"
            "ated_at) VALUES (?,?,'assistant',?,?)",
            (
                task["conversation_id"],
                chat_run,
                json.dumps(
                    {
                        "text": f"**后台任务 · {task['name']}**\n\n" + text,
                        "agent_task_id": task["id"],
                    }
                ),
                now,
            ),
        )
        notification_id = str(uuid.uuid4())
        c.execute(
            "INSERT INTO agent_notifications VALUES (?,?,?,?,?,?,NULL)",
            (
                notification_id,
                task["tenant_id"],
                task["id"],
                run["id"],
                task["name"],
                now,
            ),
        )
        from finance_agent.modules.notifications.telegram import TelegramService

        TelegramService.enqueue(
            c, task["tenant_id"], notification_id, task["name"] + "\n\n" + text, now
        )
        c.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?",
            (now, task["conversation_id"]),
        )

    def fail(self, run, code, retry_after=30):
        with self.database.transaction() as c:
            row = c.execute(
                "SELECT 1 FROM agent_task_runs WHERE id=? AND lease_token=? AND status='running'",
                (run["id"], run["lease_token"]),
            ).fetchone()
            if not row:
                return
            terminal = run["attempts"] >= 3 or code in {
                "needs_reconnect",
                "permission_denied",
                "cancelled",
            }
            c.execute(
                "UPDATE agent_task_runs SET status=?,error_code=?,next_at=?,finished_at=?"
                ",lease_token=NULL,lease_until=NULL WHERE id=?",
                (
                    "failed" if terminal else "retrying",
                    code,
                    time.time() + retry_after * 2 ** (run["attempts"] - 1),
                    time.time() if terminal else None,
                    run["id"],
                ),
            )
            c.execute("UPDATE agent_tasks SET error_code=? WHERE id=?", (code, run["task_id"]))
            if terminal and code != "cancelled":
                self.publish(
                    c,
                    run,
                    "任务未完成：" + code + "。请在任务记录中查看状态或重新连接账号。",
                    time.time(),
                )
