CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    active_run TEXT,
    lease_until REAL,
    transcript_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX conversations_tenant ON conversations(tenant_id, updated_at);
CREATE TABLE chat_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    request_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(conversation_id, request_id)
);
CREATE TABLE chat_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    run_id TEXT NOT NULL REFERENCES chat_runs(id),
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE conversation_tasks (
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    PRIMARY KEY(conversation_id, task_id)
);
