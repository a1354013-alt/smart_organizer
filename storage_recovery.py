from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import suppress
from pathlib import Path
from typing import Any

from core import FileUtils
from storage_base import _log_context

logger = logging.getLogger(__name__)


class StorageRecoveryMixin:
    def _require_file_info(self: Any, file_id: int, file_info: dict[str, object] | None) -> dict[str, object]:
        if file_info is None:
            raise FileNotFoundError(f"file record not found for file_id={file_id}")
        return file_info

    def _recover_moving_file(self: Any, file_id: int, file_info: dict[str, object]):
        if file_info.get("status") != "MOVING" or not file_info.get("moving_target_path"):
            return None

        moving_target = str(file_info["moving_target_path"])
        temp_path = file_info.get("temp_path")
        temp_exists = bool(temp_path and self._path_exists(temp_path))
        target_exists = self._path_exists(moving_target)
        existing_last_error = file_info.get("last_error")

        conn: sqlite3.Connection | None = None
        try:
            if target_exists and not temp_exists:
                logger.info("Recovery completed move using existing target%s", _log_context(file_id=file_id, target=moving_target))
                conn = self._get_connection()
                conn.execute(
                    """
                    UPDATE files
                    SET final_path = ?, temp_path = NULL, moving_target_path = NULL, status = 'COMPLETED', updated_at = datetime('now')
                    WHERE file_id = ?
                    """,
                    (moving_target, file_id),
                )
                conn.commit()
                return moving_target

            if temp_exists:
                cleanup_failed = False
                if target_exists:
                    logger.warning("Recovery found both temp and target; removing leftover target%s", _log_context(file_id=file_id, target=moving_target))
                    try:
                        self._remove_path(moving_target)
                    except Exception:
                        cleanup_failed = True
                        logger.warning("Recovery failed to remove leftover target%s", _log_context(file_id=file_id, target=moving_target), exc_info=True)
                else:
                    logger.info("Recovery reset MOVING file back to PROCESSED%s", _log_context(file_id=file_id))

                conn = self._get_connection()
                if target_exists and cleanup_failed:
                    diag = self._recovery_diag(
                        f"target cleanup failed (清理失敗); remove manually: {Path(moving_target).name}"
                    )
                    merged = self._merge_last_error(existing_last_error, diag)
                    conn.execute(
                        "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ?, updated_at = datetime('now') WHERE file_id = ?",
                        (merged, file_id),
                    )
                else:
                    conn.execute(
                        "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, updated_at = datetime('now') WHERE file_id = ?",
                        (file_id,),
                    )
                conn.commit()
                return None

            logger.warning("Recovery found MOVING record without source or target%s", _log_context(file_id=file_id))
            conn = self._get_connection()
            diag = self._recovery_diag(
                "source and target are both missing; status reset to PROCESSED for retry"
            )
            merged = self._merge_last_error(existing_last_error, diag)
            conn.execute(
                "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ?, updated_at = datetime('now') WHERE file_id = ?",
                (merged, file_id),
            )
            conn.commit()
            return None
        except Exception as exc:
            logger.error("Recovery failed%s: %s", _log_context(file_id=file_id), exc)
            return None
        finally:
            if conn:
                conn.close()

    def finalize_organization(self: Any, file_id: int, standard_date: str, main_topic: str, original_name: str):
        try:
            file_info = self._require_file_info(file_id, self.get_file_by_id(file_id))

            if (
                file_info.get("status") == "COMPLETED"
                and file_info.get("final_path")
                and self._path_exists(file_info["final_path"])
            ):
                return file_info["final_path"]

            recovered_path = self._recover_moving_file(file_id, file_info)
            if recovered_path:
                return recovered_path

            file_info = self._require_file_info(file_id, self.get_file_by_id(file_id))
            normalized_date, year, month = FileUtils.get_date_directory_parts(standard_date)

            target_dir = self.repo_root / year / month
            if self._mem_files is None:
                target_dir.mkdir(parents=True, exist_ok=True)

            safe_name = file_info.get("safe_name") or FileUtils.sanitize_filename(
                Path(original_name or file_info.get("original_name") or "").name
            )
            final_name = FileUtils.sanitize_filename(f"{normalized_date}_{main_topic}_{safe_name}")

            if self._mem_files is not None:
                with self._mem_files_lock:
                    base_target = f"mem://repo/{year}/{month}/{final_name}"
                    if base_target not in self._mem_files:
                        target_path = base_target
                    else:
                        stem, ext = os.path.splitext(final_name)
                        counter = 1
                        while True:
                            candidate_name = f"{stem}_{counter}{ext}"
                            candidate_path = f"mem://repo/{year}/{month}/{candidate_name}"
                            if candidate_path not in self._mem_files:
                                target_path = candidate_path
                                final_name = candidate_name
                                break
                            counter += 1
            else:
                target_path = str(FileUtils.get_unique_path(target_dir / final_name))

            temp_path = file_info.get("temp_path")
            if not temp_path or not self._path_exists(temp_path):
                raise FileNotFoundError(f"temporary file missing: {temp_path}")

            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE files SET status = 'MOVING', moving_target_path = ?, updated_at = datetime('now') WHERE file_id = ?",
                    (target_path, file_id),
                )
                conn.commit()

                try:
                    self._move_path(str(temp_path), target_path)
                except PermissionError:
                    logger.warning("Move failed; using copy fallback%s", _log_context(file_id=file_id, target=target_path))
                    try:
                        self._copy_path(str(temp_path), target_path)
                    except Exception as copy_err:
                        logger.error("Copy fallback failed%s", _log_context(file_id=file_id, target=target_path), exc_info=True)
                        if self._path_exists(target_path):
                            try:
                                self._remove_path(target_path)
                            except Exception:
                                logger.warning("Failed to remove partial target%s", _log_context(file_id=file_id, target=target_path), exc_info=True)

                        msg = str(copy_err)
                        if len(msg) > 400:
                            msg = msg[:400] + "..."
                        conn.execute(
                            "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ?, updated_at = datetime('now') WHERE file_id = ?",
                            (msg, file_id),
                        )
                        conn.commit()
                        raise copy_err
                    with suppress(Exception):
                        self._remove_path(str(temp_path))
                except Exception as move_err:
                    if not self._path_exists(target_path):
                        msg = str(move_err)
                        if len(msg) > 400:
                            msg = msg[:400] + "..."
                        conn.execute(
                            "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ?, updated_at = datetime('now') WHERE file_id = ?",
                            (msg, file_id),
                        )
                        conn.commit()
                    raise move_err

                conn.execute(
                    """
                    UPDATE files
                    SET final_name = ?,
                        final_path = ?,
                        temp_path = NULL,
                        moving_target_path = NULL,
                        last_error = NULL,
                        updated_at = datetime('now'),
                        status = 'COMPLETED'
                    WHERE file_id = ?
                    """,
                    (final_name, target_path, file_id),
                )
                conn.commit()
                logger.info(
                    "finalize_organization success%s",
                    _log_context(file_id=file_id, status="COMPLETED", temp_path=temp_path, final_path=target_path),
                )
                return target_path
            finally:
                conn.close()
        except Exception as exc:
            logger.error("finalize_organization failed%s: %s", _log_context(file_id=file_id), exc)
            try:
                conn2 = self._get_connection()
                try:
                    msg = str(exc)
                    if len(msg) > 400:
                        msg = msg[:400] + "..."
                    conn2.execute("UPDATE files SET last_error = ?, updated_at = datetime('now') WHERE file_id = ?", (msg, file_id))
                    conn2.commit()
                finally:
                    conn2.close()
            except Exception:
                logger.warning("Failed to persist last_error%s", _log_context(file_id=file_id), exc_info=True)
            raise
