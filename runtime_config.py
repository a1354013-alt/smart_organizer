from __future__ import annotations

import datetime
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict, cast

from sqlite_utils import open_sqlite
from storage_db_schema import (
    CURRENT_SCHEMA_VERSION,
    SchemaStatus,
    expected_runtime_tables,
    inspect_database_schema,
    upgrade_database_schema,
)

DATA_DIR_ENV = "SMART_ORGANIZER_DATA_DIR"
APP_AUTHOR = "SmartOrganizer"
APP_DIR_WINDOWS = "SmartOrganizer"
APP_DIR_POSIX = "smart-organizer"
MIGRATION_MARKER = ".smart_organizer_migration.json"
MIGRATION_LOCK = ".smart-organizer-migration.lock"
MIGRATION_STATE = "migration-state.json"
MIGRATION_VERSION = 1
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

MigrationStatus = Literal[
    "preparing",
    "copying",
    "verifying",
    "promoting",
    "completed",
    "failed",
    "rollback_required",
    "manual_recovery_required",
]
ArtifactStatus = Literal["pending", "copied", "verified", "promoted", "absent", "failed"]
DatabaseSource = Literal["migrated", "newly_created"]
DestinationState = Literal[
    "absent",
    "empty",
    "valid_completed_migration",
    "valid_unrelated_installation",
    "recognized_interrupted_migration",
    "invalid_completed_marker",
    "partial_promoted_destination",
    "unknown_non_empty_destination",
    "corrupted_destination_db",
    "directory_only_destination_without_db",
    "active_migration",
    "stale_migration_lock",
    "failed_migration",
]


class ConfigurationError(RuntimeError):
    pass


class RuntimeDirectoryError(ConfigurationError):
    pass


class LegacyDataMigrationError(ConfigurationError):
    pass


class MigrationStateError(LegacyDataMigrationError):
    pass


class MigrationStateValidationError(MigrationStateError):
    pass


class MigrationContainmentError(MigrationStateValidationError):
    pass


class MigrationMarkerValidationError(LegacyDataMigrationError):
    pass


class MigrationLockError(LegacyDataMigrationError):
    pass


class MigrationRecoveryError(LegacyDataMigrationError):
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
    database_source: DatabaseSource | None = None
    promotion_started_at: str | None = None

    @property
    def state_path(self) -> Path:
        return self.staging_root / MIGRATION_STATE


class MarkerPayload(TypedDict):
    format_version: int
    status: str
    migration_id: str
    legacy_root: str
    destination_root: str
    started_at: str
    completed_at: str
    database_verified: bool
    database_source: str
    schema_version: int
    migrated_artifacts: list[str]


