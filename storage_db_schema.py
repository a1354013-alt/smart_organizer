from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from sqlite_utils import (
    SQLiteTarget,
    is_physical_sqlite_path,
    is_sqlite_memory_target,
    open_sqlite,
    physical_sqlite_path,
)

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 18
MIN_SUPPORTED_SCHEMA_VERSION = 1

REQUIRED_SCHEMA_TABLES = frozenset({"sys_config", "files"})
EXPECTED_RUNTIME_TABLES = frozenset({"sys_config", "files", "tags", "file_tags", "file_content_fts"})
MIGRATION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("safe_name", "TEXT"),
    ("final_name", "TEXT"),
    ("classification_reason", "TEXT"),
    ("final_decision_reason", "TEXT"),
    ("temp_path", "TEXT"),
    ("final_path", "TEXT"),
    ("preview_path", "TEXT"),
    ("moving_target_path", "TEXT"),
    ("file_type", "TEXT"),
    ("standard_date", "TEXT"),
    ("main_topic", "TEXT"),
    ("summary", "TEXT"),
    ("summary_status", "TEXT"),
    ("summary_error", "TEXT"),
    ("is_scanned", "INTEGER DEFAULT 0"),
    ("status", "TEXT DEFAULT 'PENDING'"),
    ("last_error", "TEXT"),
    ("manual_override", "INTEGER DEFAULT 0"),
    ("decision_source", "TEXT"),
    ("decision_updated_at", "TEXT"),
    ("last_manual_topic", "TEXT"),
    ("last_manual_reason", "TEXT"),
    ("updated_at", "TEXT"),
    ("malware_verdict", "TEXT DEFAULT 'not_scanned'"),
    ("malware_scan_health", "TEXT DEFAULT 'incomplete'"),
    ("malware_status", "TEXT DEFAULT 'not_scanned'"),
    ("malware_scanner_backend", "TEXT"),
    ("malware_scanner_engine_version", "TEXT"),
    ("malware_database_version", "TEXT"),
    ("malware_database_date", "TEXT"),
    ("malware_threat_name", "TEXT"),
    ("malware_message", "TEXT"),
    ("malware_scanned_at", "TEXT"),
    ("malware_elapsed_seconds", "REAL DEFAULT 0"),
    ("malware_cache_hit", "INTEGER DEFAULT 0"),
)
FILE_INDEX_STATEMENTS = {
    "idx_files_created_at_file_id": (
        {"created_at", "file_id"},
        "CREATE INDEX IF NOT EXISTS idx_files_created_at_file_id ON files(created_at DESC, file_id DESC)",
    ),
    "idx_files_status_created_at": (
        {"status", "created_at", "file_id"},
        "CREATE INDEX IF NOT EXISTS idx_files_status_created_at ON files(status, created_at DESC, file_id DESC)",
    ),
    "idx_files_main_topic_created_at": (
        {"main_topic", "created_at", "file_id"},
        "CREATE INDEX IF NOT EXISTS idx_files_main_topic_created_at ON files(main_topic, created_at DESC, file_id DESC)",
    ),
    "idx_files_file_type_created_at": (
        {"file_type", "created_at", "file_id"},
        "CREATE INDEX IF NOT EXISTS idx_files_file_type_created_at ON files(file_type, created_at DESC, file_id DESC)",
    ),
}


