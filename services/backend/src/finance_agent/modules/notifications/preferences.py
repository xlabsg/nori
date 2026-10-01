import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from finance_agent.modules.analytics.schemas import StrictModel


class Preferences(StrictModel):
    timezone: str = "Asia/Shanghai"
    quiet_enabled: bool = False
    quiet_start: str = Field(default="22:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str = Field(default="08:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    important_contacts: list[str] = Field(default_factory=list, max_length=30)
    alert_criteria: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def check(self):
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown timezone") from None
        if self.quiet_enabled and self.quiet_start == self.quiet_end:
            raise ValueError("Quiet hours must have different start and end")
        if any(len(contact) > 200 for contact in self.important_contacts):
            raise ValueError("Contact too long")
        return self


class PreferenceService:
    def __init__(self, database):
        self.database = database

    def get(self, tenant):
        with self.database.connect() as c:
            row = c.execute(
                "SELECT payload_json FROM assistant_preferences WHERE tenant_id=?", (tenant,)
            ).fetchone()
        return Preferences.model_validate_json(row[0]) if row else Preferences()

    def save(self, tenant, request):
        with self.database.transaction() as c:
            c.execute(
                "INSERT INTO assistant_preferences VALUES (?,?,?) ON CONFLICT(tenant_id) "
                "DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                (tenant, request.model_dump_json(), time.time()),
            )
        return request.model_dump()

    def context(self, tenant):
        return json.dumps(self.get(tenant).model_dump(), ensure_ascii=False)


def next_allowed(preferences, now):
    """Quiet hours defer external delivery; station inbox remains immediate."""
    if not preferences.quiet_enabled:
        return now
    local = datetime.fromtimestamp(now, ZoneInfo(preferences.timezone))
    current = local.hour * 60 + local.minute
    start = sum(
        int(v) * m for v, m in zip(preferences.quiet_start.split(":"), (60, 1), strict=True)
    )
    end = sum(int(v) * m for v, m in zip(preferences.quiet_end.split(":"), (60, 1), strict=True))
    inside = start <= current < end if start < end else current >= start or current < end
    if not inside:
        return now
    finish = local.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
    if finish.timestamp() <= now:
        finish += timedelta(days=1)
    return finish.timestamp()
