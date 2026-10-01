import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo


def calendar_reminder_result(tasks, run, now=None):
    now = time.time() if now is None else now
    task = run["task"]
    api = tasks.connectors.api(task["tenant_id"], task["connection_id"])
    try:
        events = api.upcoming(now, 86400)
    finally:
        api.close()
    zone = ZoneInfo(json.loads(task["schedule_json"])["timezone"])
    keys, lines = [], []
    with tasks.database.connect() as c:
        for event in events:
            if event["status"] == "cancelled" or not event.get("start", {}).get("dateTime"):
                continue  # All-day entries are not meetings with an exact start time.
            try:
                start = datetime.fromisoformat(event["start"]["dateTime"].replace("Z", "+00:00"))
                stamp = start.timestamp()
            except ValueError:
                continue
            if not stamp - task["reminder_minutes"] * 60 <= now < stamp:
                continue
            if c.execute(
                "SELECT 1 FROM calendar_reminder_sent WHERE task_id=? AND event_id=? AND "
                "starts_at=?",
                (task["id"], event["id"], stamp),
            ).fetchone():
                continue
            keys.append({"id": event["id"], "starts_at": stamp})
            local = start.astimezone(zone).strftime("%m-%d %H:%M")
            details = event.get("location", "")[:300]
            meeting_url = event.get("meeting_url", "")
            if meeting_url.startswith("https://"):
                details += "\n  " + meeting_url
            lines.append(
                f"- {event['title'][:300] or '未命名会议'} · {local}\n  {event['url']}\n  {details}"
            )
    return {
        "notify": bool(keys),
        "text": "会议即将开始：\n\n" + "\n".join(lines) if keys else "没有即将开始的会议。",
        "reminder_keys": keys,
        "checked_at": now,
    }
