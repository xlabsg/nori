from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from finance_agent.modules.analytics.schemas import StrictModel


class Schedule(StrictModel):
    kind: Literal["once", "interval", "daily"]
    timezone: str = "Asia/Shanghai"
    interval_seconds: int | None = Field(default=None, ge=60, le=2592000)
    at: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    run_at: datetime | None = None

    @model_validator(mode="after")
    def check(self):
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown IANA timezone") from None
        if self.kind == "interval" and self.interval_seconds is None:
            raise ValueError("Interval required")
        if self.kind == "daily" and self.at is None:
            raise ValueError("Daily time required")
        if self.kind == "once" and (self.run_at is None or self.run_at.utcoffset() is None):
            raise ValueError("Timezone-aware run_at required")
        return self


class AgentTaskCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=1, max_length=4000)
    mode: Literal["watch", "digest", "prompt", "calendar_reminder"] = "watch"
    connection_id: str | None = None
    resources: list[Literal["gmail", "calendar"]] = Field(
        default_factory=lambda: ["gmail", "calendar"], min_length=1, max_length=2
    )
    schedule: Schedule
    reminder_minutes: int = Field(default=10, ge=1, le=1440)

    @model_validator(mode="after")
    def check(self):
        if self.mode != "prompt" and not self.connection_id:
            raise ValueError("Connect Google before creating this task")
        if self.mode == "calendar_reminder" and (
            self.resources != ["calendar"]
            or self.schedule.kind != "interval"
            or self.schedule.interval_seconds > 300
        ):
            raise ValueError(
                "Calendar reminder requires calendar-only polling every 60–300 seconds"
            )
        return self


class AgentTaskToggle(StrictModel):
    enabled: bool


class TaskIdentifier(StrictModel):
    task_id: str


class AgentTaskUpdate(StrictModel):
    reminder_minutes: int | None = Field(default=None, ge=1, le=1440)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    instruction: str | None = Field(default=None, min_length=1, max_length=4000)
    schedule: Schedule | None = None

    @model_validator(mode="after")
    def check(self):
        if (
            self.name is None
            and self.instruction is None
            and self.schedule is None
            and self.reminder_minutes is None
        ):
            raise ValueError("Specify name, instruction or schedule to update")
        return self


class TaskUpdateArgs(AgentTaskUpdate):
    task_id: str
