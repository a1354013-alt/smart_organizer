from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from sqlite_utils import open_sqlite
from storage import StorageManager
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


def _table_info(path: Path, table_name: str) -> list[tuple[str, str, int, str | None, int]]:
    with open_sqlite(path) as conn:
        return [
            (str(row[1]), str(row[2]), int(row[3]), None if row[4] is None else str(row[4]), int(row[5]))
            for row in conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        ]


def _index_info(path: Path, table_name: str) -> list[tuple[str, int]]:
    with open_sqlite(path) as conn:
        return [(str(row[1]), int(row[2])) for row in conn.execute(f"PRAGMA index_list('{table_name}')").fetchall()]


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


def test_schema_19_adds_malware_cache_lookup_indexes_and_identity_table(tmp_path: Path):
    db_path = tmp_path / "schema19.db"
    _create_schema_db(db_path, "17")

    upgraded = upgrade_database_schema(db_path)

    with open_sqlite(db_path) as conn:
        index_names = {
            str(row[1])
            for row in conn.execute("PRAGMA index_list('malware_scan_cache')").fetchall()
        }
        identity_tables = {
            str(row[0]) for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='malware_scan_cache_identities'"
            ).fetchall()
        }
    assert upgraded == CURRENT_SCHEMA_VERSION == 19
    assert "idx_malware_scan_cache_lookup" in index_names
    assert "malware_scan_cache_identities" in identity_tables


def test_fresh_and_migrated_schema_19_cache_tables_are_identical(tmp_path: Path):
    fresh_db = tmp_path / "fresh.db"
    migrated_db = tmp_path / "migrated.db"

    storage = StorageManager(str(fresh_db), str(tmp_path / "fresh-repo"), str(tmp_path / "fresh-uploads"))
    storage.close()
    _create_schema_db(migrated_db, "17")
    upgrade_database_schema(migrated_db)

    for table_name in ("malware_scan_cache", "malware_scan_cache_identities"):
        assert _table_info(fresh_db, table_name) == _table_info(migrated_db, table_name)
        assert _index_info(fresh_db, table_name) == _index_info(migrated_db, table_name)


def test_schema_repair_normalizes_nullable_malware_cache_keys_and_deduplicates_rows(tmp_path: Path):
    db_path = tmp_path / "repair.db"
    _create_schema_db(db_path, str(CURRENT_SCHEMA_VERSION))

    with open_sqlite(db_path) as conn, conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE malware_scan_cache (
                cache_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                canonical_path_key TEXT,
                size_bytes INTEGER,
                mtime_ns INTEGER,
                file_identity TEXT,
                scanner_backend TEXT NOT NULL,
                engine_version TEXT,
                database_version TEXT,
                database_date TEXT,
                scan_policy_version TEXT NOT NULL,
                verdict TEXT NOT NULL,
                scan_health TEXT NOT NULL,
                threat_name TEXT,
                message TEXT,
                scanned_at TEXT NOT NULL,
                elapsed_seconds REAL DEFAULT 0,
                UNIQUE(sha256, scanner_backend, engine_version, database_version, database_date, scan_policy_version)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE malware_scan_cache_identities (
                identity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_path_key,
                size_bytes,
                mtime_ns,
                file_identity,
                scanner_backend,
                engine_version,
                database_version,
                database_date,
                scan_policy_version,
                cache_id INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO malware_scan_cache (
                sha256,
                canonical_path_key,
                size_bytes,
                mtime_ns,
                file_identity,
                scanner_backend,
                engine_version,
                database_version,
                database_date,
                scan_policy_version,
                verdict,
                scan_health,
                threat_name,
                message,
                scanned_at,
                elapsed_seconds
            )
            VALUES
                ('abc123', 'canon:path', 10, 20, 'inode-1', 'clamd', NULL, NULL, NULL, 'standard-v1', 'clean', 'ok', NULL, 'older', '2026-07-28T00:00:00+00:00', 0.1),
                ('abc123', 'canon:path', 10, 20, 'inode-1', 'clamd', NULL, NULL, NULL, 'standard-v1', 'clean', 'ok', NULL, 'newer', '2026-07-29T00:00:00+00:00', 0.2)
            """
        )
        cursor.execute(
            """
            INSERT INTO malware_scan_cache_identities (
                canonical_path_key,
                size_bytes,
                mtime_ns,
                file_identity,
                scanner_backend,
                engine_version,
                database_version,
                database_date,
                scan_policy_version,
                cache_id,
                updated_at
            )
            VALUES
                ('canon:path', 10, 20, 'inode-1', 'clamd', NULL, NULL, NULL, 'standard-v1', 1, '2026-07-28T00:00:00+00:00'),
                ('canon:path', 10, 20, 'inode-1', 'clamd', NULL, NULL, NULL, 'standard-v1', 2, '2026-07-29T00:00:00+00:00')
            """
        )

    upgraded = upgrade_database_schema(db_path)

    assert upgraded == CURRENT_SCHEMA_VERSION
    assert _table_info(db_path, "malware_scan_cache") == [
        ("cache_id", "INTEGER", 0, None, 1),
        ("sha256", "TEXT", 1, None, 0),
        ("scanner_backend", "TEXT", 1, None, 0),
        ("engine_version", "TEXT", 1, "''", 0),
        ("database_version", "TEXT", 1, "''", 0),
        ("database_date", "TEXT", 1, "''", 0),
        ("scan_policy_version", "TEXT", 1, None, 0),
        ("verdict", "TEXT", 1, None, 0),
        ("scan_health", "TEXT", 1, None, 0),
        ("threat_name", "TEXT", 0, None, 0),
        ("message", "TEXT", 0, None, 0),
        ("scanned_at", "TEXT", 1, None, 0),
        ("elapsed_seconds", "REAL", 0, "0", 0),
    ]
    with open_sqlite(db_path) as conn:
        content_rows = conn.execute(
            """
            SELECT sha256, scanner_backend, engine_version, database_version, database_date, scan_policy_version, message
            FROM malware_scan_cache
            """
        ).fetchall()
        identity_rows = conn.execute(
            """
            SELECT canonical_path_key, scanner_backend, engine_version, database_version, database_date, scan_policy_version
            FROM malware_scan_cache_identities
            """
        ).fetchall()
    assert content_rows == [("abc123", "clamd", "", "", "", "standard-v1", "newer")]
    assert identity_rows == [("canon:path", "clamd", "", "", "", "standard-v1")]


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
