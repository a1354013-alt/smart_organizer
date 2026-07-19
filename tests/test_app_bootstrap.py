from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest

import app_main
from core import FileProcessor
from runtime_config import build_runtime_config
from sqlite_utils import open_sqlite
from storage import StorageManager


def test_bootstrap_services_initializes_clean_workspace(tmp_path: Path):
    db_path = tmp_path / "smart_organizer.db"
    repo_root = tmp_path / "repo"
    upload_dir = tmp_path / "uploads"

    app_main.clear_test_service_cache()
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

        with open_sqlite(db_path) as conn:
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
        app_main.clear_test_service_cache()


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


def test_clear_test_service_cache_closes_cached_storage_and_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "smart_organizer.db"
    repo_root = tmp_path / "repo"
    upload_dir = tmp_path / "uploads"
    app_main.clear_test_service_cache()

    _processor, storage = app_main._bootstrap_services(
        str(db_path),
        str(repo_root),
        str(upload_dir),
    )
    storage.create_temp_file("invoice.pdf", b"%PDF-1.4\n", "bootstrap-cache", "document")

    app_main.clear_test_service_cache()
    app_main.clear_test_service_cache()

    renamed = tmp_path / "renamed.db"
    db_path.rename(renamed)
    assert renamed.exists()


def test_bootstrap_services_closes_storage_when_registration_fails(monkeypatch, tmp_path: Path):
    app_main.clear_test_service_cache()
    captured: list[StorageManager] = []

    def fail_register(storage: StorageManager) -> None:
        captured.append(storage)
        raise RuntimeError("register failed")

    monkeypatch.setattr(app_main, "_register_storage_close", fail_register)

    with pytest.raises(RuntimeError, match="register failed"):
        app_main._bootstrap_services(
            str(tmp_path / "smart_organizer.db"),
            str(tmp_path / "repo"),
            str(tmp_path / "uploads"),
        )

    assert len(captured) == 1
    with pytest.raises(RuntimeError, match="closed"):
        captured[0]._get_connection()
