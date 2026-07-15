from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, TypedDict, cast

from storage_base import utc_now_iso

logger = logging.getLogger(__name__)

UNFINISHED_STATUSES = {"PENDING", "PROCESSED", "ERROR", "BROKEN"}
RESUMABLE_STATUSES = {"PENDING", "PROCESSED", "ERROR"}
STALE_UNFINISHED_AGE_SECONDS = 7 * 24 * 3600


class LifecycleError(RuntimeError):
    pass


class RecordNotFoundError(LifecycleError):
    pass


class InvalidLifecycleTransitionError(LifecycleError):
    pass


class MissingTemporaryFileError(LifecycleError):
    pass


class UnsafeLifecyclePathError(LifecycleError):
    pass


class UnfinishedRecord(TypedDict, total=False):
    file_id: int
    original_name: str | None
    status: str
    created_at: str | None
    updated_at: str | None
    temp_path: str | None
    temp_exists: bool
    temp_missing: bool
    last_error: str | None
    available_actions: list[str]


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


class StorageLifecycleMixin:
    def is_unfinished_status(self: Any, status: object) -> bool:
        return str(status or "").upper() in UNFINISHED_STATUSES

    def _is_allowed_upload_path(self: Any, path_value: object) -> bool:
        raw = str(path_value or "").strip()
        if not raw:
            return False
        if self._mem_files is not None:
            return self._is_mem_path(raw)
        try:
            candidate = Path(raw).expanduser().resolve(strict=False)
            upload_root = Path(self.upload_dir).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return False
        return _is_relative_to(candidate, upload_root)

    def _validated_temp_path(self: Any, record: dict[str, object]) -> str:
        temp_path = str(record.get("temp_path") or "").strip()
        if not temp_path or not self._is_allowed_upload_path(temp_path):
            raise UnsafeLifecyclePathError("temporary file path is outside the upload directory")
        if not self._path_exists(temp_path):
            self.mark_unfinished_temp_missing(int(str(record["file_id"])), temp_path)
            raise MissingTemporaryFileError("temporary file is missing; discard the unfinished record or upload again")
        return temp_path

    def available_unfinished_actions(self: Any, record: dict[str, object]) -> list[str]:
        status = str(record.get("status") or "").upper()
        if status not in UNFINISHED_STATUSES:
            return []
        temp_path = record.get("temp_path")
        temp_ok = bool(temp_path and self._is_allowed_upload_path(temp_path) and self._path_exists(temp_path))
        actions: list[str] = []
        if status in RESUMABLE_STATUSES and temp_ok:
            actions.extend(["resume", "reanalyze"])
        actions.append("discard")
        return actions

    def get_unfinished_records(self: Any, *, limit: int = 100) -> list[UnfinishedRecord]:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in UNFINISHED_STATUSES)
            cursor.execute(
                f"""
                SELECT file_id, original_name, status, created_at, updated_at, temp_path, last_error
                FROM files
                WHERE status IN ({placeholders})
                ORDER BY updated_at DESC, created_at DESC, file_id DESC
                LIMIT ?
                """,
                (*sorted(UNFINISHED_STATUSES), int(limit)),
            )
            records: list[UnfinishedRecord] = []
            for row in cursor.fetchall():
                raw = dict(row)
                temp_path = raw.get("temp_path")
                temp_exists = bool(temp_path and self._is_allowed_upload_path(temp_path) and self._path_exists(temp_path))
                raw["temp_exists"] = temp_exists
                raw["temp_missing"] = bool(temp_path and not temp_exists)
                raw["available_actions"] = self.available_unfinished_actions(raw)
                records.append(cast(UnfinishedRecord, raw))
            return records
        except sqlite3.Error as exc:
            logger.error("get_unfinished_records failed: %s", exc)
            raise
        finally:
            if conn:
                conn.close()

    def prepare_unfinished_record_for_analysis(self: Any, file_id: int) -> tuple[dict[str, object], str]:
        record = self.get_file_by_id(int(file_id))
        if record is None:
            raise RecordNotFoundError("unfinished record not found")
        status = str(record.get("status") or "").upper()
        if status not in RESUMABLE_STATUSES:
            raise InvalidLifecycleTransitionError(f"record status {status or 'UNKNOWN'} cannot be resumed")
        temp_path = self._validated_temp_path(record)
        return record, temp_path

    def mark_unfinished_temp_missing(self: Any, file_id: int, temp_path: str | None = None) -> None:
        message = "temporary file is missing"
        if temp_path:
            message = f"{message}: {Path(temp_path).name}"
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            conn.execute(
                """
                UPDATE files
                SET status = 'BROKEN', last_error = ?, updated_at = ?
                WHERE file_id = ? AND status != 'COMPLETED'
                """,
                (message, utc_now_iso(), int(file_id)),
            )
            conn.commit()
        except sqlite3.Error:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def mark_unfinished_error(self: Any, file_id: int, message: str) -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            conn.execute(
                """
                UPDATE files
                SET status = 'ERROR', last_error = ?, updated_at = ?
                WHERE file_id = ? AND status != 'COMPLETED'
                """,
                (message[:400], utc_now_iso(), int(file_id)),
            )
            conn.commit()
        except sqlite3.Error:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def discard_unfinished_record(self: Any, file_id: int) -> dict[str, object]:
        record = self.get_file_by_id(int(file_id))
        if record is None:
            raise RecordNotFoundError("unfinished record not found")
        status = str(record.get("status") or "").upper()
        if status not in UNFINISHED_STATUSES:
            raise InvalidLifecycleTransitionError(f"record status {status or 'UNKNOWN'} cannot be discarded")

        paths_to_remove: list[str] = []
        for key, checker in (("temp_path", self._is_allowed_upload_path), ("preview_path", self._is_allowed_preview_path)):
            path_value = record.get(key)
            if not path_value:
                continue
            path_str = str(path_value)
            if not checker(path_str):
                raise UnsafeLifecyclePathError(f"{key} is outside approved runtime directories")
            paths_to_remove.append(path_str)

        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            cursor.execute("DELETE FROM file_tags WHERE file_id = ?", (int(file_id),))
            cursor.execute("DELETE FROM file_content_fts WHERE rowid = ?", (int(file_id),))
            cursor.execute("DELETE FROM files WHERE file_id = ? AND status != 'COMPLETED'", (int(file_id),))
            if cursor.rowcount != 1:
                raise InvalidLifecycleTransitionError("unfinished record was not removed")
            conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

        cleanup_errors: list[str] = []
        removed_paths: list[str] = []
        for path_str in paths_to_remove:
            if not self._path_exists(path_str):
                continue
            try:
                self._remove_path(path_str)
                removed_paths.append(path_str)
            except OSError as exc:
                cleanup_errors.append(f"{Path(path_str).name}: {exc}")
                logger.warning("discard cleanup failed for %s: %s", path_str, exc)

        return {
            "success": not cleanup_errors,
            "file_id": int(file_id),
            "removed_paths": removed_paths,
            "cleanup_errors": cleanup_errors,
        }
