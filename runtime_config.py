from __future__ import annotations

import datetime
import json
import os
import shutil
import socket
import sqlite3
import sys
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict, cast

DATA_DIR_ENV = "SMART_ORGANIZER_DATA_DIR"
APP_AUTHOR = "SmartOrganizer"
APP_DIR_WINDOWS = "SmartOrganizer"
APP_DIR_POSIX = "smart-organizer"
MIGRATION_MARKER = ".smart_organizer_migration.json"
MIGRATION_LOCK = ".smart-organizer-migration.lock"
MIGRATION_STATE = "migration-state.json"
MIGRATION_VERSION = 1
CURRENT_SCHEMA_VERSION = 16
MIGRATION_PREFIX = ".smart-organizer-migration-"
MIGRATED_ARTIFACTS = (
    "database",
    "uploads",
    "repository",
    "previews",
    "quarantine",
    "manifests",
    "logs",
)

MigrationStatus = Literal["preparing", "copying", "verifying", "promoting", "completed", "failed", "rollback_required"]
ArtifactStatus = Literal["pending", "copied", "verified", "promoted", "absent", "failed"]
DestinationState = Literal[
    "absent",
    "empty",
    "initialized_valid",
    "partially_migrated",
    "staging_exists",
    "failed_migration",
    "unrelated_files",
    "active_database",
    "invalid_marker",
]


class ConfigurationError(RuntimeError):
    pass


class RuntimeDirectoryError(ConfigurationError):
    pass


class LegacyDataMigrationError(ConfigurationError):
    pass


class MigrationStateError(LegacyDataMigrationError):
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
    destination_state: DestinationState = "absent"


@dataclass(slots=True)
class MigrationState:
    migration_id: str
    status: MigrationStatus
    legacy_root: Path
    destination_root: Path
    staging_root: Path
    started_at: str
    updated_at: str
    completed_at: str | None = None
    database_verified: bool = False
    artifacts: dict[str, ArtifactStatus] = field(default_factory=dict)
    last_error: str | None = None

    @property
    def state_path(self) -> Path:
        return self.staging_root / MIGRATION_STATE


class MarkerPayload(TypedDict):
    format_version: int
    status: str
    migration_id: str
    legacy_root: str
    destination_root: str
    completed_at: str
    database_verified: bool
    schema_version: int
    migrated_artifacts: list[str]


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def _normalized(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _clean_error(exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:500]


def _default_artifacts() -> dict[str, ArtifactStatus]:
    return dict.fromkeys(MIGRATED_ARTIFACTS, "pending")


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
        return _normalized(raw)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeDirectoryError(f"Runtime data directory is invalid: {raw}") from exc


def build_runtime_config(project_root: Path | None = None, env: dict[str, str] | None = None) -> RuntimeConfig:
    root = _normalized(project_root or Path(__file__).resolve().parent)
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
        project_root / "repository",
        project_root / "previews",
        project_root / "quarantine",
        project_root / "manifests",
        project_root / "logs",
    )


def _staging_parent(config: RuntimeConfig) -> Path:
    return config.data_root.parent


def _state_to_json(state: MigrationState) -> dict[str, object]:
    return {
        "format_version": MIGRATION_VERSION,
        "migration_id": state.migration_id,
        "status": state.status,
        "legacy_root": str(_normalized(state.legacy_root)),
        "destination_root": str(_normalized(state.destination_root)),
        "staging_root": str(_normalized(state.staging_root)),
        "started_at": state.started_at,
        "updated_at": state.updated_at,
        "completed_at": state.completed_at,
        "database_verified": state.database_verified,
        "artifacts": state.artifacts,
        "last_error": state.last_error,
    }


