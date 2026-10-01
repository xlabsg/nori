import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=rw",
            timeout=10,
            isolation_level=None,
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def migrate(self, directory: Path):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)"
            )
        for migration in sorted(directory.glob("*.sql")):
            with self.transaction() as connection:
                if connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=?", (migration.name,)
                ).fetchone():
                    continue
                # Migration files deliberately use simple statements without procedural SQL.
                for statement in migration.read_text().split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations VALUES (?)", (migration.name,))
