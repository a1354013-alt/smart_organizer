from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from sqlite_utils import open_sqlite
from storage_db_schema import (
    CURRENT_SCHEMA_VERSION,
    SchemaStatus,
    expected_runtime_tables,
    inspect_database_schema,
    upgrade_database_schema,
)


def _create_schema_db(path: Path, version: str | None) -> None:
    with open_sqlite(path) as conn, conn:
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


def test_inspect_database_schema_rejects_missing_physical_file(tmp_path: Path):
    missing = tmp_path / "missing.db"

    inspection = inspect_database_schema(missing)

    assert inspection.status == SchemaStatus.CORRUPT
    assert "missing" in str(inspection.details).lower()


def test_inspect_database_schema_supports_memory_target_without_missing_file_error():
    inspection = inspect_database_schema(":memory:")

    assert inspection.status != SchemaStatus.CORRUPT
    assert "Database file is missing" not in str(inspection.details or "")


def test_shared_memory_uri_connections_share_the_same_database():
    uri = f"file:smart_organizer_schema_share_{uuid.uuid4().hex}?mode=memory&cache=shared"

    with open_sqlite(uri) as first:
        first.execute("CREATE TABLE shared_table(value TEXT)")
        first.execute("INSERT INTO shared_table(value) VALUES('ready')")
        first.commit()

        with open_sqlite(uri) as second:
            value = second.execute("SELECT value FROM shared_table").fetchone()

    assert value == ("ready",)


def test_schema_inspection_upgrade_and_expected_tables_support_shared_memory_uri():
    uri = f"file:smart_organizer_schema_upgrade_{uuid.uuid4().hex}?mode=memory&cache=shared"

    with open_sqlite(uri) as conn:
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
        cursor.execute("INSERT INTO sys_config(key, value) VALUES('schema_version', ?)", ("15",))
        conn.commit()

        before = inspect_database_schema(uri)
        upgraded = upgrade_database_schema(uri)
        after = inspect_database_schema(uri)
        tables = expected_runtime_tables(uri)

    assert before.status == SchemaStatus.LEGACY
    assert upgraded == CURRENT_SCHEMA_VERSION
    assert after.status == SchemaStatus.VALID
    assert "files" in tables
    assert "file_content_fts" in tables


def test_expected_runtime_tables_supports_uri_with_query_parameters():
    uri = (
        f"file:smart_organizer_schema_query_{uuid.uuid4().hex}"
        "?mode=memory&cache=shared&immutable=0"
    )

    with open_sqlite(uri) as conn:
        conn.execute("CREATE TABLE sample(value TEXT)")
        conn.commit()
        table_names = expected_runtime_tables(uri)

    assert "sample" in table_names


def test_inspect_database_schema_reports_corrupt_physical_database(tmp_path: Path):
    broken = tmp_path / "broken.db"
    broken.write_text("not sqlite", encoding="utf-8")

    inspection = inspect_database_schema(broken)

    assert inspection.status == SchemaStatus.CORRUPT
    assert "could not be opened" in str(inspection.details or "").lower()


def test_schema_inspection_releases_physical_database_for_rename(tmp_path: Path):
    db_path = tmp_path / "rename-me.db"
    renamed = tmp_path / "renamed.db"
    _create_schema_db(db_path, str(CURRENT_SCHEMA_VERSION))

    inspection = inspect_database_schema(db_path)
    db_path.rename(renamed)

    assert inspection.status == SchemaStatus.VALID
    assert renamed.exists()


def test_expected_runtime_tables_releases_physical_database_for_delete(tmp_path: Path):
    db_path = tmp_path / "delete-me.db"
    _create_schema_db(db_path, str(CURRENT_SCHEMA_VERSION))

    tables = expected_runtime_tables(db_path)
    db_path.unlink()

    assert "files" in tables
    assert not db_path.exists()


def test_schema_upgrade_releases_physical_database_for_rename(tmp_path: Path):
    db_path = tmp_path / "upgrade.db"
    renamed = tmp_path / "upgrade-renamed.db"
    _create_schema_db(db_path, "15")

    version = upgrade_database_schema(db_path)
    db_path.rename(renamed)

    assert version == CURRENT_SCHEMA_VERSION
    assert renamed.exists()
