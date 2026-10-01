CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    input_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    result_json TEXT,
    error_code TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    lease_token TEXT,
    lease_until REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    monitor_id TEXT,
    UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX tasks_queue ON tasks(status, created_at);
CREATE TABLE events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    type TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (task_id, sequence)
);
CREATE TABLE notifications (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE REFERENCES events(id),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    title TEXT NOT NULL,
    created_at REAL NOT NULL,
    read_at REAL
);
CREATE TABLE deliveries (
    event_id TEXT PRIMARY KEY REFERENCES events(id),
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_at REAL NOT NULL,
    created_at REAL NOT NULL,
    lease_token TEXT,
    lease_until REAL,
    last_error TEXT
);
CREATE TABLE monitors (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    next_at REAL NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
