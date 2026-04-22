from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from core import FileUtils

from storage_base import _log_context

logger = logging.getLogger(__name__)


class StorageRecoveryMixin:
    def _recover_moving_file(self: Any, file_id: int, file_info: dict[str, object]):
        if file_info.get("status") != "MOVING" or not file_info.get("moving_target_path"):
            return None

        moving_target = file_info["moving_target_path"]
        temp_path = file_info.get("temp_path")
        temp_exists = bool(temp_path and self._path_exists(temp_path))
        target_exists = self._path_exists(moving_target)
        existing_last_error = file_info.get("last_error")

        conn: sqlite3.Connection | None = None
        try:
            if target_exists and not temp_exists:
                logger.info("偵測到 Recovery: 檔案已搬移成功但 DB 未更新 (file_id=%s)", file_id)
                conn = self._get_connection()
                conn.execute(
                    """
                    UPDATE files SET final_path = ?, temp_path = NULL, moving_target_path = NULL, status = 'COMPLETED'
                    WHERE file_id = ?
                    """,
                    (moving_target, file_id),
                )
                conn.commit()
                return moving_target
            if temp_exists:
                if target_exists:
                    logger.warning(
                        "偵測到異常狀態: 來源與目標同時存在 (file_id=%s)，嘗試清理目標殘留後回退至 PROCESSED 供重新檢查",
                        file_id,
                    )
                    cleanup_failed = False
                    try:
                        self._remove_path(moving_target)
                        logger.warning("Recovery 已清理目標殘留 (file_id=%s): %s", file_id, moving_target)
                    except Exception:
                        cleanup_failed = True
                        logger.warning(
                            "Recovery 清理目標殘留失敗 (file_id=%s): %s",
                            file_id,
                            moving_target,
                            exc_info=True,
                        )
                else:
                    logger.info("偵測到 Recovery: 搬移中斷且目標不存在，回退狀態 (file_id=%s)", file_id)

                conn = self._get_connection()
                if target_exists and cleanup_failed:
                    diag = self._recovery_diag(f"目標殘留清理失敗（請人工處理）：{Path(str(moving_target)).name}")
                    merged = self._merge_last_error(existing_last_error, diag)
                    conn.execute(
                        "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ? WHERE file_id = ?",
                        (merged, file_id),
                    )
                else:
                    conn.execute(
                        "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL WHERE file_id = ?",
                        (file_id,),
                    )
                conn.commit()
            else:
                logger.warning("偵測到嚴重異常: 來源與目標皆不存在 (file_id=%s)，強制回退狀態", file_id)
                conn = self._get_connection()
                diag = self._recovery_diag("來源與目標皆不存在（可能檔案遺失或被移除），已回退 PROCESSED 供重試/修復")
                merged = self._merge_last_error(existing_last_error, diag)
                conn.execute(
                    "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ? WHERE file_id = ?",
                    (merged, file_id),
                )
                conn.commit()
            return None
        except Exception as e:
            logger.error("Recovery 執行失敗 (ID: %s): %s", file_id, e)
            return None
        finally:
            if conn:
                conn.close()

    def finalize_organization(self: Any, file_id: int, standard_date: str, main_topic: str, original_name: str):
        try:
            file_info = self.get_file_by_id(file_id)
            if not file_info:
                raise ValueError(f"找不到檔案 ID: {file_id}")

            if file_info.get("status") == "COMPLETED" and file_info.get("final_path"):
                if self._path_exists(file_info["final_path"]):
                    return file_info["final_path"]

            recovered_path = self._recover_moving_file(file_id, file_info)
            if recovered_path:
                return recovered_path

            file_info = self.get_file_by_id(file_id)

            normalized_date, year, month = FileUtils.get_date_directory_parts(standard_date)

            target_dir = self.repo_root / year / month
            if self._mem_files is None:
                target_dir.mkdir(parents=True, exist_ok=True)

            safe_name = file_info.get("safe_name") or FileUtils.sanitize_filename(
                Path(original_name or file_info.get("original_name") or "").name
            )
            final_name = FileUtils.sanitize_filename(f"{normalized_date}_{main_topic}_{safe_name}")

            if self._mem_files is not None:
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

            if not file_info["temp_path"] or not self._path_exists(file_info["temp_path"]):
                raise FileNotFoundError(f"找不到暫存檔案: {file_info.get('temp_path')}")

            temp_path = file_info["temp_path"]

            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE files SET status = 'MOVING', moving_target_path = ? WHERE file_id = ?",
                    (target_path, file_id),
                )
                conn.commit()

                try:
                    self._move_path(temp_path, target_path)
                except PermissionError as move_err:
                    logger.warning("搬移權限不足，改用 copy (file_id=%s): %s", file_id, move_err)
                    try:
                        self._copy_path(temp_path, target_path)
                    except Exception as copy_err:
                        logger.error("copy fallback 失敗", exc_info=True)
                        if self._path_exists(target_path):
                            try:
                                self._remove_path(target_path)
                                logger.warning("已清理 partial target (file_id=%s): %s", file_id, target_path)
                            except Exception:
                                logger.warning("清理 partial target 失敗（忽略）", exc_info=True)

                        msg = str(copy_err)
                        if len(msg) > 400:
                            msg = msg[:400] + "..."
                        conn.execute(
                            "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ? WHERE file_id = ?",
                            (msg, file_id),
                        )
                        conn.commit()
                        raise copy_err
                    try:
                        self._remove_path(temp_path)
                    except Exception:
                        pass
                except Exception as move_err:
                    if not self._path_exists(target_path):
                        msg = str(move_err)
                        if len(msg) > 400:
                            msg = msg[:400] + "..."
                        conn.execute(
                            "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ? WHERE file_id = ?",
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
        except Exception as e:
            logger.error("整理檔案失敗 (file_id=%s): %s", file_id, e)
            try:
                conn2 = self._get_connection()
                try:
                    msg = str(e)
                    if len(msg) > 400:
                        msg = msg[:400] + "..."
                    conn2.execute("UPDATE files SET last_error = ? WHERE file_id = ?", (msg, file_id))
                    conn2.commit()
                finally:
                    conn2.close()
            except Exception:
                logger.warning("寫入 last_error 失敗（忽略，不影響主流程）", exc_info=True)
            raise