def _fsync_parent(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    _fsync_parent(path.parent)


def _write_state(state: MigrationState, *, status: MigrationStatus | None = None, error: str | None = None) -> None:
    if status is not None:
        state.status = status
    state.updated_at = _utc_now()
    if error is not None:
        state.last_error = error
    _atomic_write_json(state.state_path, _state_to_json(state))


def _load_state(path: Path) -> MigrationState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationStateError(f"Migration state is unreadable: {path}") from exc
    if not isinstance(raw, dict):
        raise MigrationStateError("Migration state must be a JSON object")
    if raw.get("format_version") != MIGRATION_VERSION:
        raise MigrationStateError("Unsupported migration state format version")
    status = raw.get("status")
    if status not in {"preparing", "copying", "verifying", "promoting", "completed", "failed", "rollback_required"}:
        raise MigrationStateError("Migration state has an unsupported status")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, dict) or not set(MIGRATED_ARTIFACTS).issubset(artifacts):
        raise MigrationStateError("Migration state artifacts are incomplete")
    try:
        return MigrationState(
            migration_id=str(raw["migration_id"]),
            status=cast(MigrationStatus, status),
            legacy_root=_normalized(Path(str(raw["legacy_root"]))),
            destination_root=_normalized(Path(str(raw["destination_root"]))),
            staging_root=_normalized(Path(str(raw["staging_root"]))),
            started_at=str(raw["started_at"]),
            updated_at=str(raw["updated_at"]),
            completed_at=cast(str | None, raw.get("completed_at")),
            database_verified=bool(raw.get("database_verified")),
            artifacts={name: cast(ArtifactStatus, str(value)) for name, value in artifacts.items()},
            last_error=cast(str | None, raw.get("last_error")),
        )
    except KeyError as exc:
        raise MigrationStateError(f"Migration state is missing required field: {exc.args[0]}") from exc


def _find_migration_states(config: RuntimeConfig) -> list[MigrationState]:
    parent = _staging_parent(config)
    if not parent.exists():
        return []
    states: list[MigrationState] = []
    for candidate in parent.glob(f"{MIGRATION_PREFIX}*"):
        state_path = candidate / MIGRATION_STATE
        if not state_path.exists():
            continue
        state = _load_state(state_path)
        if _normalized(state.destination_root) == _normalized(config.data_root):
            states.append(state)
    return sorted(states, key=lambda item: item.updated_at, reverse=True)


def _marker_path(config: RuntimeConfig) -> Path:
    return config.data_root / MIGRATION_MARKER


def _required_runtime_dirs(config: RuntimeConfig) -> tuple[Path, ...]:
    return (
        config.upload_dir,
        config.repo_root,
        config.preview_dir,
        config.quarantine_dir,
        config.manifest_dir,
        config.log_dir,
    )


