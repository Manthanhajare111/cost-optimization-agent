from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from costopt.config import settings
from costopt.storage.local_store import ensure_runtime_directories
from costopt.storage.migrations import apply_migrations


ROOT_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT_DIR / "data" / "sqlite" / "schema.sql"
TABLES_DIR = ROOT_DIR / "data" / "synthetic" / "tables"
DB_PATH = settings.db_path

TABLE_ORDER = [
    "suppliers",
    "locations",
    "squads",
    "categories",
    "users",
    "resources",
    "rate_cards",
    "contracts",
    "purchase_orders",
    "procurement_contracts",
    "contract_clauses",
    "optimization_scenarios",
    "invoices",
    "recommendations",
    "procurement_recommendations",
    "recommendation_evidence",
    "audit_log",
]

JSON_TEXT_FIELDS = {
    "optimization_scenarios": {"assumptions"},
    "audit_log": {"details"},
}

BOOLEAN_FIELDS = {
    "locations": {"is_offshore"},
    "contracts": {"offshore_permitted", "customer_approval_required"},
    "resources": {"pii_access"},
    "procurement_contracts": {"is_preferred_supplier"},
}


def main() -> None:
    ensure_runtime_directories()
    if not TABLES_DIR.exists():
        raise FileNotFoundError(f"Synthetic tables directory not found: {TABLES_DIR}")
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"SQLite schema file not found: {SCHEMA_PATH}")

    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        execute_schema(connection)
        import_tables(connection)
        counts = read_counts(connection)

    print(json.dumps({"db_path": str(DB_PATH), "table_counts": counts}, indent=2))


def execute_schema(connection: sqlite3.Connection) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema_sql)
    connection.commit()


def import_tables(connection: sqlite3.Connection) -> None:
    for table_name in TABLE_ORDER:
        rows = load_rows(table_name)
        if not rows:
            continue
        insert_rows(connection, table_name, rows)
    apply_migrations(connection)
    connection.commit()


def load_rows(table_name: str) -> list[dict]:
    path = TABLES_DIR / f"{table_name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Table seed file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def insert_rows(connection: sqlite3.Connection, table_name: str, rows: list[dict]) -> None:
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    sql = f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})"

    payload = []
    for row in rows:
        payload.append(tuple(normalize_value(table_name, column, row.get(column)) for column in columns))

    connection.executemany(sql, payload)


def normalize_value(table_name: str, column_name: str, value: object) -> object:
    if value is None:
        return None

    if column_name in JSON_TEXT_FIELDS.get(table_name, set()):
        return json.dumps(value)

    if column_name in BOOLEAN_FIELDS.get(table_name, set()):
        return int(bool(value))

    return value


def read_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in TABLE_ORDER:
        counts[table_name] = connection.execute(
            f"SELECT COUNT(*) AS row_count FROM {table_name}"
        ).fetchone()["row_count"]
    return counts


if __name__ == "__main__":
    main()
