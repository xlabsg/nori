CREATE TABLE terminal_commands (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    request_id TEXT NOT NULL,
    command TEXT NOT NULL,
    status TEXT NOT NULL,
    output TEXT NOT NULL DEFAULT '',
    exit_code INTEGER,
    created_at REAL NOT NULL,
    finished_at REAL,
    UNIQUE(conversation_id, request_id)
);
CREATE UNIQUE INDEX terminal_one_running ON terminal_commands(conversation_id) WHERE status='running';
