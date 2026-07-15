from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENV = "SMART_ORGANIZER_DATA_DIR"
APP_AUTHOR = "SmartOrganizer"
APP_DIR_WINDOWS = "SmartOrganizer"
APP_DIR_POSIX = "smart-organizer"
MIGRATION_MARKER = ".smart_organizer_migration.json"
MIGRATION_LOCK = ".smart_organizer_migration.lock"
MIGRATION_VERSION = 1


class ConfigurationError(RuntimeError):
    pass


class RuntimeDirectoryError(ConfigurationError):
    pass


class LegacyDataMigrationError(ConfigurationError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    project_root: Path
    data_root: Path
    db_path: Path
    upload_dir: Path
    repo_root: Path
    preview_dir: Path
    quarantine_dir: Path
    log_dir: Path
    manifest_dir: Path
    cleanup_stale_unfinished_seconds: int = 7 * 24 * 3600


@dataclass(frozen=True, slots=True)
class LegacyDataStatus:
    legacy_root: Path
    has_legacy_data: bool
    destination_initialized: bool
    marker_path: Path


def _default_data_root() -> Path:
    try:
        from platformdirs import user_data_dir
    except ImportError:
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            return base / APP_DIR_WINDOWS
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / APP_DIR_WINDOWS
        return Path.home() / ".local" / "share" / APP_DIR_POSIX

    app_name = APP_DIR_WINDOWS if sys.platform in {"win32", "darwin"} else APP_DIR_POSIX
    return Path(user_data_dir(appname=app_name, appauthor=APP_AUTHOR if sys.platform == "win32" else False))


def _resolve_data_root(env: dict[str, str] | None = None) -> Path:
    env_map = os.environ if env is None else env
    override = str(env_map.get(DATA_DIR_ENV) or "").strip()
    if override:
        raw = Path(os.path.expandvars(os.path.expanduser(override)))
    else:
        raw = _default_data_root()
    try:
        return raw.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeDirectoryError(f"Runtime data directory is invalid: {raw}") from exc


def build_runtime_config(project_root: Path | None = None, env: dict[str, str] | None = None) -> RuntimeConfig:
    root = (project_root or Path(__file__).resolve().parent).resolve(strict=False)
    data_root = _resolve_data_root(env)
    return RuntimeConfig(
        project_root=root,
        data_root=data_root,
        db_path=data_root / "smart_organizer.db",
        upload_dir=data_root / "uploads",
        repo_root=data_root / "repository",
        preview_dir=data_root / "previews",
        quarantine_dir=data_root / "quarantine",
        log_dir=data_root / "logs",
        manifest_dir=data_root / "manifests",
    )


def _ensure_directory(path: Path, *, label: str) -> None:
    if path.exists() and not path.is_dir():
        raise RuntimeDirectoryError(f"{label} is a file, not a directory: {path}")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise RuntimeDirectoryError(f"{label} is not writable: {path}") from exc


def ensure_runtime_directories(config: RuntimeConfig) -> None:
    for label, path in (
        ("runtime data directory", config.data_root),
        ("upload directory", config.upload_dir),
        ("repository directory", config.repo_root),
        ("preview directory", config.preview_dir),
        ("quarantine directory", config.quarantine_dir),
        ("log directory", config.log_dir),
        ("manifest directory", config.manifest_dir),
    ):
        _ensure_directory(path, label=label)


def legacy_source_paths(project_root: Path) -> tuple[Path, ...]:
    return (
        project_root / "smart_organizer.db",
        project_root / "smart_organizer.db-wal",
        project_root / "smart_organizer.db-shm",
        project_root / "uploads",
        project_root / "repo",
        project_root / "previews",
        project_root / "logs",
    )


def detect_legacy_data(config: RuntimeConfig) -> LegacyDataStatus:
    legacy_exists = any(path.exists() for path in legacy_source_paths(config.project_root))
    destination_initialized = config.db_path.exists() or any(
        path.exists() and any(path.iterdir()) for path in (config.upload_dir, config.repo_root, config.preview_dir)
    )
    return LegacyDataStatus(
        legacy_root=config.project_root,
        has_legacy_data=legacy_exists,
        destination_initialized=destination_initialized,
        marker_path=config.data_root / MIGRATION_MARKER,
    )


def _copy_sqlite_database(source_db: Path, target_db: Path) -> None:
    target_db.parent.mkdir(parents=True, exist_ok=True)
    if not source_db.exists():
        return
    try:
        source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
        try:
            destination = sqlite3.connect(target_db)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
    except sqlite3.Error as exc:
        raise LegacyDataMigrationError("Failed to copy legacy SQLite database safely") from exc


def _copy_tree_if_present(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if destination.exists():
        raise LegacyDataMigrationError(f"Migration destination already exists: {destination}")
    shutil.copytree(source, destination)


def _acquire_migration_lock(data_root: Path) -> Path:
    data_root.mkdir(parents=True, exist_ok=True)
    lock_path = data_root / MIGRATION_LOCK
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise LegacyDataMigrationError("Legacy data migration is already in progress.") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
        lock_file.write(f"pid={os.getpid()}\n")
    return lock_path


def migrate_legacy_data_if_needed(config: RuntimeConfig) -> LegacyDataStatus:
    status = detect_legacy_data(config)
    if not status.has_legacy_data or status.marker_path.exists():
        return status
    if status.destination_initialized:
        raise LegacyDataMigrationError(
            "Legacy source-adjacent data exists, but the runtime data directory already contains data. "
            "Choose a different SMART_ORGANIZER_DATA_DIR or migrate manually."
        )

    lock_path = _acquire_migration_lock(config.data_root)
    staging = config.data_root / f".migration-{uuid.uuid4().hex}.tmp"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        _copy_sqlite_database(config.project_root / "smart_organizer.db", staging / "smart_organizer.db")
        _copy_tree_if_present(config.project_root / "uploads", staging / "uploads")
        _copy_tree_if_present(config.project_root / "repo", staging / "repository")
        _copy_tree_if_present(config.project_root / "previews", staging / "previews")
        _copy_tree_if_present(config.project_root / "logs", staging / "logs")
        if (staging / "smart_organizer.db").exists():
            with sqlite3.connect(staging / "smart_organizer.db") as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise LegacyDataMigrationError("Migrated SQLite database failed integrity_check")

        ensure_runtime_directories(config)
        for source_name, target in (
            ("smart_organizer.db", config.db_path),
            ("uploads", config.upload_dir),
            ("repository", config.repo_root),
            ("previews", config.preview_dir),
            ("logs", config.log_dir),
        ):
            source = staging / source_name
            if not source.exists():
                continue
            if source.is_file():
                if target.exists():
                    raise LegacyDataMigrationError(f"Migration destination already exists: {target}")
                shutil.copy2(source, target)
            else:
                shutil.copytree(source, target, dirs_exist_ok=True)
        status.marker_path.write_text(
            json.dumps(
                {"version": MIGRATION_VERSION, "legacy_root": str(config.project_root)},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except LegacyDataMigrationError:
        raise
    except Exception as exc:
        raise LegacyDataMigrationError("Legacy data migration failed; source data was left untouched") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        lock_path.unlink(missing_ok=True)
    return detect_legacy_data(config)
