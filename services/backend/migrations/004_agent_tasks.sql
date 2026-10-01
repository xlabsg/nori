CREATE TABLE connections (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, provider TEXT NOT NULL,
    account TEXT NOT NULL, status TEXT NOT NULL, scopes_json TEXT NOT NULL,
    credentials TEXT NOT NULL, created_at REAL NOT NULL, last_sync_at REAL,
    UNIQUE(tenant_id, provider, account)
);
CREATE TABLE oauth_requests (
    state_hash TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, browser_hash TEXT NOT NULL,
    verifier TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE connector_cursors (
    connection_id TEXT NOT NULL REFERENCES connections(id), resource TEXT NOT NULL,
    cursor TEXT NOT NULL, updated_at REAL NOT NULL,
    PRIMARY KEY(connection_id, resource)
);
CREATE TABLE connector_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, connection_id TEXT NOT NULL REFERENCES connections(id),
    resource TEXT NOT NULL, external_id TEXT NOT NULL, version TEXT NOT NULL,
    payload_json TEXT NOT NULL, created_at REAL NOT NULL,
    UNIQUE(connection_id, resource, external_id, version)
);
CREATE TABLE agent_tasks (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, conversation_id TEXT NOT NULL REFERENCES conversations(id),
    name TEXT NOT NULL, instruction TEXT NOT NULL, mode TEXT NOT NULL,
    connection_id TEXT REFERENCES connections(id), resources_json TEXT NOT NULL,
    schedule_json TEXT NOT NULL, status TEXT NOT NULL, next_at REAL,
    last_success_at REAL, error_code TEXT, created_at REAL NOT NULL,
    idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, UNIQUE(tenant_id, idempotency_key)
);
CREATE TABLE agent_task_runs (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES agent_tasks(id), occurrence REAL NOT NULL,
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL,
    lease_token TEXT, lease_until REAL, result_json TEXT, error_code TEXT,
    created_at REAL NOT NULL, finished_at REAL, UNIQUE(task_id, occurrence)
);
CREATE TABLE agent_task_consumed (
    task_id TEXT NOT NULL REFERENCES agent_tasks(id), change_id INTEGER NOT NULL REFERENCES connector_changes(id),
    PRIMARY KEY(task_id, change_id)
);
CREATE TABLE agent_task_batches (
    run_id TEXT NOT NULL REFERENCES agent_task_runs(id), change_id INTEGER NOT NULL REFERENCES connector_changes(id),
    PRIMARY KEY(run_id, change_id)
);
CREATE TABLE agent_notifications (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES agent_tasks(id),
    run_id TEXT NOT NULL UNIQUE REFERENCES agent_task_runs(id), title TEXT NOT NULL,
    created_at REAL NOT NULL, read_at REAL
);
CREATE INDEX agent_runs_queue ON agent_task_runs(status,next_at);
ALTER TABLE connections ADD COLUMN sync_lease TEXT;
ALTER TABLE connections ADD COLUMN sync_until REAL;
CREATE TABLE agent_deliveries (
    event_id TEXT PRIMARY KEY REFERENCES agent_task_runs(id), tenant_id TEXT NOT NULL,
    payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
    next_at REAL NOT NULL, created_at REAL NOT NULL, lease_token TEXT, lease_until REAL, last_error TEXT
);
