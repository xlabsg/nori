ALTER TABLE agent_tasks ADD COLUMN reminder_minutes INTEGER NOT NULL DEFAULT 10;
CREATE TABLE assistant_preferences (
    tenant_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE notification_channels (
    tenant_id TEXT PRIMARY KEY, credentials TEXT NOT NULL, generation TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1, updated_at REAL NOT NULL
);
CREATE TABLE notification_outbox (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, generation TEXT NOT NULL,
    text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
    next_at REAL NOT NULL, lease_token TEXT, lease_until REAL, error_code TEXT, sent_at REAL
);
CREATE INDEX notification_outbox_queue ON notification_outbox(status,next_at);
CREATE TABLE calendar_reminder_sent (
    task_id TEXT NOT NULL REFERENCES agent_tasks(id), event_id TEXT NOT NULL,
    starts_at REAL NOT NULL, created_at REAL NOT NULL,
    PRIMARY KEY(task_id,event_id,starts_at)
);
CREATE TABLE service_heartbeats (
    name TEXT PRIMARY KEY, updated_at REAL NOT NULL, pid INTEGER NOT NULL
);
