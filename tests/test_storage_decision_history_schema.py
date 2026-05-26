from __future__ import annotations

import sqlite3
from pathlib import Path

from storage import StorageManager


def test_fresh_db_has_decision_history_columns(tmp_path: Path):
    storage = StorageManager(str(tmp_path / "t.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    conn = storage._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(files)")
        cols = {row[1] for row in cursor.fetchall()}
    finally:
        conn.close()

    assert "decision_source" in cols
    assert "decision_updated_at" in cols
    assert "last_manual_topic" in cols
    assert "last_manual_reason" in cols


def test_migration_creates_repeatable_query_indexes(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sys_config (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sys_config(key, value) VALUES ('schema_version', '1')")
        conn.execute(
            """
            CREATE TABLE files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT,
                file_hash TEXT UNIQUE,
                created_at TEXT,
                status TEXT DEFAULT 'PENDING'
            )
            """
        )
        conn.commit()

    expected_indexes = {
        "idx_files_created_at_file_id",
        "idx_files_status_created_at",
        "idx_files_main_topic_created_at",
        "idx_files_file_type_created_at",
    }

    for _ in range(2):
        storage = StorageManager(str(db_path), str(tmp_path / "repo"), str(tmp_path / "uploads"))
        conn = storage._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'files'")
            index_names = {str(row[0]) for row in cursor.fetchall()}
        finally:
            conn.close()
            storage.close()
        assert expected_indexes.issubset(index_names)
