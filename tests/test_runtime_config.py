from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

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
