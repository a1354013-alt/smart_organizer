from __future__ import annotations

import logging
import sqlite3
from typing import Any

from storage_base import CURRENT_SCHEMA_VERSION

logger = logging.getLogger(__name__)


class StorageSchemaMixin:
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
                    classification_reason TEXT,
                    final_decision_reason TEXT,
                    manual_override INTEGER DEFAULT 0,
                    is_scanned INTEGER DEFAULT 0,
                    last_error TEXT,
                    status TEXT DEFAULT 'PENDING',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
            conn.commit()
        except Exception as e:
            logger.error("db init failed: %s", e)
            raise
        finally:
            if conn:
                conn.close()

    def _check_migration(self: Any) -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM sys_config WHERE key = "schema_version"')
            row = cursor.fetchone()
            version = int(row[0]) if row else 1

            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            new_cols = [
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
                ("is_scanned", "INTEGER DEFAULT 0"),
                ("status", "TEXT DEFAULT 'PENDING'"),
                ("last_error", "TEXT"),
                ("manual_override", "INTEGER DEFAULT 0"),
                ("decision_source", "TEXT"),
                ("decision_updated_at", "TEXT"),
                ("last_manual_topic", "TEXT"),
                ("last_manual_reason", "TEXT"),
            ]
            for col_name, col_type in new_cols:
                if col_name not in columns:
                    cursor.execute(f"ALTER TABLE files ADD COLUMN {col_name} {col_type}")

            if version < CURRENT_SCHEMA_VERSION:
                logger.info("Migration: V%s -> V%s", version, CURRENT_SCHEMA_VERSION)

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

                cursor.execute(
                    "UPDATE sys_config SET value = ? WHERE key = 'schema_version'",
                    (str(CURRENT_SCHEMA_VERSION),),
                )
                conn.commit()
        except Exception as e:
            raise RuntimeError(f"Database migration failed: {e}") from e
        finally:
            if conn:
                conn.close()