class SchemaStatus(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    INVALID = "invalid"
    FUTURE = "future"
    LEGACY = "legacy"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class SchemaInspection:
    status: SchemaStatus
    version: int | None
    details: str | None = None


def _ensure_indexes(cursor: sqlite3.Cursor) -> None:
    cursor.execute("PRAGMA table_info(files)")
    columns = {str(row[1]) for row in cursor.fetchall()}
    for required_columns, statement in FILE_INDEX_STATEMENTS.values():
        if required_columns.issubset(columns):
            cursor.execute(statement)


def _create_current_schema(cursor: sqlite3.Cursor) -> None:
    cursor.execute("CREATE TABLE IF NOT EXISTS sys_config (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_name TEXT,
            safe_name TEXT,
            final_name TEXT,
            temp_path TEXT,
            final_path TEXT,
            preview_path TEXT,
            moving_target_path TEXT,
            file_hash TEXT UNIQUE,
            file_type TEXT,
            standard_date TEXT,
            main_topic TEXT,
            summary TEXT,
            summary_status TEXT,
            summary_error TEXT,
            classification_reason TEXT,
            final_decision_reason TEXT,
            manual_override INTEGER DEFAULT 0,
            decision_source TEXT,
            decision_updated_at TEXT,
            last_manual_topic TEXT,
            last_manual_reason TEXT,
            is_scanned INTEGER DEFAULT 0,
            last_error TEXT,
            status TEXT DEFAULT 'PENDING',
            malware_verdict TEXT DEFAULT 'not_scanned',
            malware_scan_health TEXT DEFAULT 'incomplete',
            malware_status TEXT DEFAULT 'not_scanned',
            malware_scanner_backend TEXT,
            malware_scanner_engine_version TEXT,
            malware_database_version TEXT,
            malware_database_date TEXT,
            malware_threat_name TEXT,
            malware_message TEXT,
            malware_scanned_at TEXT,
            malware_elapsed_seconds REAL DEFAULT 0,
            malware_cache_hit INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
            updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
        )
        """
    )
    cursor.execute("CREATE TABLE IF NOT EXISTS tags (tag_id INTEGER PRIMARY KEY AUTOINCREMENT, tag_name TEXT UNIQUE)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS file_tags (
            file_id INTEGER, tag_id INTEGER, confidence REAL,
            PRIMARY KEY (file_id, tag_id),
            FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS file_content_fts USING fts5(
            original_filename,
            title,
            summary,
            content,
            tokenize='unicode61'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS malware_scan_cache (
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
        CREATE INDEX IF NOT EXISTS idx_malware_scan_cache_lookup
        ON malware_scan_cache(sha256, scanner_backend, engine_version, database_version, database_date, scan_policy_version)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_malware_scan_cache_unchanged_file
        ON malware_scan_cache(
            canonical_path_key, size_bytes, mtime_ns, file_identity,
            scanner_backend, engine_version, database_version, database_date, scan_policy_version,
            verdict, scan_health
        )
        """
    )
    cursor.execute(
        "INSERT OR IGNORE INTO sys_config (key, value) VALUES (?, ?)",
        ("schema_version", str(CURRENT_SCHEMA_VERSION)),
    )
    _ensure_indexes(cursor)