TERMINAL_RECOVERY_STATES = {"manual_recovery_required", "rollback_required", "completed"}


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def _normalized(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _clean_error(exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:500]


def _default_artifacts() -> dict[str, ArtifactStatus]:
    return dict.fromkeys(MIGRATED_ARTIFACTS, "pending")


def _parse_iso_timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationStateValidationError(f"{label} must be a non-empty ISO timestamp")
    try:
        datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise MigrationStateValidationError(f"{label} is not a valid ISO timestamp") from exc
    return value


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _require_under_migration_parent(config: RuntimeConfig, path: Path, *, label: str, allow_parent: bool = False) -> Path:
    migration_parent = _normalized(_staging_parent(config))
    resolved = _normalized(path)
    if resolved == migration_parent and allow_parent:
        return resolved
    if not _is_relative_to(resolved, migration_parent):
        raise MigrationContainmentError(f"{label} escapes the approved migration parent")
    return resolved


def _validate_exact_child(parent: Path, path: Path, *, expected_name: str, label: str) -> Path:
    resolved = _normalized(path)
    if resolved.parent != parent or resolved.name != expected_name:
        raise MigrationContainmentError(f"{label} is not at the expected migration path")
    return resolved


def validate_migration_staging_root(
    config: RuntimeConfig,
    state_path: Path,
    serialized_staging_root: Path,
) -> tuple[Path, Path]:
    actual_state_path = _normalized(state_path)
    actual_staging_root = actual_state_path.parent
    migration_parent = _normalized(_staging_parent(config))
    if actual_staging_root.parent != migration_parent:
        raise MigrationContainmentError("Migration staging root is outside the approved migration parent")
    if not actual_staging_root.name.startswith(MIGRATION_PREFIX):
        raise MigrationContainmentError("Migration staging root does not use the approved prefix")
    if actual_state_path.name != MIGRATION_STATE:
        raise MigrationContainmentError("Migration state file has an unexpected name")
    if _normalized(serialized_staging_root) != actual_staging_root:
        raise MigrationContainmentError("Migration state staging_root does not match the state file location")
    _require_under_migration_parent(config, actual_state_path, label="migration state file")
    return actual_staging_root, actual_state_path


def safe_resolve_prepared_root(config: RuntimeConfig, state: MigrationState) -> Path:
    staging_root, _ = validate_migration_staging_root(config, state.state_path, state.staging_root)
    prepared = _normalized(staging_root / "prepared-data")
    if prepared.parent != staging_root or prepared.name != "prepared-data":
        raise MigrationContainmentError("Prepared migration data path is not inside staging")
    return prepared


def _safe_resolve_promotion_identity(config: RuntimeConfig, state: MigrationState, root: Path) -> Path:
    resolved_root = _normalized(root)
    if resolved_root not in {_normalized(config.data_root), safe_resolve_prepared_root(config, state)}:
        raise MigrationContainmentError("Promotion identity target is not an approved migration root")
    return resolved_root / ".smart_organizer_promotion.json"


def _safe_state_temp_path(config: RuntimeConfig, state_path: Path, temp_path: Path) -> Path:
    staging_root, actual_state_path = validate_migration_staging_root(config, state_path, state_path.parent)
    resolved_temp = _normalized(temp_path)
    if resolved_temp.parent != staging_root or not resolved_temp.name.startswith(f"{actual_state_path.name}."):
        raise MigrationContainmentError("Temporary migration state path is outside staging")
    return resolved_temp


def _safe_marker_path(config: RuntimeConfig) -> Path:
    marker = _normalized(_marker_path(config))
    data_root = _normalized(config.data_root)
    if marker.parent != data_root or marker.name != MIGRATION_MARKER:
        raise MigrationContainmentError("Completed migration marker path is outside the runtime root")
    return marker


def _safe_lock_path(config: RuntimeConfig) -> Path:
    lock_path = _normalized(_lock_path(config))
    parent = _normalized(_staging_parent(config))
    if lock_path.parent != parent or lock_path.name != MIGRATION_LOCK:
        raise MigrationContainmentError("Migration lock path is unsafe")
    return lock_path


def safe_remove_migration_staging(config: RuntimeConfig, state: MigrationState, target: Path | None = None) -> None:
    staging_root, _ = validate_migration_staging_root(config, state.state_path, state.staging_root)
    resolved_target = _normalized(target or staging_root)
    approved = {staging_root, safe_resolve_prepared_root(config, state)}
    if resolved_target not in approved:
        raise MigrationContainmentError("Refusing to remove an unapproved migration staging path")
    if resolved_target.exists() and resolved_target.is_symlink():
        raise MigrationContainmentError("Refusing to remove symlinked migration staging path")
    if resolved_target.exists():
        shutil.rmtree(resolved_target, ignore_errors=True)


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
        "database_source": state.database_source,
        "promotion_started_at": state.promotion_started_at,
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


LEGAL_TRANSITIONS: dict[MigrationStatus, set[MigrationStatus]] = {
    "preparing": {"preparing", "copying", "failed"},
    "copying": {"copying", "verifying", "failed"},
    "verifying": {"verifying", "promoting", "failed"},
    "promoting": {"promoting", "completed", "rollback_required", "manual_recovery_required", "failed"},
    "failed": {"preparing"},
    "rollback_required": {"failed", "completed"},
    "manual_recovery_required": {"failed", "completed"},
    "completed": {"completed"},
}


def safe_write_migration_state(
    config: RuntimeConfig,
    state: MigrationState,
    *,
    status: MigrationStatus | None = None,
    error: str | None = None,
) -> None:
    state_path = state.state_path
    validate_migration_staging_root(config, state_path, state.staging_root)
    if status is not None:
        transition_migration_state(config, state, new_status=status, write=False)
    state.updated_at = _utc_now()
    if status == "completed":
        state.completed_at = state.completed_at or state.updated_at
    if error is not None:
        state.last_error = error
    temp = state_path.with_name(f"{state_path.name}.{uuid.uuid4().hex}.tmp")
    _safe_state_temp_path(config, state_path, temp)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _state_to_json(state)
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, state_path)
    _fsync_parent(state_path.parent)


def transition_migration_state(
    config: RuntimeConfig,
    state: MigrationState,
    *,
    new_status: MigrationStatus,
    expected_current: set[MigrationStatus] | None = None,
    write: bool = True,
) -> None:
    if expected_current is not None and state.status not in expected_current:
        raise MigrationStateValidationError(f"Migration state is {state.status}, expected {sorted(expected_current)}")
    allowed = LEGAL_TRANSITIONS.get(state.status, set())
    if new_status not in allowed:
        raise MigrationStateValidationError(f"Illegal migration state transition: {state.status} -> {new_status}")
    state.status = new_status
    if write:
        safe_write_migration_state(config, state)


def _write_state(
    config: RuntimeConfig,
    state: MigrationState,
    *,
    status: MigrationStatus | None = None,
    error: str | None = None,
) -> None:
    if status is not None:
        safe_write_migration_state(config, state, status=status, error=error)
    else:
        safe_write_migration_state(config, state, error=error)


def _validate_migration_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationStateValidationError("Migration ID must be a non-empty string")
    return value


