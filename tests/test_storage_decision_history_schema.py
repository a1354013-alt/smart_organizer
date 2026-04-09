from __future__ import annotations

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

