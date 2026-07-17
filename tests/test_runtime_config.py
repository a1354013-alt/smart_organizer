from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import runtime_config
from runtime_config import (
    DATA_DIR_ENV,
    LegacyDataMigrationError,
    RuntimeDirectoryError,
    build_runtime_config,
    detect_legacy_data,
    ensure_runtime_directories,
    migrate_legacy_data_if_needed,
)


def test_env_override_supports_spaces_and_unicode(tmp_path: Path):
    data_root = tmp_path / "Smart Organizer 資料"
    config = build_runtime_config(tmp_path / "source", {DATA_DIR_ENV: str(data_root)})

    assert config.data_root == data_root.resolve()
    assert config.db_path == data_root.resolve() / "smart_organizer.db"
    assert config.upload_dir == data_root.resolve() / "uploads"
    assert config.repo_root == data_root.resolve() / "repository"


def test_runtime_directories_reject_file_where_directory_expected(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.write_text("not a directory", encoding="utf-8")
    config = build_runtime_config(tmp_path / "source", {DATA_DIR_ENV: str(data_root)})

    with pytest.raises(RuntimeDirectoryError, match="not a directory"):
        ensure_runtime_directories(config)


def test_runtime_directories_create_required_structure(tmp_path: Path):
    config = build_runtime_config(tmp_path / "source", {DATA_DIR_ENV: str(tmp_path / "data")})

    ensure_runtime_directories(config)

    for path in (
        config.data_root,
        config.upload_dir,
        config.repo_root,
        config.preview_dir,
        config.quarantine_dir,
        config.log_dir,
        config.manifest_dir,
    ):
        assert path.is_dir()


def test_legacy_migration_copies_data_without_deleting_source(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    legacy_uploads = source / "uploads"
    legacy_repo = source / "repo"
    legacy_uploads.mkdir()
    legacy_repo.mkdir()
    (legacy_uploads / "old.pdf").write_bytes(b"%PDF-old")
    (legacy_repo / "organized.pdf").write_text("organized", encoding="utf-8")
    with sqlite3.connect(source / "smart_organizer.db") as conn:
        conn.execute("CREATE TABLE sys_config(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sys_config VALUES('schema_version', '16')")

    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})
    status = migrate_legacy_data_if_needed(config)

    assert status.has_legacy_data
    assert config.db_path.exists()
    assert (config.upload_dir / "old.pdf").exists()
    assert (config.repo_root / "organized.pdf").exists()
    assert (source / "uploads" / "old.pdf").exists()
    assert (config.data_root / ".smart_organizer_migration.json").exists()
    marker = json.loads((config.data_root / ".smart_organizer_migration.json").read_text(encoding="utf-8"))
    assert marker["status"] == "completed"
    assert marker["database_verified"] is True


def test_legacy_migration_refuses_non_empty_destination(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    data = tmp_path / "data"
    (data / "uploads").mkdir(parents=True)
    (data / "uploads" / "existing.pdf").write_bytes(b"existing")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(data)})

    with pytest.raises(LegacyDataMigrationError, match="already contains data"):
        migrate_legacy_data_if_needed(config)

    assert (source / "uploads").exists()
    assert (data / "uploads" / "existing.pdf").exists()


def test_legacy_migration_refuses_concurrent_lock(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (data / ".smart_organizer_migration.lock").write_text("pid=123\n", encoding="utf-8")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(data)})

    with pytest.raises(LegacyDataMigrationError, match="already in progress"):
        migrate_legacy_data_if_needed(config)

    assert (source / "uploads").exists()
    assert (data / ".smart_organizer_migration.lock").exists()


def test_legacy_migration_failure_during_staging_retries_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    (source / "uploads" / "old.pdf").write_bytes(b"%PDF-old")
    with sqlite3.connect(source / "smart_organizer.db") as conn:
        conn.execute("CREATE TABLE sys_config(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sys_config VALUES('schema_version', '16')")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    original = runtime_config._copy_tree_if_present
    calls = {"count": 0}

    def fail_upload_once(source_path: Path, destination: Path) -> bool:
        calls["count"] += 1
        if source_path.name == "uploads":
            raise OSError("simulated copy failure")
        return original(source_path, destination)

    monkeypatch.setattr(runtime_config, "_copy_tree_if_present", fail_upload_once)
    with pytest.raises(LegacyDataMigrationError, match="source data was left untouched"):
        migrate_legacy_data_if_needed(config)

    assert not config.data_root.exists()
    assert (source / "uploads" / "old.pdf").exists()
    state_files = list(tmp_path.glob(".smart-organizer-migration-*/migration-state.json"))
    assert state_files
    assert json.loads(state_files[0].read_text(encoding="utf-8"))["status"] == "failed"

    monkeypatch.setattr(runtime_config, "_copy_tree_if_present", original)
    status = migrate_legacy_data_if_needed(config)

    assert status.destination_state == "initialized_valid"
    assert (config.upload_dir / "old.pdf").exists()
    assert len(list(config.data_root.rglob("old.pdf"))) == 1


def test_legacy_migration_preserves_committed_wal_rows(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    db_path = source / "smart_organizer.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE sys_config(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE files(file_id INTEGER PRIMARY KEY, original_name TEXT)")
        conn.execute("INSERT INTO sys_config VALUES('schema_version', '16')")
        conn.execute("INSERT INTO files(original_name) VALUES('wal-backed.pdf')")
        conn.commit()
        assert (source / "smart_organizer.db-wal").exists()
        config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})
        migrate_legacy_data_if_needed(config)
    finally:
        conn.close()

    with sqlite3.connect(config.db_path) as migrated:
        row = migrated.execute("SELECT original_name FROM files").fetchone()

    assert row == ("wal-backed.pdf",)
    assert not (config.data_root / "smart_organizer.db-wal").exists()


def test_corrupted_completed_marker_is_rejected(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})
    config.data_root.mkdir()
    (config.data_root / ".smart_organizer_migration.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(LegacyDataMigrationError, match="invalid_marker|marker"):
        migrate_legacy_data_if_needed(config)


def test_repeated_migration_startup_is_idempotent(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    (source / "uploads" / "old.pdf").write_bytes(b"%PDF-old")
    with sqlite3.connect(source / "smart_organizer.db") as conn:
        conn.execute("CREATE TABLE sys_config(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sys_config VALUES('schema_version', '16')")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    migrate_legacy_data_if_needed(config)
    first_marker = (config.data_root / ".smart_organizer_migration.json").read_text(encoding="utf-8")
    first_files = sorted(path.relative_to(config.data_root) for path in config.data_root.rglob("*") if path.is_file())
    with pytest.raises(LegacyDataMigrationError, match="validated data"):
        migrate_legacy_data_if_needed(config)

    assert (config.data_root / ".smart_organizer_migration.json").read_text(encoding="utf-8") == first_marker
    assert sorted(path.relative_to(config.data_root) for path in config.data_root.rglob("*") if path.is_file()) == first_files


def test_legacy_detection_reports_source_and_destination_state(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})
    ensure_runtime_directories(config)

    status = detect_legacy_data(config)

    assert status.legacy_root == source.resolve()
    assert status.has_legacy_data is True
    assert status.destination_initialized is False


def test_data_root_is_independent_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source"
    source.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    assert config.project_root == source.resolve()
    assert config.data_root != other.resolve()
