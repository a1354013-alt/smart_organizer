from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SQLiteTarget = str | os.PathLike[str]


def sqlite_target_string(target: SQLiteTarget) -> str:
    return os.fspath(target)


def is_sqlite_uri(target: SQLiteTarget) -> bool:
    return sqlite_target_string(target).startswith("file:")


def is_sqlite_memory_target(target: SQLiteTarget) -> bool:
    raw_target = sqlite_target_string(target)
    return raw_target == ":memory:" or (is_sqlite_uri(raw_target) and "mode=memory" in raw_target)


def is_physical_sqlite_path(target: SQLiteTarget) -> bool:
    return not is_sqlite_uri(target) and sqlite_target_string(target) != ":memory:"


def physical_sqlite_path(target: SQLiteTarget) -> Path:
    return Path(sqlite_target_string(target))


def connect_sqlite(target: SQLiteTarget, **kwargs: Any) -> sqlite3.Connection:
    """Return an open caller-owned SQLite connection."""
    raw_target = sqlite_target_string(target)
    return sqlite3.connect(raw_target, uri=is_sqlite_uri(raw_target), **kwargs)


@contextmanager
def open_sqlite(target: SQLiteTarget, **kwargs: Any) -> Iterator[sqlite3.Connection]:
    """Open and always close a short-lived SQLite connection."""
    conn = connect_sqlite(target, **kwargs)
    try:
        yield conn
    finally:
        conn.close()