def _verify_database(db_path: Path, *, require_expected_schema: bool = True) -> int:
    if not db_path.exists():
        raise LegacyDataMigrationError(f"Runtime database is missing: {db_path}")
    try:
        with sqlite3.connect(db_path) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise LegacyDataMigrationError("SQLite database failed integrity_check")
            table_names = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if require_expected_schema and "sys_config" not in table_names:
                raise LegacyDataMigrationError("SQLite database is missing expected Smart Organizer tables")
            row = conn.execute("SELECT value FROM sys_config WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error as exc:
        raise LegacyDataMigrationError("SQLite database could not be verified") from exc
    try:
        return int(row[0]) if row else CURRENT_SCHEMA_VERSION
    except (TypeError, ValueError):
        return CURRENT_SCHEMA_VERSION


def _validate_completed_marker(config: RuntimeConfig) -> MarkerPayload:
    marker_path = _marker_path(config)
    try:
        raw = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyDataMigrationError("Completed migration marker is unreadable or malformed") from exc
    if not isinstance(raw, dict):
        raise LegacyDataMigrationError("Completed migration marker must be a JSON object")
    if raw.get("format_version") != MIGRATION_VERSION:
        raise LegacyDataMigrationError("Completed migration marker uses an unsupported version")
    if raw.get("status") != "completed":
        raise LegacyDataMigrationError("Completed migration marker status is not completed")
    if _normalized(Path(str(raw.get("destination_root", "")))) != _normalized(config.data_root):
        raise LegacyDataMigrationError("Completed migration marker points at a different runtime directory")
    _verify_database(config.db_path, require_expected_schema=True)
    missing_dirs = [path.name for path in _required_runtime_dirs(config) if not path.is_dir()]
    if missing_dirs:
        raise LegacyDataMigrationError(f"Completed migration marker is missing required directories: {', '.join(missing_dirs)}")
    active_states = [state for state in _find_migration_states(config) if state.status != "completed"]
    if active_states:
        raise LegacyDataMigrationError("Completed migration marker conflicts with unfinished migration staging")
    return cast(MarkerPayload, raw)


def _destination_contains_known_partial(config: RuntimeConfig) -> bool:
    known = {config.db_path, *_required_runtime_dirs(config), _marker_path(config)}
    if not config.data_root.exists() or not config.data_root.is_dir():
        return False
    ignored = {".smart_organizer_migration.lock"}
    for child in config.data_root.iterdir():
        if child.name in ignored:
            continue
        if child in known or child.name in {"smart_organizer.db-wal", "smart_organizer.db-shm"}:
            return True
    return False


def classify_destination_state(config: RuntimeConfig) -> DestinationState:
    states = _find_migration_states(config)
    if any(state.status == "failed" for state in states):
        return "failed_migration"
    if any(state.status != "completed" for state in states):
        return "staging_exists"
    if not config.data_root.exists():
        return "absent"
    if not config.data_root.is_dir():
        return "unrelated_files"
    marker = _marker_path(config)
    if marker.exists():
        try:
            _validate_completed_marker(config)
            return "initialized_valid"
        except LegacyDataMigrationError:
            return "invalid_marker"
    children = list(config.data_root.iterdir())
    if not children:
        return "empty"
    if config.db_path.exists():
        try:
            _verify_database(config.db_path, require_expected_schema=True)
            return "active_database"
        except LegacyDataMigrationError:
            return "partially_migrated"
    if _destination_contains_known_partial(config):
        return "partially_migrated"
    return "unrelated_files"


def detect_legacy_data(config: RuntimeConfig) -> LegacyDataStatus:
    legacy_exists = any(path.exists() for path in legacy_source_paths(config.project_root))
    destination_state = classify_destination_state(config)
    destination_initialized = destination_state in {"initialized_valid", "active_database"}
    return LegacyDataStatus(
        legacy_root=config.project_root,
        has_legacy_data=legacy_exists,
        destination_initialized=destination_initialized,
        marker_path=_marker_path(config),
        destination_state=destination_state,
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
                destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                destination.execute("PRAGMA journal_mode=DELETE")
            finally:
                destination.close()
        finally:
            source.close()
    except sqlite3.Error as exc:
        raise LegacyDataMigrationError("Failed to copy legacy SQLite database safely") from exc


def _copy_tree_if_present(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return True


def _prepared_path(state: MigrationState) -> Path:
    return state.staging_root / "prepared-data"


def _artifact_sources(project_root: Path) -> dict[str, tuple[Path, ...]]:
    return {
        "uploads": (project_root / "uploads",),
        "repository": (project_root / "repository", project_root / "repo"),
        "previews": (project_root / "previews",),
        "quarantine": (project_root / "quarantine", project_root / ".smart_organizer_quarantine"),
        "manifests": (project_root / "manifests",),
        "logs": (project_root / "logs",),
    }


def _copy_artifacts_to_staging(config: RuntimeConfig, state: MigrationState) -> None:
    prepared = _prepared_path(state)
    prepared.mkdir(parents=True, exist_ok=True)
    _write_state(state, status="copying")
    db_copied = (config.project_root / "smart_organizer.db").exists()
    if db_copied:
        _copy_sqlite_database(config.project_root / "smart_organizer.db", prepared / "smart_organizer.db")
        (prepared / "smart_organizer.db-wal").unlink(missing_ok=True)
        (prepared / "smart_organizer.db-shm").unlink(missing_ok=True)
        state.artifacts["database"] = "copied"
    else:
        state.artifacts["database"] = "absent"
    _write_state(state)

    for artifact, sources in _artifact_sources(config.project_root).items():
        copied = False
        for source in sources:
            if source.exists():
                copied = _copy_tree_if_present(source, prepared / artifact)
                break
        state.artifacts[artifact] = "copied" if copied else "absent"
        _write_state(state)

    for directory in ("uploads", "repository", "previews", "quarantine", "manifests", "logs"):
        (prepared / directory).mkdir(exist_ok=True)


def _verify_prepared_data(state: MigrationState) -> None:
    prepared = _prepared_path(state)
    _write_state(state, status="verifying")
    if state.artifacts.get("database") == "copied":
        _verify_database(prepared / "smart_organizer.db", require_expected_schema=False)
        state.database_verified = True
        state.artifacts["database"] = "verified"
    else:
        state.database_verified = False
    for artifact in MIGRATED_ARTIFACTS:
        if artifact == "database":
            continue
        if state.artifacts.get(artifact) == "copied":
            state.artifacts[artifact] = "verified"
    _write_state(state)


def _build_marker(state: MigrationState, schema_version: int) -> MarkerPayload:
    return {
        "format_version": MIGRATION_VERSION,
        "status": "completed",
        "migration_id": state.migration_id,
        "legacy_root": str(_normalized(state.legacy_root)),
        "destination_root": str(_normalized(state.destination_root)),
        "completed_at": state.completed_at or _utc_now(),
        "database_verified": state.database_verified,
        "schema_version": schema_version,
        "migrated_artifacts": [name for name, value in state.artifacts.items() if value in {"verified", "promoted"}],
    }


def _promote_prepared_data(config: RuntimeConfig, state: MigrationState) -> None:
    prepared = _prepared_path(state)
    if not prepared.exists():
        raise LegacyDataMigrationError("Prepared migration data is missing")
    destination_state = classify_destination_state(config)
    if destination_state not in {"absent", "empty", "staging_exists", "failed_migration"}:
        raise LegacyDataMigrationError(f"Cannot promote migration into destination state: {destination_state}")
    if config.data_root.exists():
        if any(config.data_root.iterdir()):
            raise LegacyDataMigrationError("Cannot promote migration into non-empty destination")
        config.data_root.rmdir()
    _write_state(state, status="promoting")
    try:
        prepared.rename(config.data_root)
    except OSError:
        if config.data_root.exists():
            raise
        promotion_tmp = config.data_root.with_name(f"{config.data_root.name}.promoting-{state.migration_id}.tmp")
        if promotion_tmp.exists():
            shutil.rmtree(promotion_tmp)
        shutil.copytree(prepared, promotion_tmp)
        try:
            promotion_tmp.rename(config.data_root)
        except OSError:
            shutil.rmtree(promotion_tmp, ignore_errors=True)
            raise
        shutil.rmtree(prepared, ignore_errors=True)
    for artifact in MIGRATED_ARTIFACTS:
        if state.artifacts.get(artifact) in {"verified", "absent"}:
            state.artifacts[artifact] = "promoted" if state.artifacts[artifact] == "verified" else "absent"
    if config.db_path.exists():
        schema_version = _verify_database(config.db_path, require_expected_schema=False)
    else:
        schema_version = CURRENT_SCHEMA_VERSION
    state.completed_at = _utc_now()
    state.status = "completed"
    state.database_verified = state.database_verified or not config.db_path.exists()
    _atomic_write_json(_marker_path(config), cast(dict[str, object], _build_marker(state, schema_version)))
    _write_state(state, status="completed")
    _validate_completed_marker(config)


def _new_state(config: RuntimeConfig) -> MigrationState:
    migration_id = uuid.uuid4().hex
    staging_root = _staging_parent(config) / f"{MIGRATION_PREFIX}{migration_id}"
    now = _utc_now()
    return MigrationState(
        migration_id=migration_id,
        status="preparing",
        legacy_root=config.project_root,
        destination_root=config.data_root,
        staging_root=staging_root,
        started_at=now,
        updated_at=now,
        artifacts=_default_artifacts(),
    )


def _lock_path(config: RuntimeConfig) -> Path:
    return _staging_parent(config) / MIGRATION_LOCK


def _write_lock_metadata(fd: int) -> None:
    metadata = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at": _utc_now(),
    }
    with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
        json.dump(metadata, lock_file, sort_keys=True)
        lock_file.write("\n")
        lock_file.flush()
        os.fsync(lock_file.fileno())


def _acquire_migration_lock(config: RuntimeConfig) -> Path:
    parent = _staging_parent(config)
    parent.mkdir(parents=True, exist_ok=True)
    legacy_lock = config.data_root / ".smart_organizer_migration.lock"
    if legacy_lock.exists():
        raise LegacyDataMigrationError("Legacy data migration is already in progress.")
    lock_path = _lock_path(config)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise LegacyDataMigrationError(f"Legacy data migration is already in progress: {lock_path}") from exc
    _write_lock_metadata(fd)
    return lock_path


def _run_state_machine(config: RuntimeConfig, state: MigrationState) -> None:
    try:
        if state.status == "failed":
            if state.staging_root.exists():
                shutil.rmtree(state.staging_root)
            state = _new_state(config)
            _write_state(state, status="preparing")
        elif state.status in {"preparing", "copying"}:
            if _prepared_path(state).exists():
                shutil.rmtree(_prepared_path(state))
        elif state.status == "rollback_required":
            raise LegacyDataMigrationError("Previous migration requires manual rollback review before retry")

        if state.status in {"preparing", "copying"}:
            _copy_artifacts_to_staging(config, state)
        if state.status in {"copying", "verifying"}:
            _verify_prepared_data(state)
        if state.status in {"verifying", "promoting"}:
            _promote_prepared_data(config, state)
    except Exception as exc:
        with suppress(Exception):
            _write_state(state, status="failed", error=_clean_error(exc))
        if isinstance(exc, LegacyDataMigrationError):
            raise
        raise LegacyDataMigrationError("Legacy data migration failed; source data was left untouched") from exc


def migrate_legacy_data_if_needed(config: RuntimeConfig) -> LegacyDataStatus:
    status = detect_legacy_data(config)
    if not status.has_legacy_data:
        if _marker_path(config).exists():
            _validate_completed_marker(config)
        return status
    legacy_lock = config.data_root / ".smart_organizer_migration.lock"
    if legacy_lock.exists():
        raise LegacyDataMigrationError("Legacy data migration is already in progress.")
    if status.destination_state == "initialized_valid":
        raise LegacyDataMigrationError(
            "Legacy source-adjacent data exists, but the runtime data directory already contains validated data. "
            "Choose a different SMART_ORGANIZER_DATA_DIR or migrate manually."
        )
    if status.destination_state == "active_database":
        raise LegacyDataMigrationError(
            "Legacy source-adjacent data exists, but the runtime data directory contains an active database. "
            "Choose a different SMART_ORGANIZER_DATA_DIR or migrate manually."
        )
    if status.destination_state in {"unrelated_files", "partially_migrated", "invalid_marker"}:
        raise LegacyDataMigrationError(
            f"Legacy source-adjacent data exists, but the runtime data directory already contains data "
            f"({status.destination_state}). Choose a different SMART_ORGANIZER_DATA_DIR or migrate manually."
        )

    lock_path = _acquire_migration_lock(config)
    try:
        states = _find_migration_states(config)
        active = next((state for state in states if state.status != "completed"), None)
        state = active or _new_state(config)
        if not state.state_path.exists():
            _write_state(state, status="preparing")
        _run_state_machine(config, state)
    finally:
        lock_path.unlink(missing_ok=True)
    return detect_legacy_data(config)
