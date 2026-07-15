from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from storage_lifecycle import STALE_UNFINISHED_AGE_SECONDS, UNFINISHED_STATUSES

logger = logging.getLogger(__name__)

CURRENT_TEMP_NAME_PREFIXES = ("preview_",)


class StorageCleanupMixin:
    def refresh_file_locations(self: Any, fix_moving: bool = True):
        conn: sqlite3.Connection | None = None
        summary = {"checked": 0, "recovered": 0, "missing": 0, "broken": 0}
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT file_id, status, temp_path, final_path, moving_target_path FROM files")
            rows = cursor.fetchall()

            for row in rows:
                summary["checked"] += 1
                info = dict(row)
                file_id = info["file_id"]
                status = info.get("status")
                temp_path = info.get("temp_path")
                final_path = info.get("final_path")
                moving_target = info.get("moving_target_path")

                if fix_moving and status == "MOVING" and moving_target:
                    recovered = self._recover_moving_file(file_id, info)
                    if recovered:
                        summary["recovered"] += 1
                        continue

                if status == "COMPLETED" and final_path and not self._path_exists(final_path):
                    cursor.execute("UPDATE files SET status = 'MISSING' WHERE file_id = ?", (file_id,))
                    summary["missing"] += 1
                    continue

                if status in {"PENDING", "PROCESSED"}:
                    temp_exists = bool(temp_path and self._path_exists(temp_path))
                    final_exists = bool(final_path and self._path_exists(final_path))
                    if not temp_exists and not final_exists:
                        cursor.execute("UPDATE files SET status = 'BROKEN' WHERE file_id = ?", (file_id,))
                        summary["broken"] += 1
                        continue

            conn.commit()
            return {"success": True, "summary": summary}
        except Exception as exc:
            logger.error("Failed to refresh file locations: %s", exc)
            if conn:
                conn.rollback()
            return {"success": False, "error": str(exc), "summary": summary}
        finally:
            if conn:
                conn.close()

    def _is_preview_referenced(
        self: Any,
        preview_path: str,
        valid_preview_paths: set[str],
        valid_temp_names: set[str],
        valid_hash_prefixes: set[str],
    ) -> bool:
        if preview_path in valid_preview_paths:
            return True

        preview_name = Path(preview_path).name
        source_name = preview_name[len("preview_") :] if preview_name.startswith("preview_") else preview_name
        source_basename = Path(source_name).stem

        if source_basename in valid_temp_names:
            return True

        hash_prefix = source_basename.split("_", 1)[0].lower()
        return len(hash_prefix) == 8 and hash_prefix in valid_hash_prefixes

    def _record_cleanup_action(
        self: Any,
        actions: list[dict[str, object]],
        *,
        action_type: str,
        path: Path,
        dry_run: bool,
        age_sec: int | None = None,
        error: Exception | None = None,
    ) -> None:
        entry: dict[str, object] = {
            "type": action_type,
            "path": str(path),
            "status": "planned" if dry_run else "deleted",
        }
        if age_sec is not None:
            entry["age_sec"] = age_sec
        if error is not None:
            entry["status"] = "error"
            entry["error"] = f"{type(error).__name__}: {error}"
        actions.append(entry)

    def cleanup_orphaned_uploads(
        self: Any,
        preview_ttl_days: int = 7,
        dry_run: bool = True,
        stale_unfinished_age_seconds: int = STALE_UNFINISHED_AGE_SECONDS,
    ):
        if self._mem_files is not None:
            return []

        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT file_id, status, temp_path, final_path, preview_path, file_hash
                FROM files
                WHERE temp_path IS NOT NULL OR final_path IS NOT NULL OR preview_path IS NOT NULL
                """
            )
            valid_temp_paths: set[str] = set()
            valid_temp_names: set[str] = set()
            valid_preview_paths: set[str] = set()
            valid_hash_prefixes: set[str] = set()
            db_temp_status: dict[str, tuple[int, str]] = {}
            missing_unfinished: list[tuple[int, str, str]] = []
            for file_id, status, temp_path, _final_path, preview_path, file_hash in cursor.fetchall():
                if temp_path:
                    normalized_temp = self._normalize_preview_path(temp_path) if str(temp_path).endswith((".png", ".jpg", ".jpeg")) else str(temp_path)
                    valid_temp_paths.add(str(normalized_temp or temp_path))
                    valid_temp_names.add(Path(temp_path).name)
                    db_temp_status[str(normalized_temp or temp_path)] = (int(file_id), str(status or ""))
                    if str(status or "").upper() in UNFINISHED_STATUSES and not self._path_exists(str(temp_path)):
                        missing_unfinished.append((int(file_id), str(status or ""), str(temp_path)))
                if preview_path:
                    normalized_preview = self._normalize_preview_path(preview_path)
                    if normalized_preview:
                        valid_preview_paths.add(normalized_preview)
                if file_hash:
                    valid_hash_prefixes.add(file_hash[:8].lower())
        except Exception as exc:
            logger.error("Failed to load cleanup metadata: %s", exc)
            return []
        finally:
            if conn:
                conn.close()

        now = time.time()
        ttl_sec = preview_ttl_days * 24 * 3600
        actions: list[dict[str, object]] = []
        if dry_run:
            for file_id, status, temp_path in missing_unfinished:
                actions.append(
                    {
                        "type": "unfinished",
                        "file_id": file_id,
                        "path": temp_path,
                        "status": "missing_temp",
                        "reason": f"database-backed unfinished record ({status}) has no temporary file",
                    }
                )
        for temp_file in self.upload_dir.glob("*"):
            if not temp_file.is_file():
                continue
            temp_path = str(temp_file)
            try:
                age_sec = now - temp_file.stat().st_mtime
            except OSError:
                age_sec = 0

            within_uploads = self._normalize_preview_path(temp_path)
            is_current_temp_name = (
                len(temp_file.name.split("_", 2)) >= 3
                and len(temp_file.name.split("_", 2)[0]) == 64
                and len(temp_file.name.split("_", 2)[1]) == 32
            )
            is_legacy_temp_name = (
                "_" in temp_file.name
                and len(temp_file.name.split("_", 1)[0]) == 8
            )
            if temp_path in valid_temp_paths:
                file_id, db_status = db_temp_status.get(temp_path, (0, ""))
                if dry_run and str(db_status).upper() in UNFINISHED_STATUSES:
                    actions.append(
                        {
                            "type": "unfinished",
                            "file_id": file_id,
                            "path": temp_path,
                            "status": "stale" if age_sec > stale_unfinished_age_seconds else "active",
                            "reason": "database-backed unfinished record requires explicit discard",
                            "age_sec": int(age_sec),
                        }
                    )
                continue

            if (
                age_sec <= 300
                or within_uploads is None
                or temp_file.name.startswith(CURRENT_TEMP_NAME_PREFIXES)
                or not (is_current_temp_name or is_legacy_temp_name)
            ):
                continue

            if dry_run:
                self._record_cleanup_action(
                    actions,
                    action_type="temp",
                    path=temp_file,
                    dry_run=True,
                    age_sec=int(age_sec),
                )
                continue

            try:
                temp_file.unlink()
                self._record_cleanup_action(
                    actions,
                    action_type="temp",
                    path=temp_file,
                    dry_run=False,
                    age_sec=int(age_sec),
                )
                logger.info("Removed orphaned temp upload: %s", temp_path)
            except Exception as exc:
                self._record_cleanup_action(
                    actions,
                    action_type="temp",
                    path=temp_file,
                    dry_run=False,
                    age_sec=int(age_sec),
                    error=exc,
                )
                logger.warning("Failed to remove orphaned temp upload %s: %s", temp_path, exc)

        preview_dir = self.upload_dir / "previews"
        if preview_dir.exists():
            for pattern in ("*.png", "*.jpg", "*.jpeg"):
                for preview_file in preview_dir.glob(pattern):
                    preview_path = self._normalize_preview_path(preview_file)
                    if preview_path is None:
                        continue
                    try:
                        too_old = (now - preview_file.stat().st_mtime) > ttl_sec
                    except OSError:
                        too_old = True

                    if not too_old:
                        continue

                    if self._is_preview_referenced(
                        preview_path,
                        valid_preview_paths,
                        valid_temp_names,
                        valid_hash_prefixes,
                    ):
                        continue

                    if dry_run:
                        self._record_cleanup_action(
                            actions,
                            action_type="preview",
                            path=preview_file,
                            dry_run=True,
                        )
                        continue

                    try:
                        preview_file.unlink()
                        self._record_cleanup_action(
                            actions,
                            action_type="preview",
                            path=preview_file,
                            dry_run=False,
                        )
                        logger.info("Removed orphaned preview: %s", preview_path)
                    except Exception as exc:
                        self._record_cleanup_action(
                            actions,
                            action_type="preview",
                            path=preview_file,
                            dry_run=False,
                            error=exc,
                        )
                        logger.warning("Failed to remove orphaned preview %s: %s", preview_path, exc)

        return actions
