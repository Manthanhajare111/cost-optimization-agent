from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from costopt.config import settings
from costopt.storage.migrations import apply_migrations

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


def dict_row_factory(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> dict[str, object]:
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(settings.db_path)
    connection.row_factory = dict_row_factory
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        connection.close()


def execute_schema(connection: sqlite3.Connection) -> None:
    schema_path = settings.data_dir / "sqlite" / "schema.sql"
    if schema_path.exists():
        schema_sql = schema_path.read_text(encoding="utf-8")
        connection.executescript(schema_sql)
        connection.commit()


def import_tables(connection: sqlite3.Connection) -> None:
    tables_dir = settings.data_dir / "synthetic" / "tables"
    for table_name in TABLE_ORDER:
        path = tables_dir / f"{table_name}.json"
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not rows:
            continue
        columns = list(rows[0].keys())
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        sql = f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})"
        payload = [
            tuple(_normalize_value(table_name, col, row.get(col)) for col in columns)
            for row in rows
        ]
        connection.executemany(sql, payload)
    apply_migrations(connection)
    connection.commit()


def _normalize_value(table_name: str, column_name: str, value: object) -> object:
    if value is None:
        return None
    if column_name in JSON_TEXT_FIELDS.get(table_name, set()):
        return json.dumps(value)
    if column_name in BOOLEAN_FIELDS.get(table_name, set()):
        return int(bool(value))
    return value
