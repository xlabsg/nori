from concurrent.futures import ThreadPoolExecutor

import pytest

from finance_agent.entrypoints.worker import work_once
from finance_agent.modules.analytics.schemas import MonitorCreate, TaskCreate
from finance_agent.modules.monitors.service import MonitorService
from finance_agent.modules.notifications.service import NotificationService
from finance_agent.modules.tasks.service import Conflict, NotFound


def request(input_data, key="one"):
    return TaskCreate(name="Test analysis", idempotency_key=key, input=input_data)


def test_idempotency_conflict_and_isolation(tasks, input_data):
    first = tasks.create("a", request(input_data))
    assert tasks.create("a", request(input_data))["id"] == first["id"]
    input_data["closing_equity"] = "0"
    with pytest.raises(Conflict):
        tasks.create("a", request(input_data))
    with pytest.raises(NotFound):
        tasks.get("b", first["id"])
    assert tasks.list("b") == []


def test_worker_result_and_single_notification(tasks, database, input_data):
    task = tasks.create("a", request(input_data))
    assert work_once(tasks)
    assert not work_once(tasks)
    result = tasks.get("a", task["id"])
    assert result["status"] == "succeeded"
    assert result["result"]["equity"]["profit"] == "500"
    assert [event["event_type"] for event in tasks.events("a", task["id"])] == [
        "task.queued",
        "task.started",
        "task.succeeded",
    ]
    assert len(NotificationService(database).list("a")) == 1


def test_expired_lease_fences_old_worker(tasks, input_data):
    task = tasks.create("a", request(input_data), now=100)
    old = tasks.claim(now=101, lease_seconds=10)
    new = tasks.claim(now=112)
    assert old["lease_token"] != new["lease_token"]
    assert not tasks.finish("a", task["id"], old["lease_token"], result={}, now=113)
    assert tasks.finish("a", task["id"], new["lease_token"], result={}, now=113)
    assert not tasks.finish("a", task["id"], new["lease_token"], result={}, now=114)


def test_cancel_prevents_result_publication(tasks, database, input_data):
    task = tasks.create("a", request(input_data))
    job = tasks.claim()
    tasks.cancel("a", task["id"])
    tasks.cancel("a", task["id"])
    assert not tasks.finish("a", task["id"], job["lease_token"], result={})
    assert tasks.get("a", task["id"])["status"] == "cancelled"
    assert len(NotificationService(database).list("a")) == 1


def test_concurrent_workers_claim_only_once(tasks, input_data):
    tasks.create("a", request(input_data))
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: tasks.claim(), range(2)))
    assert sum(job is not None for job in claimed) == 1


def test_exhausted_crash_recovery(tasks, input_data):
    task = tasks.create("a", request(input_data), now=0)
    for now in (0, 61, 122):
        assert tasks.claim(now=now)
    assert tasks.claim(now=183) is None
    assert tasks.get("a", task["id"])["error_code"] == "attempts_exhausted"


def test_monitor_catchup_dedupe_and_pause(tasks, input_data):
    monitors = MonitorService(tasks)
    monitor_id = monitors.create(
        "a", MonitorCreate(name="Periodic", interval_seconds=60, input=input_data), now=100
    )
    assert monitors.tick(now=1000) == 1
    assert monitors.tick(now=1000) == 0
    assert len(tasks.list("a")) == 1
    job = tasks.claim(now=1001)
    monitors.set_enabled("a", monitor_id, False)
    assert not tasks.finish("a", job["id"], job["lease_token"], result={})
    assert monitors.tick(now=2000) == 0
    with pytest.raises(NotFound):
        monitors.set_enabled("b", monitor_id, True)
