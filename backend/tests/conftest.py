import sqlite3
from pathlib import Path

import pytest

from costopt.config import settings
from scripts.load_synthetic_dataset_to_sqlite import execute_schema, import_tables


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(settings, "db_path", db_path)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        execute_schema(connection)
        import_tables(connection)

    return db_path
