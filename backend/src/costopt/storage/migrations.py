"""Small, deterministic SQLite migration runner for local and deployment environments."""

import sqlite3
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "data" / "sqlite" / "migrations"


def apply_migrations(connection: sqlite3.Connection) -> list[str]:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        row["version"] if isinstance(row, dict) else row[0]
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    applied_now: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO schema_migrations (version) VALUES (?)", (path.name,))
        applied_now.append(path.name)
    connection.commit()
    return applied_now
