from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest

import runtime_config
from runtime_config import (
    DATA_DIR_ENV,
    LegacyDataMigrationError,
    MigrationMarkerValidationError,
    RuntimeDirectoryError,
    build_runtime_config,
    detect_legacy_data,
    ensure_runtime_directories,
    migrate_legacy_data_if_needed,
)
from sqlite_utils import open_sqlite


def _write_legacy_db(path: Path) -> None:
    with open_sqlite(path) as conn, conn:
        conn.execute("CREATE TABLE sys_config(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            """
            CREATE TABLE files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT,
                file_hash TEXT UNIQUE,
                created_at TEXT
            )
            """
        )
        conn.execute("CREATE TABLE tags(tag_id INTEGER PRIMARY KEY AUTOINCREMENT, tag_name TEXT UNIQUE)")
        conn.execute("CREATE TABLE file_tags(file_id INTEGER, tag_id INTEGER, confidence REAL)")
        conn.execute(
            """
            CREATE VIRTUAL TABLE file_content_fts USING fts5(
                original_filename,
                title,
                summary,
                content,
                tokenize='unicode61'
            )
            """
        )
        conn.execute("INSERT INTO sys_config VALUES('schema_version', '16')")


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
    _write_legacy_db(source / "smart_organizer.db")

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
    _write_legacy_db(source / "smart_organizer.db")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    original = runtime_config._copy_tree_if_present
    calls = {"count": 0}

    def fail_upload_once(source_path: Path, destination: Path, **kwargs: object) -> bool:
        calls["count"] += 1
        if source_path.name == "uploads":
            raise OSError("simulated copy failure")
        return original(source_path, destination, **kwargs)

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

    assert status.destination_state == "valid_completed_migration"
    assert (config.upload_dir / "old.pdf").exists()
    assert len(list(config.data_root.rglob("old.pdf"))) == 1


def test_legacy_migration_preserves_committed_wal_rows(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    db_path = source / "smart_organizer.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE files(file_id INTEGER PRIMARY KEY, original_name TEXT)")
        conn.execute("CREATE TABLE sys_config(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE tags(tag_id INTEGER PRIMARY KEY AUTOINCREMENT, tag_name TEXT UNIQUE)")
        conn.execute("CREATE TABLE file_tags(file_id INTEGER, tag_id INTEGER, confidence REAL)")
        conn.execute(
            """
            CREATE VIRTUAL TABLE file_content_fts USING fts5(
                original_filename,
                title,
                summary,
                content,
                tokenize='unicode61'
            )
            """
        )
        conn.execute("INSERT INTO sys_config VALUES('schema_version', '16')")
        conn.execute("INSERT INTO files(original_name) VALUES('wal-backed.pdf')")
        conn.commit()
        assert (source / "smart_organizer.db-wal").exists()
        config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})
        migrate_legacy_data_if_needed(config)
    finally:
        conn.close()

    with open_sqlite(config.db_path) as migrated:
        row = migrated.execute("SELECT original_name FROM files").fetchone()

    assert row == ("wal-backed.pdf",)
    assert not (config.data_root / "smart_organizer.db-wal").exists()


def test_migration_releases_legacy_database_for_rename(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    _write_legacy_db(source / "smart_organizer.db")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    migrate_legacy_data_if_needed(config)
    renamed_source = source / "smart_organizer-renamed.db"
    source_db = source / "smart_organizer.db"
    source_db.rename(renamed_source)

    assert renamed_source.exists()


def test_failed_database_copy_releases_source_and_destination_handles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    _write_legacy_db(source)

    class FailingBackupConnection:
        def __init__(self, real_conn: sqlite3.Connection) -> None:
            self._real = real_conn

        def backup(self, target: sqlite3.Connection, *args: object, **kwargs: object) -> object:
            raise sqlite3.OperationalError("forced backup failure")

        def close(self) -> None:
            self._real.close()

    @contextmanager
    def failing_open_sqlite(target: object, **kwargs: object):
        raw_target = str(target)
        conn = sqlite3.connect(raw_target, uri=raw_target.startswith("file:"), **kwargs)
        wrapped = FailingBackupConnection(conn) if raw_target == f"file:{source}?mode=ro" else conn
        try:
            yield wrapped
        finally:
            wrapped.close()

    monkeypatch.setattr(runtime_config, "open_sqlite", failing_open_sqlite)
    with pytest.raises(LegacyDataMigrationError, match="Failed to copy legacy SQLite database safely"):
        runtime_config._copy_sqlite_database(source, destination)

    source.rename(tmp_path / "source-renamed.db")
    if destination.exists():
        destination.unlink()


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
    _write_legacy_db(source / "smart_organizer.db")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    first = migrate_legacy_data_if_needed(config)
    first_marker = (config.data_root / ".smart_organizer_migration.json").read_text(encoding="utf-8")
    first_files = sorted(path.relative_to(config.data_root) for path in config.data_root.rglob("*") if path.is_file())
    second = migrate_legacy_data_if_needed(config)
    third = migrate_legacy_data_if_needed(config)

    assert first.destination_state == "valid_completed_migration"
    assert second.destination_state == "valid_completed_migration"
    assert third.destination_state == "valid_completed_migration"
    assert (config.data_root / ".smart_organizer_migration.json").read_text(encoding="utf-8") == first_marker
    assert sorted(path.relative_to(config.data_root) for path in config.data_root.rglob("*") if path.is_file()) == first_files
    assert (source / "uploads" / "old.pdf").exists()
    assert not list(tmp_path.glob(".smart-organizer-migration-*/migration-state.json"))


def test_tampered_state_staging_root_does_not_delete_unrelated_directory(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    _write_legacy_db(source / "smart_organizer.db")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})
    staging = tmp_path / ".smart-organizer-migration-tampered"
    staging.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    sentinel = unrelated / "sentinel.txt"
    sentinel.write_text("do not delete", encoding="utf-8")
    now = runtime_config._utc_now()
    state = {
        "format_version": 1,
        "migration_id": "tampered",
        "status": "failed",
        "legacy_root": str(source),
        "destination_root": str(config.data_root),
        "staging_root": str(unrelated),
        "started_at": now,
        "updated_at": now,
        "completed_at": None,
        "database_verified": False,
        "artifacts": dict.fromkeys(runtime_config.MIGRATED_ARTIFACTS, "pending"),
        "last_error": None,
        "database_source": None,
        "promotion_started_at": None,
    }
    (staging / "migration-state.json").write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(LegacyDataMigrationError, match="staging_root|staging"):
        migrate_legacy_data_if_needed(config)

    assert sentinel.read_text(encoding="utf-8") == "do not delete"


def test_directory_only_uploads_create_valid_database(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    (source / "uploads" / "orphan.pdf").write_bytes(b"orphan")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    status = migrate_legacy_data_if_needed(config)
    marker = json.loads((config.data_root / ".smart_organizer_migration.json").read_text(encoding="utf-8"))

    assert status.destination_state == "valid_completed_migration"
    assert marker["database_source"] == "newly_created"
    assert marker["database_verified"] is True
    assert config.db_path.exists()
    assert (config.upload_dir / "orphan.pdf").exists()


def test_marker_missing_migration_id_is_rejected(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _write_legacy_db(source / "smart_organizer.db")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})
    migrate_legacy_data_if_needed(config)
    marker_path = config.data_root / ".smart_organizer_migration.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker.pop("migration_id")
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(LegacyDataMigrationError, match="Migration ID|migration"):
        migrate_legacy_data_if_needed(config)


def test_stale_local_lock_is_recovered(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    _write_legacy_db(source / "smart_organizer.db")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})
    lock_path = tmp_path / ".smart-organizer-migration.lock"
    lock_path.write_text(
        json.dumps({"pid": 99999999, "hostname": runtime_config.socket.gethostname(), "created_at": runtime_config._utc_now()}),
        encoding="utf-8",
    )

    status = migrate_legacy_data_if_needed(config)

    assert status.destination_state == "valid_completed_migration"
    assert not lock_path.exists()


def test_repository_sources_merge_and_conflict(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _write_legacy_db(source / "smart_organizer.db")
    (source / "repo").mkdir()
    (source / "repository").mkdir()
    (source / "repo" / "old.txt").write_text("old", encoding="utf-8")
    (source / "repository" / "new.txt").write_text("new", encoding="utf-8")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    migrate_legacy_data_if_needed(config)

    assert (config.repo_root / "old.txt").read_text(encoding="utf-8") == "old"
    assert (config.repo_root / "new.txt").read_text(encoding="utf-8") == "new"


def test_repository_sources_conflicting_file_stops_before_promotion(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _write_legacy_db(source / "smart_organizer.db")
    (source / "repo").mkdir()
    (source / "repository").mkdir()
    (source / "repo" / "same.txt").write_text("old", encoding="utf-8")
    (source / "repository" / "same.txt").write_text("new", encoding="utf-8")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    with pytest.raises(LegacyDataMigrationError, match="Repository migration file conflict"):
        migrate_legacy_data_if_needed(config)

    assert not config.data_root.exists()


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


def test_recovery_after_marker_write_completes_on_next_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "uploads").mkdir()
    (source / "uploads" / "old.pdf").write_bytes(b"%PDF-old")
    _write_legacy_db(source / "smart_organizer.db")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    original_write_state = runtime_config._write_state
    failed_once = {"done": False}

    def fail_after_marker(active_config: object, state: object, *, status: object = None, error: object = None) -> None:
        if (
            not failed_once["done"]
            and active_config == config
            and status == "completed"
            and (config.data_root / ".smart_organizer_migration.json").exists()
        ):
            failed_once["done"] = True
            raise OSError("simulated completed-state persistence failure")
        original_write_state(active_config, state, status=status, error=error)

    monkeypatch.setattr(runtime_config, "_write_state", fail_after_marker)

    with pytest.raises(LegacyDataMigrationError, match="source data was left untouched|failed"):
        migrate_legacy_data_if_needed(config)

    monkeypatch.setattr(runtime_config, "_write_state", original_write_state)
    status = migrate_legacy_data_if_needed(config)

    assert failed_once["done"] is True
    assert status.destination_state == "valid_completed_migration"
    assert (config.upload_dir / "old.pdf").exists()


def test_completed_marker_rejects_unrelated_active_lock_owner(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _write_legacy_db(source / "smart_organizer.db")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})
    migrate_legacy_data_if_needed(config)

    lock_path = config.data_root.parent / ".smart-organizer-migration.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "hostname": runtime_config.socket.gethostname(),
                "created_at": runtime_config._utc_now(),
                "owner_token": "someone-else",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MigrationMarkerValidationError, match="lock owner"):
        runtime_config._validate_completed_marker(config, allowed_lock_owner="current-owner")


def test_legacy_upload_symlink_is_rejected_before_promotion(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    uploads = source / "uploads"
    uploads.mkdir()
    sentinel = tmp_path / "outside.txt"
    sentinel.write_text("sentinel", encoding="utf-8")
    try:
        (uploads / "escape.txt").symlink_to(sentinel)
    except OSError:
        pytest.skip("symlink creation is not available on this host")
    _write_legacy_db(source / "smart_organizer.db")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    with pytest.raises(LegacyDataMigrationError, match="unsafe linked entry|symlinked"):
        migrate_legacy_data_if_needed(config)

    assert sentinel.read_text(encoding="utf-8") == "sentinel"
    assert not config.data_root.exists()


def test_quarantine_aliases_merge_unique_files(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _write_legacy_db(source / "smart_organizer.db")
    (source / "quarantine").mkdir()
    (source / ".smart_organizer_quarantine").mkdir()
    (source / "quarantine" / "a.txt").write_text("a", encoding="utf-8")
    (source / ".smart_organizer_quarantine" / "b.txt").write_text("b", encoding="utf-8")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    migrate_legacy_data_if_needed(config)

    assert (config.quarantine_dir / "a.txt").read_text(encoding="utf-8") == "a"
    assert (config.quarantine_dir / "b.txt").read_text(encoding="utf-8") == "b"


def test_quarantine_alias_conflict_stops_before_promotion(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _write_legacy_db(source / "smart_organizer.db")
    (source / "quarantine").mkdir()
    (source / ".smart_organizer_quarantine").mkdir()
    (source / "quarantine" / "same.txt").write_text("old", encoding="utf-8")
    (source / ".smart_organizer_quarantine" / "same.txt").write_text("new", encoding="utf-8")
    config = build_runtime_config(source, {DATA_DIR_ENV: str(tmp_path / "data")})

    with pytest.raises(LegacyDataMigrationError, match="Quarantine migration file conflict"):
        migrate_legacy_data_if_needed(config)

    assert not config.data_root.exists()
