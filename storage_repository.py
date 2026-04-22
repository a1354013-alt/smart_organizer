from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from core import FileUtils

from storage_base import MAX_UPLOAD_BYTES, _log_context

logger = logging.getLogger(__name__)


class StorageRepositoryMixin:
    def _normalize_uploaded_bytes(self, file_content: bytes | bytearray | memoryview) -> bytes:
        if isinstance(file_content, memoryview):
            return file_content.tobytes()
        if isinstance(file_content, bytearray):
            return bytes(file_content)
        if isinstance(file_content, bytes):
            return file_content
        return bytes(file_content)

    def _detect_extension(self, filename: str) -> str:
        return Path(filename or "").suffix.lower()

    def _validate_upload(self, uploaded_file_name: str, file_content: bytes | bytearray | memoryview) -> tuple[str, str, bytes]:
        original_name = Path(uploaded_file_name or "").name
        safe_name = FileUtils.sanitize_filename(original_name)
        ext = self._detect_extension(safe_name)
        payload = self._normalize_uploaded_bytes(file_content)

        if not safe_name.strip():
            raise ValueError("檔名不可為空")
        if ext not in FileUtils.ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError(f"不支援的檔案格式: {ext or 'unknown'}")
        if not payload:
            raise ValueError("檔案不可為空")
        if len(payload) > MAX_UPLOAD_BYTES:
            raise ValueError(f"檔案大小超過上傳硬限制 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")

        if ext == ".pdf" and not payload.startswith(b"%PDF-"):
            raise ValueError("PDF 檔案簽章不正確")
        if ext == ".png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG 檔案簽章不正確")
        if ext in {".jpg", ".jpeg"} and not payload.startswith(b"\xff\xd8\xff"):
            raise ValueError("JPEG 檔案簽章不正確")

        return original_name, safe_name, payload

    def _merge_main_topic_into_tags(self, main_topic: str, tags_with_confidence: Mapping[str, object] | None) -> dict[str, float]:
        merged: dict[str, float] = {}
        for tag_name, confidence in (tags_with_confidence or {}).items():
            if not tag_name:
                continue
            try:
                merged[str(tag_name)] = float(confidence)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                merged[str(tag_name)] = 0.0

        if main_topic:
            current_max = max(merged.values(), default=0.0)
            merged[main_topic] = max(merged.get(main_topic, 0.0), current_max, 1.0)

        return merged

    def _replace_file_tags(self, cursor: sqlite3.Cursor, file_id: int, tags_with_confidence: dict[str, float]) -> None:
        cursor.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
        for tag_name, confidence in tags_with_confidence.items():
            cursor.execute("INSERT OR IGNORE INTO tags (tag_name) VALUES (?)", (tag_name,))
            cursor.execute("SELECT tag_id FROM tags WHERE tag_name = ?", (tag_name,))
            tag_id = cursor.fetchone()[0]
            cursor.execute(
                "INSERT INTO file_tags (file_id, tag_id, confidence) VALUES (?, ?, ?)",
                (file_id, tag_id, confidence),
            )

    def path_exists(self: Any, path: str) -> bool:
        return self._path_exists(path)

    def _infer_file_type(self, filename: str, provided: str | None = None) -> str:
        name = str(filename or "")
        ext = os.path.splitext(name)[1].lower()
        if ext in {".jpg", ".jpeg", ".png"}:
            return "photo"
        if ext == ".pdf":
            return "document"
        if ext in {".mp4", ".mov", ".mkv"}:
            return "video"
        if provided in {"photo", "document", "video"}:
            return str(provided)
        return "document"

    def create_temp_file(self: Any, uploaded_file_name: str, file_content: bytes | bytearray | memoryview, file_hash: str, file_type: str):
        temp_path: str | Path | None = None
        part_path: Path | None = None
        conn: sqlite3.Connection | None = None
        try:
            original_name, safe_name, payload = self._validate_upload(uploaded_file_name, file_content)
            final_file_type = self._infer_file_type(original_name, file_type)

            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT file_id, status, final_path, temp_path FROM files WHERE file_hash = ?",
                (file_hash,),
            )
            row = cursor.fetchone()
            if row:
                return {"success": False, "reason": "DUPLICATE", "file_id": row[0], "status": row[1], "final_path": row[2]}

            unique_temp_name = f"{file_hash[:8]}_{safe_name}"
            if self._mem_files is not None:
                temp_path = f"mem://uploads/{unique_temp_name}"
                part_path = None
            else:
                temp_path = self.upload_dir / unique_temp_name
                part_path = self.upload_dir / f"{unique_temp_name}.{uuid.uuid4().hex}.part"

            if self._mem_files is not None:
                if temp_path not in self._mem_files:
                    self._mem_files[temp_path] = payload
            elif isinstance(temp_path, Path) and not temp_path.exists():
                try:
                    assert part_path is not None
                    with open(part_path, "wb") as f:
                        f.write(payload)
                    os.replace(part_path, temp_path)
                except PermissionError as e:
                    logger.warning("os.replace 失敗，改用直接寫入 temp_path: %s", e)
                    with open(temp_path, "wb") as f:
                        f.write(payload)
                    if part_path and part_path.exists():
                        try:
                            os.remove(part_path)
                        except Exception:
                            pass

            try:
                begin_err: sqlite3.OperationalError | None = None
                for attempt in range(10):
                    try:
                        cursor.execute("BEGIN IMMEDIATE")
                        begin_err = None
                        break
                    except sqlite3.OperationalError as oe:
                        begin_err = oe
                        if "locked" in str(oe).lower():
                            time.sleep(0.01 * (attempt + 1))
                            continue
                        raise
                if begin_err is not None:
                    raise begin_err

                cursor.execute(
                    "SELECT file_id, status, final_path, temp_path FROM files WHERE file_hash = ?",
                    (file_hash,),
                )
                row = cursor.fetchone()
                if row:
                    conn.rollback()
                    db_temp_path = row[3]
                    if temp_path and str(temp_path) != db_temp_path and self._path_exists(temp_path):
                        try:
                            self._remove_path(str(temp_path))
                        except Exception:
                            pass
                    return {"success": False, "reason": "DUPLICATE", "file_id": row[0], "status": row[1], "final_path": row[2]}

                cursor.execute(
                    """
                    INSERT INTO files (original_name, safe_name, temp_path, file_hash, file_type, status)
                    VALUES (?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (original_name, safe_name, str(temp_path), file_hash, final_file_type),
                )
                file_id = cursor.lastrowid
                conn.commit()
                logger.info(
                    "create_temp_file success%s",
                    _log_context(file_id=file_id, original_name=original_name, file_type=final_file_type, temp_path=str(temp_path)),
                )
                return {"success": True, "file_id": file_id}
            except sqlite3.IntegrityError:
                conn.rollback()
                cursor.execute(
                    "SELECT file_id, status, final_path, temp_path FROM files WHERE file_hash = ?",
                    (file_hash,),
                )
                row = cursor.fetchone()
                if row:
                    db_temp_path = row[3]
                    if temp_path and str(temp_path) != db_temp_path and self._path_exists(temp_path):
                        try:
                            self._remove_path(str(temp_path))
                        except Exception:
                            pass
                return {"success": False, "reason": "DUPLICATE", "file_id": row[0], "status": row[1], "final_path": row[2]}
        except Exception as e:
            logger.error(
                "建立暫存檔案失敗%s: %s",
                _log_context(original_name=uploaded_file_name, file_hash=str(file_hash)[:8]),
                e,
            )
            if part_path and part_path.exists():
                try:
                    os.remove(part_path)
                except Exception:
                    pass
            return {"success": False, "reason": "ERROR", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def get_file_path(self: Any, file_id: int) -> str | None:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT final_path, temp_path FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
            if row:
                return row[0] if row[0] else row[1]
            return None
        except Exception as e:
            logger.error("獲取檔案路徑失敗: %s", e)
            return None
        finally:
            if conn:
                conn.close()

    def get_file_by_id(self: Any, file_id: int) -> dict[str, object] | None:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error("獲取檔案資訊失敗: %s", e)
            return None
        finally:
            if conn:
                conn.close()

    def update_file_metadata(self: Any, file_id: int, metadata: dict[str, object]) -> None:
        conn: sqlite3.Connection | None = None
        main_topic = ""
        decision_source = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            normalized_date = FileUtils.normalize_standard_date(metadata.get("standard_date"))
            main_topic = str(metadata.get("main_topic", "") or "")
            preview_path = metadata.get("preview_path")
            tag_scores = self._merge_main_topic_into_tags(main_topic, metadata.get("tag_scores"))
            manual_override = metadata.get("manual_override")
            manual_override_val = None if manual_override is None else (1 if manual_override else 0)

            decision_source = metadata.get("decision_source")
            last_manual_topic = metadata.get("last_manual_topic")
            last_manual_reason = metadata.get("last_manual_reason")
            if manual_override_val == 1:
                decision_source = decision_source or "MANUAL_OVERRIDE"
                last_manual_topic = last_manual_topic or main_topic
                last_manual_reason = last_manual_reason or metadata.get("final_decision_reason")

            cursor.execute(
                """
                UPDATE files
                SET standard_date = ?,
                    main_topic = ?,
                    summary = ?,
                    preview_path = ?,
                    classification_reason = COALESCE(?, classification_reason),
                    final_decision_reason = COALESCE(?, final_decision_reason),
                    manual_override = COALESCE(?, manual_override),
                    decision_source = COALESCE(?, decision_source),
                    decision_updated_at = CASE WHEN ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE decision_updated_at END,
                    last_manual_topic = COALESCE(?, last_manual_topic),
                    last_manual_reason = COALESCE(?, last_manual_reason),
                    is_scanned = ?,
                    status = CASE
                        WHEN status = 'COMPLETED' THEN 'COMPLETED'
                        ELSE 'PROCESSED'
                    END
                WHERE file_id = ?
                """,
                (
                    normalized_date,
                    main_topic,
                    metadata.get("summary", ""),
                    preview_path,
                    metadata.get("classification_reason"),
                    metadata.get("final_decision_reason"),
                    manual_override_val,
                    decision_source,
                    decision_source,
                    last_manual_topic,
                    last_manual_reason,
                    1 if metadata.get("is_scanned") else 0,
                    file_id,
                ),
            )

            cursor.execute("SELECT content FROM file_content_fts WHERE rowid = ?", (file_id,))
            fts_row = cursor.fetchone()
            old_content = fts_row[0] if fts_row else ""

            cursor.execute("SELECT original_name FROM files WHERE file_id = ?", (file_id,))
            file_row = cursor.fetchone()
            original_name = file_row[0] if file_row else ""

            content = metadata.get("content", "") or old_content
            title = main_topic
            summary = metadata.get("summary", "")

            cursor.execute(
                """
                INSERT OR REPLACE INTO file_content_fts (rowid, original_filename, title, summary, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                (file_id, original_name, title, summary, content),
            )
            if tag_scores:
                self._replace_file_tags(cursor, file_id, tag_scores)
            conn.commit()
            cursor.execute("SELECT status FROM files WHERE file_id = ?", (file_id,))
            status_row = cursor.fetchone()
            current_status = status_row[0] if status_row else None
            logger.info(
                "update_file_metadata success%s",
                _log_context(
                    file_id=file_id,
                    status=current_status,
                    main_topic=main_topic,
                    decision_source=decision_source,
                    preview_path=preview_path,
                ),
            )
        except Exception as e:
            logger.error(
                "更新中繼資料失敗%s: %s",
                _log_context(file_id=file_id, main_topic=main_topic, decision_source=decision_source),
                e,
            )
            raise
        finally:
            if conn:
                conn.close()

    def add_tags_to_file(self: Any, file_id: int, tags_with_confidence: dict[str, float], main_topic: str | None = None) -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            merged_tags = self._merge_main_topic_into_tags(main_topic or "", tags_with_confidence)
            self._replace_file_tags(cursor, file_id, merged_tags)
            conn.commit()
        except Exception as e:
            logger.error("添加標籤失敗: %s", e)
            raise
        finally:
            if conn:
                conn.close()

    def get_all_records(self: Any):
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT f.*, GROUP_CONCAT(t.tag_name) as all_tags
                FROM files f
                LEFT JOIN file_tags ft ON f.file_id = ft.file_id
                LEFT JOIN tags t ON ft.tag_id = t.tag_id
                GROUP BY f.file_id
                ORDER BY f.created_at DESC
                """
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error("獲取紀錄失敗: %s", e)
            return []
        finally:
            if conn:
                conn.close()
