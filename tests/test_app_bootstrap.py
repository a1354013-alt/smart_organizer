from __future__ import annotations

import sqlite3
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import app_main
from core import FileProcessor
from runtime_config import build_runtime_config
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


def test_build_context_uses_startup_resolved_runtime_config(monkeypatch, tmp_path: Path):
    config = build_runtime_config(tmp_path / "source", {"SMART_ORGANIZER_DATA_DIR": str(tmp_path / "runtime data")})
    calls: list[tuple[str, str, str]] = []

    def fake_bootstrap(db_path: str, repo_root: str, upload_dir: str):
        calls.append((db_path, repo_root, upload_dir))
        return SimpleNamespace(), SimpleNamespace()

    monkeypatch.setattr(app_main, "_bootstrap_services", fake_bootstrap)
    monkeypatch.setattr(app_main, "_optional_import", lambda module_name: None)

    context = app_main._build_context(config)

    assert calls == [(str(config.db_path), str(config.repo_root), str(config.upload_dir))]
    assert context.project_root == config.project_root
    assert context.db_path == config.db_path
    assert context.repo_root == config.repo_root
    assert context.upload_dir == config.upload_dir
