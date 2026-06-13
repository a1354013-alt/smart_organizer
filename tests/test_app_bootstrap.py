from __future__ import annotations

import sqlite3
from contextlib import suppress
from pathlib import Path

import app_main
from core import FileProcessor
from storage import StorageManager


def test_bootstrap_services_initializes_clean_workspace(tmp_path: Path):
    db_path = tmp_path / "smart_organizer.db"
    repo_root = tmp_path / "repo"
    upload_dir = tmp_path / "uploads"

    app_main._bootstrap_services.clear()
    try:
        processor, storage = app_main._bootstrap_services(
            str(db_path),
            str(repo_root),
            str(upload_dir),
        )

        assert isinstance(processor, FileProcessor)
        assert isinstance(storage, StorageManager)
        assert db_path.exists()
        assert repo_root.is_dir()
        assert upload_dir.is_dir()

        with sqlite3.connect(db_path) as conn:
            table_names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            schema_version = conn.execute(
                "SELECT value FROM sys_config WHERE key = 'schema_version'"
            ).fetchone()

        assert {"sys_config", "files", "tags", "file_tags", "file_content_fts"}.issubset(table_names)
        assert schema_version is not None
    finally:
        with suppress(UnboundLocalError):
            storage.close()
        app_main._bootstrap_services.clear()
