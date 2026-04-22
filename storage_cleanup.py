from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
        except Exception as e:
            logger.error("重新整理檔案位置失敗: %s", e)
            if conn:
                conn.rollback()
            return {"success": False, "error": str(e), "summary": summary}
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
        if len(hash_prefix) == 8 and hash_prefix in valid_hash_prefixes:
            return True

        return False

    def cleanup_orphaned_uploads(self: Any, preview_ttl_days: int = 7, dry_run: bool = True):
        if self._mem_files is not None:
            return []

        import re

        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT temp_path, final_path, preview_path, file_hash
                FROM files
                WHERE temp_path IS NOT NULL OR final_path IS NOT NULL OR preview_path IS NOT NULL
                """
            )
            valid_temp_paths: set[str] = set()
            valid_temp_names: set[str] = set()
            valid_preview_paths: set[str] = set()
            valid_hash_prefixes: set[str] = set()
            for temp_path, final_path, preview_path, file_hash in cursor.fetchall():
                if temp_path:
                    valid_temp_paths.add(temp_path)
                    valid_temp_names.add(Path(temp_path).name)
                if preview_path:
                    valid_preview_paths.add(preview_path)
                if file_hash:
                    valid_hash_prefixes.add(file_hash[:8].lower())
        except Exception as e:
            logger.error("清理暫存檔失敗(讀 DB): %s", e)
            return []
        finally:
            if conn:
                conn.close()

        now = time.time()
        ttl_sec = preview_ttl_days * 24 * 3600
        actions: list[dict[str, object]] = []

        temp_pattern = re.compile(r"^[a-f0-9]{8}_.+")

        for p in self.upload_dir.glob("*"):
            if p.is_file():
                p_str = str(p)
                try:
                    age_sec = now - p.stat().st_mtime
                except Exception:
                    age_sec = 0

                if age_sec > 300 and temp_pattern.match(p.name) and p_str not in valid_temp_paths:
                    try:
                        actions.append({"type": "temp", "path": p_str, "age_sec": int(age_sec)})
                        if not dry_run:
                            p.unlink()
                            logger.info("已清理孤立暫存檔: %s (年齡: %ss)", p_str, int(age_sec))
                    except Exception as e:
                        logger.warning("刪除暫存檔失敗 %s: %s", p_str, e)

        preview_dir = self.upload_dir / "previews"
        if preview_dir.exists():
            for pattern in ("*.png", "*.jpg", "*.jpeg"):
                for p in preview_dir.glob(pattern):
                    p_str = str(p)
                    try:
                        too_old = (now - p.stat().st_mtime) > ttl_sec
                    except OSError:
                        too_old = True

                    is_referenced = self._is_preview_referenced(
                        p_str,
                        valid_preview_paths,
                        valid_temp_names,
                        valid_hash_prefixes,
                    )
                    is_orphan = not is_referenced

                    if too_old and is_orphan:
                        try:
                            actions.append({"type": "preview", "path": p_str})
                            if not dry_run:
                                p.unlink()
                                logger.info("已清理孤立預覽圖: %s", p_str)
                        except Exception as e:
                            logger.warning("刪除預覽圖失敗 %s: %s", p_str, e)

        return actions
