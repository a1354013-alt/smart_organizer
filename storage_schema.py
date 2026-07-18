from __future__ import annotations

import logging
import sqlite3
from typing import Any

from storage_db_schema import CURRENT_SCHEMA_VERSION, FILE_INDEX_STATEMENTS, upgrade_database_schema

logger = logging.getLogger(__name__)

class StorageSchemaMixin:
    def _ensure_indexes(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(files)")
        columns = {str(row[1]) for row in cursor.fetchall()}
        for required_columns, statement in FILE_INDEX_STATEMENTS.values():
            if not required_columns.issubset(columns):
                continue
            cursor.execute(statement)

    def _init_db(self: Any) -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
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
                    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
                    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
                )
            """
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS tags (tag_id INTEGER PRIMARY KEY AUTOINCREMENT, tag_name TEXT UNIQUE)"
            )
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
                "INSERT OR IGNORE INTO sys_config (key, value) VALUES (?, ?)",
                ("schema_version", str(CURRENT_SCHEMA_VERSION)),
            )
            self._ensure_indexes(cursor)
            conn.commit()
        except sqlite3.Error as e:
            logger.error("db init failed: %s", e)
            raise
        finally:
            if conn:
                conn.close()

    def _check_migration(self: Any) -> None:
        try:
            upgrade_database_schema(self.db_path)
        except RuntimeError as e:
            raise RuntimeError(f"Database migration failed: {e}") from e
