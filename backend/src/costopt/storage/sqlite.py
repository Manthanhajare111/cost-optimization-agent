import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from costopt.config import settings


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
