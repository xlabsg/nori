import os
import threading
import time
from contextlib import contextmanager


@contextmanager
def service_heartbeat(database, name):
    stop = threading.Event()

    def beat():
        while not stop.is_set():
            with database.transaction() as c:
                c.execute(
                    "INSERT INTO service_heartbeats VALUES (?,?,?) ON CONFLICT(name) DO UPDATE "
                    "SET updated_at=excluded.updated_at,pid=excluded.pid",
                    (name, time.time(), os.getpid()),
                )
            stop.wait(10)

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def service_status(database):
    with database.connect() as c:
        rows = {r["name"]: dict(r) for r in c.execute("SELECT * FROM service_heartbeats")}
    return [
        {
            "name": name,
            "healthy": bool(rows.get(name) and time.time() - rows[name]["updated_at"] < 45),
            "last_seen_at": rows.get(name, {}).get("updated_at"),
        }
        for name in ("worker", "scheduler")
    ]