def expected_runtime_tables(db_path: SQLiteTarget) -> set[str]:
    with open_sqlite(db_path) as conn:
        return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def inspect_database_schema(db_path: SQLiteTarget) -> SchemaInspection:
    if is_physical_sqlite_path(db_path) and not physical_sqlite_path(db_path).exists():
        return SchemaInspection(SchemaStatus.CORRUPT, None, f"Database file is missing: {db_path}")
    try:
        with open_sqlite(db_path) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                return SchemaInspection(SchemaStatus.CORRUPT, None, "SQLite integrity_check failed")
            table_names = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing_tables = sorted(REQUIRED_SCHEMA_TABLES - table_names)
            if missing_tables:
                return SchemaInspection(
                    SchemaStatus.INVALID,
                    None,
                    f"Database is missing required tables: {', '.join(missing_tables)}",
                )
            row = conn.execute("SELECT value FROM sys_config WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error as exc:
        return SchemaInspection(SchemaStatus.CORRUPT, None, f"SQLite database could not be opened: {exc}")

    if row is None:
        return SchemaInspection(SchemaStatus.MISSING, None, "schema_version is missing")
    raw_version = row[0]
    if raw_version is None or str(raw_version).strip() == "":
        return SchemaInspection(SchemaStatus.MISSING, None, "schema_version is empty")
    try:
        version = int(str(raw_version).strip())
    except (TypeError, ValueError):
        return SchemaInspection(SchemaStatus.INVALID, None, f"schema_version is not an integer: {raw_version!r}")
    if version > CURRENT_SCHEMA_VERSION:
        return SchemaInspection(SchemaStatus.FUTURE, version, f"schema_version {version} is newer than supported")
    if version < MIN_SUPPORTED_SCHEMA_VERSION:
        return SchemaInspection(
            SchemaStatus.INVALID,
            version,
            f"schema_version {version} is below the supported migration baseline",
        )
    if version < CURRENT_SCHEMA_VERSION:
        return SchemaInspection(SchemaStatus.LEGACY, version, f"schema_version {version} requires upgrade")
    return SchemaInspection(SchemaStatus.VALID, version, None)


def upgrade_database_schema(
    db_path: SQLiteTarget,
    *,
    target_version: int = CURRENT_SCHEMA_VERSION,
) -> int:
    inspection = inspect_database_schema(db_path)
    if inspection.status == SchemaStatus.MISSING:
        raise RuntimeError(f"Database schema_version is missing: {inspection.details}")
    if inspection.status == SchemaStatus.INVALID:
        raise RuntimeError(f"Database schema metadata is invalid: {inspection.details}")
    if inspection.status == SchemaStatus.FUTURE:
        raise RuntimeError(f"Database schema is from a future version: {inspection.details}")
    if inspection.status == SchemaStatus.CORRUPT:
        raise RuntimeError(f"Database verification failed: {inspection.details}")
    if inspection.version is None:
        raise RuntimeError("Database schema version could not be determined")

    try:
        with open_sqlite(db_path) as conn, conn:
            cursor = conn.cursor()
            _create_current_schema(cursor)
            cursor.execute("PRAGMA table_info(files)")
            columns = {str(row[1]) for row in cursor.fetchall()}
            for col_name, col_type in MIGRATION_COLUMNS:
                if col_name not in columns:
                    cursor.execute(f"ALTER TABLE files ADD COLUMN {col_name} {col_type}")

            version = inspection.version
            if version < target_version:
                logger.info("Migration: V%s -> V%s", version, target_version)
                if version < 7:
                    cursor.execute("CREATE TABLE IF NOT EXISTS file_tags_backup AS SELECT * FROM file_tags")
                    cursor.execute("DROP TABLE IF EXISTS file_tags")
                    cursor.execute(
                        """
                        CREATE TABLE file_tags (
                            file_id INTEGER, tag_id INTEGER, confidence REAL,
                            PRIMARY KEY (file_id, tag_id),
                            FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
                            FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
                        )
                        """
                    )
                    cursor.execute("INSERT OR IGNORE INTO file_tags SELECT * FROM file_tags_backup")
                    cursor.execute("DROP TABLE IF EXISTS file_tags_backup")

                if version < 14:
                    cursor.execute(
                        """
                        UPDATE files
                        SET created_at = REPLACE(created_at, ' ', 'T') || '+00:00'
                        WHERE created_at GLOB '????-??-?? ??:??:??'
                        """
                    )
                    cursor.execute(
                        """
                        UPDATE files
                        SET decision_updated_at = REPLACE(decision_updated_at, ' ', 'T') || '+00:00'
                        WHERE decision_updated_at GLOB '????-??-?? ??:??:??'
                        """
                    )

                if version < 16:
                    cursor.execute(
                        """
                        UPDATE files
                        SET updated_at = COALESCE(updated_at, created_at, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
                        WHERE updated_at IS NULL OR updated_at = ''
                        """
                    )

                cursor.execute(
                    "UPDATE sys_config SET value = ? WHERE key = 'schema_version'",
                    (str(target_version),),
                )

            _ensure_indexes(cursor)
    except sqlite3.Error as exc:
        raise RuntimeError(f"Database migration failed: {exc}") from exc

    verified = inspect_database_schema(db_path) if not is_sqlite_memory_target(db_path) else SchemaInspection(
        SchemaStatus.VALID,
        target_version,
        None,
    )
    if verified.status != SchemaStatus.VALID or verified.version != target_version:
        raise RuntimeError(f"Database schema upgrade verification failed: {verified.details or verified.status.value}")
    missing_runtime_tables = sorted((EXPECTED_RUNTIME_TABLES | {"malware_scan_cache"}) - expected_runtime_tables(db_path))
    if missing_runtime_tables:
        raise RuntimeError(
            f"Database schema upgrade verification failed: missing tables {', '.join(missing_runtime_tables)}"
        )
    return target_version