def _load_state(config: RuntimeConfig, path: Path) -> MigrationState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationStateError(f"Migration state is unreadable: {path}") from exc
    if not isinstance(raw, dict):
        raise MigrationStateError("Migration state must be a JSON object")
    if raw.get("format_version") != MIGRATION_VERSION:
        raise MigrationStateError("Unsupported migration state format version")
    status = raw.get("status")
    if status not in set(LEGAL_TRANSITIONS):
        raise MigrationStateError("Migration state has an unsupported status")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(MIGRATED_ARTIFACTS):
        raise MigrationStateError("Migration state artifacts are incomplete")
    artifact_values = {"pending", "copied", "verified", "promoted", "absent", "failed"}
    if any(value not in artifact_values for value in artifacts.values()):
        raise MigrationStateError("Migration state artifacts contain an unsupported status")
    migration_id = _validate_migration_id(raw.get("migration_id"))
    serialized_staging = _normalized(Path(str(raw.get("staging_root", ""))))
    actual_staging_root, _ = validate_migration_staging_root(config, path, serialized_staging)
    destination_root = _normalized(Path(str(raw.get("destination_root", ""))))
    if destination_root != _normalized(config.data_root):
        raise MigrationStateValidationError("Migration state destination does not match active RuntimeConfig")
    database_source = raw.get("database_source")
    if database_source is not None and database_source not in {"migrated", "newly_created"}:
        raise MigrationStateValidationError("Migration state database_source is unsupported")
    promotion_started_at = raw.get("promotion_started_at")
    if promotion_started_at is not None:
        promotion_started_at = _parse_iso_timestamp(promotion_started_at, label="promotion_started_at")
    try:
        return MigrationState(
            migration_id=migration_id,
            status=cast(MigrationStatus, status),
            legacy_root=_normalized(Path(str(raw["legacy_root"]))),
            destination_root=destination_root,
            staging_root=actual_staging_root,
            started_at=_parse_iso_timestamp(raw["started_at"], label="started_at"),
            updated_at=_parse_iso_timestamp(raw["updated_at"], label="updated_at"),
            completed_at=(
                _parse_iso_timestamp(raw["completed_at"], label="completed_at")
                if raw.get("completed_at") is not None
                else None
            ),
            database_verified=bool(raw.get("database_verified")),
            artifacts={name: cast(ArtifactStatus, str(value)) for name, value in artifacts.items()},
            last_error=cast(str | None, raw.get("last_error")),
            database_source=cast(DatabaseSource | None, database_source),
            promotion_started_at=cast(str | None, promotion_started_at),
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
        state = _load_state(config, state_path)
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
    inspection = inspect_database_schema(db_path)
    if inspection.status == SchemaStatus.CORRUPT:
        raise LegacyDataMigrationError(inspection.details or "SQLite database could not be verified")
    if inspection.status == SchemaStatus.MISSING:
        raise LegacyDataMigrationError(inspection.details or "SQLite database schema_version is missing")
    if inspection.status == SchemaStatus.INVALID:
        raise LegacyDataMigrationError(inspection.details or "SQLite database schema metadata is invalid")
    if inspection.status == SchemaStatus.FUTURE:
        raise LegacyDataMigrationError(inspection.details or "SQLite database uses a future schema version")
    if require_expected_schema and inspection.status != SchemaStatus.VALID:
        raise LegacyDataMigrationError(inspection.details or "SQLite database schema does not match the runtime")
    if require_expected_schema:
        missing_runtime_tables = sorted(
            {"sys_config", "files", "tags", "file_tags", "file_content_fts"} - expected_runtime_tables(db_path)
        )
        if missing_runtime_tables:
            raise LegacyDataMigrationError(
                f"SQLite database is missing expected Smart Organizer tables: {', '.join(missing_runtime_tables)}"
            )
    if inspection.version is None:
        raise LegacyDataMigrationError("SQLite database schema version could not be determined")
    return inspection.version


def _create_new_runtime_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open_sqlite(db_path) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS sys_config (key TEXT PRIMARY KEY, value TEXT)")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_name TEXT,
                    safe_name TEXT,
                    final_name TEXT,
                    temp_path TEXT,
                    final_path TEXT,
                    preview_path TEXT,
                    moving_target_path TEXT,
                    file_hash TEXT UNIQUE,
                    file_type TEXT,
                    standard_date TEXT,
                    main_topic TEXT,
                    summary TEXT,
                    summary_status TEXT,
                    summary_error TEXT,
                    classification_reason TEXT,
                    final_decision_reason TEXT,
                    manual_override INTEGER DEFAULT 0,
                    decision_source TEXT,
                    decision_updated_at TEXT,
                    last_manual_topic TEXT,
                    last_manual_reason TEXT,
                    is_scanned INTEGER DEFAULT 0,
                    last_error TEXT,
                    status TEXT DEFAULT 'PENDING',
                    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
                    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'))
                )
                """
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS tags (tag_id INTEGER PRIMARY KEY AUTOINCREMENT, tag_name TEXT UNIQUE)"
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS file_tags (
                    file_id INTEGER, tag_id INTEGER, confidence REAL,
                    PRIMARY KEY (file_id, tag_id),
                    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS file_content_fts USING fts5(
                    original_filename,
                    title,
                    summary,
                    content,
                    tokenize='unicode61'
                )
                """
            )
            cursor.execute(
                "INSERT OR REPLACE INTO sys_config (key, value) VALUES (?, ?)",
                ("schema_version", str(CURRENT_SCHEMA_VERSION)),
            )
    except sqlite3.Error as exc:
        raise LegacyDataMigrationError("Failed to create directory-only migration database") from exc


