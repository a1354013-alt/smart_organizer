from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from storage_db_schema import (
    CURRENT_SCHEMA_VERSION,
    SchemaStatus,
    inspect_database_schema,
    upgrade_database_schema,
)


def _create_schema_db(path: Path, version: str | None) -> None:
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE sys_config(key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute(
            """
            CREATE TABLE files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT,
                file_hash TEXT UNIQUE,
                created_at TEXT
            )
            """
        )
        cursor.execute("CREATE TABLE tags (tag_id INTEGER PRIMARY KEY AUTOINCREMENT, tag_name TEXT UNIQUE)")
        cursor.execute("CREATE TABLE file_tags (file_id INTEGER, tag_id INTEGER, confidence REAL)")
        cursor.execute(
            """
            CREATE VIRTUAL TABLE file_content_fts USING fts5(
                original_filename,
                title,
                summary,
                content,
                tokenize='unicode61'
            )
            """
        )
        if version is not None:
            cursor.execute("INSERT INTO sys_config(key, value) VALUES('schema_version', ?)", (version,))
        conn.commit()


@pytest.mark.parametrize("legacy_version", ["1", "13", "15", str(CURRENT_SCHEMA_VERSION)])
def test_upgrade_database_schema_accepts_supported_versions(tmp_path: Path, legacy_version: str):
    db_path = tmp_path / "legacy.db"
    _create_schema_db(db_path, legacy_version)

    version = upgrade_database_schema(db_path)
    inspection = inspect_database_schema(db_path)

    assert version == CURRENT_SCHEMA_VERSION
    assert inspection.status == SchemaStatus.VALID
    assert inspection.version == CURRENT_SCHEMA_VERSION


@pytest.mark.parametrize("version", [None, "", "bogus", str(CURRENT_SCHEMA_VERSION + 1)])
def test_upgrade_database_schema_rejects_missing_invalid_and_future_versions(tmp_path: Path, version: str | None):
    db_path = tmp_path / "bad.db"
    _create_schema_db(db_path, version)

    with pytest.raises(RuntimeError):
        upgrade_database_schema(db_path)


def test_inspect_database_schema_flags_missing_schema_version(tmp_path: Path):
    db_path = tmp_path / "missing.db"
    _create_schema_db(db_path, None)

    inspection = inspect_database_schema(db_path)

    assert inspection.status == SchemaStatus.MISSING
    assert inspection.version is None