def _require_marker_string(raw: dict[object, object], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MigrationMarkerValidationError(f"Completed migration marker missing required field: {field}")
    return value


def _current_lock_owner_token(config: RuntimeConfig) -> str | None:
    metadata = _read_lock_metadata(config)
    owner_token = metadata.get("owner_token")
    return str(owner_token) if isinstance(owner_token, str) and owner_token.strip() else None


def _marker_artifacts(raw: dict[object, object]) -> list[str]:
    artifacts = raw.get("migrated_artifacts")
    if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
        raise MigrationMarkerValidationError("Completed migration marker has invalid migrated_artifacts")
    if len(set(artifacts)) != len(artifacts):
        raise MigrationMarkerValidationError("Completed migration marker contains duplicate artifacts")
    unknown_artifacts = set(artifacts) - set(MIGRATED_ARTIFACTS)
    if unknown_artifacts:
        raise MigrationMarkerValidationError("Completed migration marker contains unknown artifacts")
    if "database" not in artifacts:
        raise MigrationMarkerValidationError("Completed migration marker must record the migrated database artifact")
    return cast(list[str], artifacts)


def _validate_completed_marker(
    config: RuntimeConfig,
    *,
    expected_migration_id: str | None = None,
    expected_legacy_root: Path | None = None,
    expected_state: MigrationState | None = None,
    allowed_lock_owner: str | None = None,
) -> MarkerPayload:
    marker_path = _safe_marker_path(config)
    if _lock_path(config).exists():
        classification = _classify_existing_lock(config)
        if classification == "stale_local":
            _remove_stale_lock(config)
        elif allowed_lock_owner is not None and classification == "active_local":
            if _current_lock_owner_token(config) != allowed_lock_owner:
                raise MigrationMarkerValidationError("Completed migration marker lock owner does not match the active recovery process")
        else:
            raise MigrationMarkerValidationError("Completed migration marker has an unresolved active migration lock")
    try:
        raw = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationMarkerValidationError("Completed migration marker is unreadable or malformed") from exc
    if not isinstance(raw, dict):
        raise MigrationMarkerValidationError("Completed migration marker must be a JSON object")
    if raw.get("format_version") != MIGRATION_VERSION:
        raise MigrationMarkerValidationError("Completed migration marker uses an unsupported version")
    if raw.get("status") != "completed":
        raise MigrationMarkerValidationError("Completed migration marker status is not completed")
    migration_id = _validate_migration_id(raw.get("migration_id"))
    if expected_migration_id is not None and migration_id != expected_migration_id:
        raise MigrationMarkerValidationError("Completed migration marker migration ID does not match the recovery state")
    legacy_root = _normalized(Path(_require_marker_string(cast(dict[object, object], raw), "legacy_root")))
    if legacy_root != _normalized(expected_legacy_root or config.project_root):
        raise MigrationMarkerValidationError("Completed migration marker points at a different legacy root")
    if _normalized(Path(_require_marker_string(cast(dict[object, object], raw), "destination_root"))) != _normalized(
        config.data_root
    ):
        raise MigrationMarkerValidationError("Completed migration marker points at a different runtime directory")
    _parse_iso_timestamp(raw.get("started_at"), label="started_at")
    _parse_iso_timestamp(raw.get("completed_at"), label="completed_at")
    if raw.get("database_verified") is not True:
        raise MigrationMarkerValidationError("Completed migration marker does not confirm database verification")
    if raw.get("database_source") not in {"migrated", "newly_created"}:
        raise MigrationMarkerValidationError("Completed migration marker database_source is unsupported")
    if not isinstance(raw.get("schema_version"), int) or raw.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise MigrationMarkerValidationError("Completed migration marker schema version does not match runtime schema")
    artifacts = _marker_artifacts(cast(dict[object, object], raw))
    schema_version = _verify_database(config.db_path, require_expected_schema=True)
    if schema_version != CURRENT_SCHEMA_VERSION:
        raise MigrationMarkerValidationError("Runtime database schema version does not match the completed marker")
    missing_dirs = [path.name for path in _required_runtime_dirs(config) if not path.is_dir()]
    if missing_dirs:
        raise MigrationMarkerValidationError(
            f"Completed migration marker is missing required directories: {', '.join(missing_dirs)}"
        )
    for artifact in artifacts:
        if artifact == "database":
            continue
        artifact_path = config.data_root / artifact
        if not artifact_path.exists():
            raise MigrationMarkerValidationError(f"Completed migration marker claims a missing artifact: {artifact}")
    if expected_state is not None:
        if expected_state.database_source != raw.get("database_source"):
            raise MigrationMarkerValidationError("Completed migration marker database_source does not match the migration state")
        expected_artifacts = {
            name
            for name, value in expected_state.artifacts.items()
            if value in {"verified", "promoted"}
        }
        if set(artifacts) != expected_artifacts:
            raise MigrationMarkerValidationError("Completed migration marker artifacts do not match the migration state")
    active_states = [state for state in _find_migration_states(config) if state.status != "completed"]
    if active_states:
        if any(state.migration_id == migration_id and state.status == "promoting" for state in active_states):
            return cast(MarkerPayload, raw)
        raise MigrationMarkerValidationError("Completed migration marker conflicts with unfinished migration staging")
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
    if _lock_path(config).exists():
        try:
            classification = _classify_existing_lock(config)
            if classification == "stale_local":
                return "stale_migration_lock"
            return "active_migration"
        except MigrationLockError:
            return "active_migration"
    if any(state.status == "failed" for state in states):
        return "failed_migration"
    if any(state.status in {"rollback_required", "manual_recovery_required"} for state in states):
        return "partial_promoted_destination"
    if any(state.status != "completed" for state in states):
        return "recognized_interrupted_migration"
    if not config.data_root.exists():
        return "absent"
    if not config.data_root.is_dir():
        return "unknown_non_empty_destination"
    marker = _marker_path(config)
    if marker.exists():
        try:
            _validate_completed_marker(config)
            return "valid_completed_migration"
        except LegacyDataMigrationError:
            return "invalid_completed_marker"
    children = list(config.data_root.iterdir())
    if not children:
        return "empty"
    if config.db_path.exists():
        try:
            _verify_database(config.db_path, require_expected_schema=True)
            return "valid_unrelated_installation"
        except LegacyDataMigrationError:
            return "corrupted_destination_db"
    known_runtime_dirs = set(_required_runtime_dirs(config))
    if any(child in known_runtime_dirs for child in children):
        return "directory_only_destination_without_db"
    if _destination_contains_known_partial(config):
        return "partial_promoted_destination"
    return "unknown_non_empty_destination"


def detect_legacy_data(config: RuntimeConfig) -> LegacyDataStatus:
    legacy_exists = any(path.exists() for path in legacy_source_paths(config.project_root))
    destination_state = classify_destination_state(config)
    destination_initialized = destination_state in {"valid_completed_migration", "valid_unrelated_installation"}
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
        with open_sqlite(f"file:{source_db}?mode=ro") as source_conn, open_sqlite(target_db) as destination_conn:
            source_conn.backup(destination_conn)
            destination_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            destination_conn.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error as exc:
        raise LegacyDataMigrationError("Failed to copy legacy SQLite database safely") from exc


def _remove_staged_artifact(config: RuntimeConfig, state: MigrationState, destination: Path) -> None:
    prepared = safe_resolve_prepared_root(config, state)
    resolved = _normalized(destination)
    if not _is_relative_to(resolved, prepared) or resolved == prepared:
        raise MigrationContainmentError("Refusing to remove staged artifact outside prepared data")
    if resolved.exists() and resolved.is_symlink():
        raise MigrationContainmentError("Refusing to remove symlinked staged artifact")
    if resolved.exists():
        shutil.rmtree(resolved)


def _is_windows_reparse_point(path: Path) -> bool:
    try:
        st_result = os.lstat(path)
    except OSError:
        return False
    file_attributes = getattr(st_result, "st_file_attributes", 0)
    return bool(file_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def validate_legacy_artifact_tree(
    source_root: Path,
    approved_legacy_root: Path,
    *,
    artifact_name: str,
) -> None:
    approved_root = _normalized(approved_legacy_root)
    source_root = _normalized(source_root)
    if not source_root.exists():
        return
    if source_root.is_symlink() or _is_windows_reparse_point(source_root):
        raise LegacyDataMigrationError(f"{artifact_name} migration rejects symlinked or reparse-point source root")
    stack = [source_root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                entry_path = Path(entry.path)
                relative = entry_path.relative_to(source_root)
                if entry.is_symlink() or _is_windows_reparse_point(entry_path):
                    raise LegacyDataMigrationError(
                        f"{artifact_name} migration rejects unsafe linked entry: {relative}"
                    )
                if entry.is_dir(follow_symlinks=False):
                    if not _is_relative_to(_normalized(entry_path), approved_root):
                        raise LegacyDataMigrationError(f"{artifact_name} migration entry escapes legacy root: {relative}")
                    stack.append(entry_path)


def _copy_directory_contents(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with os.scandir(source) as entries:
        for entry in entries:
            source_path = Path(entry.path)
            target_path = destination / entry.name
            if entry.is_dir(follow_symlinks=False):
                _copy_directory_contents(source_path, target_path)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)


def _copy_tree_if_present(source: Path, destination: Path, *, config: RuntimeConfig, state: MigrationState) -> bool:
    if not source.exists():
        return False
    validate_legacy_artifact_tree(source, config.project_root, artifact_name=source.name)
    if destination.exists():
        _remove_staged_artifact(config, state, destination)
    _copy_directory_contents(source, destination)
    return True


def _directory_has_entries(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


def _files_identical(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_handle, right.open("rb") as right_handle:
        while True:
            left_chunk = left_handle.read(1024 * 1024)
            right_chunk = right_handle.read(1024 * 1024)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def _merge_artifact_sources(
    config: RuntimeConfig,
    state: MigrationState,
    sources: tuple[Path, ...],
    destination: Path,
    *,
    artifact_name: str,
) -> bool:
    existing = [source for source in sources if source.exists()]
    if not existing:
        return False
    for source in existing:
        validate_legacy_artifact_tree(source, config.project_root, artifact_name=artifact_name)
    non_empty = [source for source in existing if _directory_has_entries(source)]
    selected = non_empty or existing[:1]
    if destination.exists():
        _remove_staged_artifact(config, state, destination)
    destination.mkdir(parents=True, exist_ok=True)
    case_seen: dict[str, Path] = {}
    for source in selected:
        for child in source.rglob("*"):
            relative = child.relative_to(source)
            key = str(relative).casefold() if os.name == "nt" else str(relative)
            prior = case_seen.get(key)
            if prior is not None and prior != relative:
                raise LegacyDataMigrationError(
                    f"{artifact_name.capitalize()} migration has a case-only path collision: {prior} and {relative}"
                )
            case_seen[key] = relative
            target = destination / relative
            if child.is_dir():
                if target.exists() and not target.is_dir():
                    raise LegacyDataMigrationError(f"{artifact_name.capitalize()} migration path conflict: {relative}")
                target.mkdir(parents=True, exist_ok=True)
                continue
            if child.is_symlink():
                raise LegacyDataMigrationError(f"{artifact_name.capitalize()} migration refuses symlinked source file: {relative}")
            if target.exists():
                if target.is_file() and _files_identical(child, target):
                    continue
                raise LegacyDataMigrationError(f"{artifact_name.capitalize()} migration file conflict: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)
    return True


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
    prepared = safe_resolve_prepared_root(config, state)
    prepared.mkdir(parents=True, exist_ok=True)
    _write_state(config, state, status="copying")
    db_copied = (config.project_root / "smart_organizer.db").exists()
    if db_copied:
        _copy_sqlite_database(config.project_root / "smart_organizer.db", prepared / "smart_organizer.db")
        (prepared / "smart_organizer.db-wal").unlink(missing_ok=True)
        (prepared / "smart_organizer.db-shm").unlink(missing_ok=True)
        state.artifacts["database"] = "copied"
        state.database_source = "migrated"
    else:
        _create_new_runtime_database(prepared / "smart_organizer.db")
        state.artifacts["database"] = "copied"
        state.database_source = "newly_created"
    _write_state(config, state)

    for artifact, sources in _artifact_sources(config.project_root).items():
        if artifact in {"repository", "quarantine"}:
            copied = _merge_artifact_sources(
                config,
                state,
                sources,
                prepared / artifact,
                artifact_name=artifact,
            )
        else:
            copied = False
            for source in sources:
                if source.exists():
                    copied = _copy_tree_if_present(source, prepared / artifact, config=config, state=state)
                    break
        state.artifacts[artifact] = "copied" if copied else "absent"
        _write_state(config, state)

    for directory in ("uploads", "repository", "previews", "quarantine", "manifests", "logs"):
        (prepared / directory).mkdir(exist_ok=True)


def _verify_prepared_data_with_config(config: RuntimeConfig, state: MigrationState) -> None:
    prepared = safe_resolve_prepared_root(config, state)
    _write_state(config, state, status="verifying")
    try:
        upgrade_database_schema(prepared / "smart_organizer.db")
    except RuntimeError as exc:
        raise LegacyDataMigrationError(str(exc)) from exc
    _verify_database(prepared / "smart_organizer.db", require_expected_schema=True)
    state.database_verified = True
    state.artifacts["database"] = "verified"
    for artifact in MIGRATED_ARTIFACTS:
        if artifact == "database":
            continue
        if state.artifacts.get(artifact) == "copied":
            state.artifacts[artifact] = "verified"
    _write_state(config, state)


def _build_marker(state: MigrationState, schema_version: int) -> MarkerPayload:
    return {
        "format_version": MIGRATION_VERSION,
        "status": "completed",
        "migration_id": state.migration_id,
        "legacy_root": str(_normalized(state.legacy_root)),
        "destination_root": str(_normalized(state.destination_root)),
        "started_at": state.started_at,
        "completed_at": state.completed_at or _utc_now(),
        "database_verified": state.database_verified,
        "database_source": state.database_source or "migrated",
        "schema_version": schema_version,
        "migrated_artifacts": [name for name, value in state.artifacts.items() if value in {"verified", "promoted"}],
    }


def _write_promotion_identity(config: RuntimeConfig, state: MigrationState, root: Path) -> None:
    state.promotion_started_at = state.promotion_started_at or _utc_now()
    identity_path = _safe_resolve_promotion_identity(config, state, root)
    payload = {
        "format_version": MIGRATION_VERSION,
        "migration_id": state.migration_id,
        "legacy_root": str(_normalized(state.legacy_root)),
        "destination_root": str(_normalized(config.data_root)),
        "promotion_started_at": state.promotion_started_at,
    }
    _atomic_write_json(identity_path, payload)


def _verify_promotion_identity(config: RuntimeConfig, state: MigrationState, root: Path) -> None:
    identity_path = _safe_resolve_promotion_identity(config, state, root)
    try:
        raw = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationRecoveryError("Promoted destination identity is missing or malformed") from exc
    if not isinstance(raw, dict):
        raise MigrationRecoveryError("Promoted destination identity must be a JSON object")
    if raw.get("migration_id") != state.migration_id:
        raise MigrationRecoveryError("Promoted destination belongs to a different migration")
    if _normalized(Path(str(raw.get("legacy_root", "")))) != _normalized(state.legacy_root):
        raise MigrationRecoveryError("Promoted destination legacy root does not match migration state")
    if _normalized(Path(str(raw.get("destination_root", "")))) != _normalized(config.data_root):
        raise MigrationRecoveryError("Promoted destination root does not match active RuntimeConfig")


def _finalize_promoted_destination(config: RuntimeConfig, state: MigrationState, *, lock_owner: str | None) -> None:
    _verify_promotion_identity(config, state, config.data_root)
    schema_version = _verify_database(config.db_path, require_expected_schema=True)
    for directory in _required_runtime_dirs(config):
        if not directory.is_dir():
            raise MigrationRecoveryError(f"Promoted destination is missing required directory: {directory.name}")
    for artifact in MIGRATED_ARTIFACTS:
        if state.artifacts.get(artifact) in {"verified", "copied"}:
            state.artifacts[artifact] = "promoted"
    state.completed_at = _utc_now()
    state.database_verified = True
    state.status = "completed"
    _atomic_write_json(_safe_marker_path(config), cast(dict[str, object], _build_marker(state, schema_version)))
    _validate_completed_marker(
        config,
        expected_migration_id=state.migration_id,
        expected_legacy_root=state.legacy_root,
        expected_state=state,
        allowed_lock_owner=lock_owner,
    )
    _write_state(config, state, status="completed")
    with suppress(OSError):
        state.state_path.unlink()
    safe_remove_migration_staging(config, state)


def _promote_prepared_data(config: RuntimeConfig, state: MigrationState, *, lock_owner: str | None) -> None:
    prepared = safe_resolve_prepared_root(config, state)
    marker_exists = _marker_path(config).exists()
    if marker_exists and config.data_root.exists():
        _validate_completed_marker(
            config,
            expected_migration_id=state.migration_id,
            expected_legacy_root=state.legacy_root,
            expected_state=state,
            allowed_lock_owner=lock_owner,
        )
        _finalize_promoted_destination(config, state, lock_owner=lock_owner)
        return
    if not prepared.exists() and config.data_root.exists():
        try:
            _finalize_promoted_destination(config, state, lock_owner=lock_owner)
            return
        except LegacyDataMigrationError as exc:
            _write_state(config, state, status="manual_recovery_required", error=_clean_error(exc))
            raise MigrationRecoveryError("Promoted destination could not be verified; manual recovery is required") from exc
    if not prepared.exists():
        raise LegacyDataMigrationError("Prepared migration data is missing")
    destination_state = classify_destination_state(config)
    if destination_state not in {
        "absent",
        "empty",
        "recognized_interrupted_migration",
        "failed_migration",
        "stale_migration_lock",
        "active_migration",
    }:
        raise LegacyDataMigrationError(f"Cannot promote migration into destination state: {destination_state}")
    if config.data_root.exists():
        if any(config.data_root.iterdir()):
            raise LegacyDataMigrationError("Cannot promote migration into non-empty destination")
        config.data_root.rmdir()
    _write_promotion_identity(config, state, prepared)
    _write_state(config, state, status="promoting")
    try:
        prepared.rename(config.data_root)
    except OSError:
        if config.data_root.exists():
            raise
        promotion_tmp = config.data_root.with_name(f"{config.data_root.name}.promoting-{state.migration_id}.tmp")
        if promotion_tmp.exists():
            if _normalized(promotion_tmp).parent != _normalized(config.data_root.parent):
                raise MigrationContainmentError("Promotion temporary path escapes migration parent") from None
            shutil.rmtree(promotion_tmp)
        shutil.copytree(prepared, promotion_tmp)
        try:
            promotion_tmp.rename(config.data_root)
        except OSError:
            shutil.rmtree(promotion_tmp, ignore_errors=True)
            raise
    _finalize_promoted_destination(config, state, lock_owner=lock_owner)


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


LockClassification = Literal["active_local", "active_remote_or_unknown", "stale_local", "malformed"]


def _is_process_actively_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return f'"{pid}"' in result.stdout
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        raw = stat_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False
    except OSError:
        raw = ""
    if raw:
        marker = raw.rfind(")")
        remainder = raw[marker + 1 :].strip() if marker >= 0 else raw.strip()
        state = remainder.split(" ", 1)[0] if remainder else ""
        return state != "Z"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_lock_metadata(config: RuntimeConfig) -> dict[str, object]:
    lock_path = _safe_lock_path(config)
    if lock_path.is_symlink():
        raise MigrationLockError("Migration lock path is a symlink and cannot be trusted")
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationLockError(f"Migration lock is malformed: {lock_path}") from exc
    if not isinstance(raw, dict):
        raise MigrationLockError("Migration lock must be a JSON object")
    return cast(dict[str, object], raw)


def _classify_existing_lock(config: RuntimeConfig) -> LockClassification:
    raw = _read_lock_metadata(config)
    pid = raw.get("pid")
    hostname = raw.get("hostname")
    if not isinstance(pid, int) or not isinstance(hostname, str) or not hostname.strip():
        return "malformed"
    if hostname != socket.gethostname():
        return "active_remote_or_unknown"
    return "active_local" if _is_process_actively_running(pid) else "stale_local"


def _remove_stale_lock(config: RuntimeConfig) -> None:
    lock_path = _safe_lock_path(config)
    if lock_path.is_symlink():
        raise MigrationLockError("Refusing to remove symlinked migration lock")
    with suppress(FileNotFoundError):
        lock_path.unlink()


def _write_lock_metadata(fd: int) -> None:
    metadata = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at": _utc_now(),
        "owner_token": uuid.uuid4().hex,
    }
    with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
        json.dump(metadata, lock_file, sort_keys=True)
        lock_file.write("\n")
        lock_file.flush()
        os.fsync(lock_file.fileno())


def _acquire_migration_lock(config: RuntimeConfig) -> tuple[Path, str]:
    parent = _staging_parent(config)
    parent.mkdir(parents=True, exist_ok=True)
    legacy_lock = config.data_root / ".smart_organizer_migration.lock"
    if legacy_lock.exists():
        raise LegacyDataMigrationError("Legacy data migration is already in progress.")
    lock_path = _safe_lock_path(config)
    if lock_path.exists():
        classification = _classify_existing_lock(config)
        if classification == "stale_local":
            _remove_stale_lock(config)
        elif classification == "malformed":
            raise MigrationLockError(f"Migration lock is malformed and requires manual recovery: {lock_path}")
        elif classification == "active_local":
            raise MigrationLockError("Legacy data migration is already in progress on this computer.")
        else:
            raise MigrationLockError("Legacy data migration lock belongs to another host; manual recovery is required.")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise MigrationLockError(f"Legacy data migration is already in progress: {lock_path}") from exc
    _write_lock_metadata(fd)
    owner_token = _current_lock_owner_token(config)
    if owner_token is None:
        raise MigrationLockError("Migration lock owner token is missing")
    return lock_path, owner_token


def _run_state_machine(config: RuntimeConfig, state: MigrationState, *, lock_owner: str) -> None:
    try:
        if state.status == "failed":
            if state.staging_root.exists():
                safe_remove_migration_staging(config, state)
            state = _new_state(config)
            _write_state(config, state, status="preparing")
        elif state.status in {"preparing", "copying"}:
            prepared = safe_resolve_prepared_root(config, state)
            if prepared.exists():
                safe_remove_migration_staging(config, state, prepared)
        elif state.status in {"rollback_required", "manual_recovery_required"}:
            raise LegacyDataMigrationError("Previous migration requires manual rollback review before retry")

        if state.status in {"preparing", "copying"}:
            _copy_artifacts_to_staging(config, state)
        if state.status in {"copying", "verifying"}:
            _verify_prepared_data_with_config(config, state)
        if state.status in {"verifying", "promoting"}:
            _promote_prepared_data(config, state, lock_owner=lock_owner)
    except Exception as exc:
        with suppress(Exception):
            if state.status in TERMINAL_RECOVERY_STATES:
                _write_state(config, state, error=_clean_error(exc))
            else:
                _write_state(config, state, status="failed", error=_clean_error(exc))
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
    if status.destination_state == "valid_completed_migration":
        _validate_completed_marker(config)
        return status
    if status.destination_state == "valid_unrelated_installation":
        raise LegacyDataMigrationError(
            "Legacy source-adjacent data exists, but the runtime data directory contains an active database. "
            "Choose a different SMART_ORGANIZER_DATA_DIR or migrate manually."
        )
    if status.destination_state == "invalid_completed_marker":
        _validate_completed_marker(config)
    if status.destination_state in {
        "unknown_non_empty_destination",
        "partial_promoted_destination",
        "corrupted_destination_db",
        "directory_only_destination_without_db",
        "active_migration",
    }:
        raise LegacyDataMigrationError(
            f"Legacy source-adjacent data exists, but the runtime data directory already contains data "
            f"({status.destination_state}). Choose a different SMART_ORGANIZER_DATA_DIR or migrate manually."
        )

    lock_path, lock_owner = _acquire_migration_lock(config)
    try:
        states = _find_migration_states(config)
        active = next((state for state in states if state.status != "completed"), None)
        state = active or _new_state(config)
        if not state.state_path.exists():
            _write_state(config, state, status="preparing")
        _run_state_machine(config, state, lock_owner=lock_owner)
    finally:
        if _normalized(lock_path) == _safe_lock_path(config) and not lock_path.is_symlink():
            lock_path.unlink(missing_ok=True)
    return detect_legacy_data(config)
