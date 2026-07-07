from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, TypedDict

from core import FileUtils
from storage_base import MAX_UPLOAD_BYTES, _log_context, utc_now_iso
from supported_formats import SUPPORTED_VIDEO_SUFFIXES

logger = logging.getLogger(__name__)


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


class CreateTempFileResult(TypedDict, total=False):
    success: bool
    reason: str
    message: str
    file_id: int
    status: str
    final_path: str | None


class StorageRepositoryMixin:
    def _escape_like(self, value: str) -> str:
        return (value or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

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
            raise ValueError("Filename is required")
        if ext not in FileUtils.ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError(f"Unsupported upload extension: {ext or 'unknown'}")
        if not payload:
            raise ValueError("Uploaded file is empty")
        if len(payload) > MAX_UPLOAD_BYTES:
            raise ValueError(f"File exceeds upload limit of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

        if ext == ".pdf" and not payload.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF signature")
        if ext == ".png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Invalid PNG signature")
        if ext in {".jpg", ".jpeg"} and not payload.startswith(b"\xff\xd8\xff"):
            raise ValueError("Invalid JPEG signature")

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
        if ext in SUPPORTED_VIDEO_SUFFIXES:
            return "video"
        if provided in {"photo", "document", "video"}:
            return str(provided)
        return "document"

    def _build_unique_temp_name(self, file_hash: str, safe_name: str) -> str:
        normalized_hash = (str(file_hash or "").strip().lower() or uuid.uuid4().hex)
        unique_suffix = uuid.uuid4().hex
        return f"{normalized_hash}_{unique_suffix}_{Path(safe_name).name}"

    def _resolve_preview_path_for_update(
        self,
        cursor: sqlite3.Cursor,
        file_id: int,
        requested_preview_path: object,
    ) -> str | None:
        normalized_preview = str(requested_preview_path).strip() if requested_preview_path not in (None, "") else ""
        if normalized_preview:
            return normalized_preview if self._is_allowed_preview_path(normalized_preview) else None

        cursor.execute("SELECT preview_path FROM files WHERE file_id = ?", (int(file_id),))
        existing_row = cursor.fetchone()
        existing_preview = str(existing_row[0]).strip() if existing_row and existing_row[0] else ""
        if existing_preview and self._is_allowed_preview_path(existing_preview) and self.path_exists(existing_preview):
            return existing_preview
        return None

    def _allowed_preview_roots(self: Any) -> tuple[Path, ...]:
        if self._mem_files is not None:
            return ()
        roots = (self.upload_dir, self.repo_root, self.repo_root / "previews")
        resolved: list[Path] = []
        for root in roots:
            try:
                candidate = Path(root).expanduser().resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if candidate not in resolved:
                resolved.append(candidate)
        return tuple(resolved)

    def _is_allowed_preview_path(self: Any, preview_path: object) -> bool:
        normalized = str(preview_path or "").strip()
        if not normalized:
            return False
        if self._mem_files is not None:
            return self._is_mem_path(normalized)
        try:
            candidate = Path(normalized).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        return any(_is_relative_to(candidate, root) for root in self._allowed_preview_roots())

    def create_temp_file(
        self: Any,
        uploaded_file_name: str,
        file_content: bytes | bytearray | memoryview,
        file_hash: str,
        file_type: str,
    ) -> CreateTempFileResult:
        temp_path: str | Path | None = None
        part_path: Path | None = None
        conn: sqlite3.Connection | None = None
        temp_created = False
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
                return {
                    "success": False,
                    "reason": "DUPLICATE",
                    "file_id": int(row[0]),
                    "status": str(row[1] or ""),
                    "final_path": str(row[2]) if row[2] else None,
                }

            unique_temp_name = self._build_unique_temp_name(file_hash, safe_name)
            if self._mem_files is not None:
                temp_path = f"mem://uploads/{unique_temp_name}"
                part_path = None
            else:
                temp_path = self.upload_dir / unique_temp_name
                part_path = self.upload_dir / f"{unique_temp_name}.{uuid.uuid4().hex}.part"

            if self._mem_files is not None:
                with self._mem_files_lock:
                    if temp_path not in self._mem_files:
                        self._mem_files[temp_path] = payload
                        temp_created = True
            elif isinstance(temp_path, Path) and not temp_path.exists():
                try:
                    assert part_path is not None
                    with open(part_path, "wb") as file_obj:
                        file_obj.write(payload)
                    os.replace(part_path, temp_path)
                    temp_created = True
                except PermissionError as exc:
                    logger.warning("os.replace failed, falling back to direct write: %s", exc)
                    with open(temp_path, "wb") as file_obj:
                        file_obj.write(payload)
                    temp_created = True
                    if part_path and part_path.exists():
                        with suppress(Exception):
                            os.remove(part_path)

            try:
                begin_err: sqlite3.OperationalError | None = None
                for attempt in range(10):
                    try:
                        cursor.execute("BEGIN IMMEDIATE")
                        begin_err = None
                        break
                    except sqlite3.OperationalError as exc:
                        begin_err = exc
                        if "locked" in str(exc).lower():
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
                        with suppress(Exception):
                            self._remove_path(str(temp_path))
                    return {
                        "success": False,
                        "reason": "DUPLICATE",
                        "file_id": int(row[0]),
                        "status": str(row[1] or ""),
                        "final_path": str(row[2]) if row[2] else None,
                    }

                cursor.execute(
                    """
                    INSERT INTO files (original_name, safe_name, temp_path, file_hash, file_type, status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
                    """,
                    (original_name, safe_name, str(temp_path), file_hash, final_file_type, utc_now_iso()),
                )
                file_id = int(cursor.lastrowid or 0)
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
                        with suppress(Exception):
                            self._remove_path(str(temp_path))
                    return {
                        "success": False,
                        "reason": "DUPLICATE",
                        "file_id": int(row[0]),
                        "status": str(row[1] or ""),
                        "final_path": str(row[2]) if row[2] else None,
                    }
                if temp_created and temp_path and self._path_exists(temp_path):
                    with suppress(Exception):
                        self._remove_path(str(temp_path))
                return {
                    "success": False,
                    "reason": "ERROR",
                    "message": "Database integrity error occurred, but no duplicate file record was found.",
                }
        except (ValueError, OSError, sqlite3.Error) as exc:
            logger.error(
                "create_temp_file failed%s: %s",
                _log_context(original_name=uploaded_file_name, file_hash=str(file_hash)[:8]),
                exc,
            )
            if part_path and part_path.exists():
                with suppress(Exception):
                    os.remove(part_path)
            if temp_created and temp_path and self._path_exists(temp_path):
                with suppress(Exception):
                    self._remove_path(str(temp_path))
            return {"success": False, "reason": "ERROR", "message": str(exc)}
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
        except sqlite3.Error as exc:
            logger.error("get_file_path failed: %s", exc)
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
        except sqlite3.Error as exc:
            logger.error("get_file_by_id failed: %s", exc)
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
            self_file_id = int(file_id)
            preview_path = self._resolve_preview_path_for_update(cursor, self_file_id, metadata.get("preview_path"))
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

            decision_updated_at = utc_now_iso() if decision_source is not None else None

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
                    decision_updated_at = CASE WHEN ? IS NOT NULL THEN ? ELSE decision_updated_at END,
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
                    decision_updated_at,
                    last_manual_topic,
                    last_manual_reason,
                    1 if metadata.get("is_scanned") else 0,
                    self_file_id,
                ),
            )

            cursor.execute("SELECT content FROM file_content_fts WHERE rowid = ?", (self_file_id,))
            fts_row = cursor.fetchone()
            old_content = fts_row[0] if fts_row else ""

            cursor.execute("SELECT original_name FROM files WHERE file_id = ?", (self_file_id,))
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
                (self_file_id, original_name, title, summary, content),
            )
            if tag_scores:
                self._replace_file_tags(cursor, self_file_id, tag_scores)
            conn.commit()
            cursor.execute("SELECT status FROM files WHERE file_id = ?", (self_file_id,))
            status_row = cursor.fetchone()
            current_status = status_row[0] if status_row else None
            logger.info(
                "update_file_metadata success%s",
                _log_context(
                    file_id=self_file_id,
                    status=current_status,
                    main_topic=main_topic,
                    decision_source=decision_source,
                    preview_path=preview_path,
                ),
            )
        except sqlite3.Error as exc:
            logger.error(
                "update_file_metadata failed%s: %s",
                _log_context(file_id=file_id, main_topic=main_topic, decision_source=decision_source),
                exc,
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
        except sqlite3.Error as exc:
            logger.error("add_tags_to_file failed: %s", exc)
            raise
        finally:
            if conn:
                conn.close()

    def get_all_records(self: Any) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        page_size = 500
        offset = 0
        while True:
            page = self.get_records_page(limit=page_size, offset=offset)
            items = list(page.get("items") or [])
            records.extend(items)
            total = int(page.get("total") or 0)
            if not items or len(records) >= total:
                return records
            offset += page_size

    def get_recent_records(self: Any, *, limit: int = 500) -> list[dict[str, object]]:
        return self.get_records_page(limit=limit, offset=0)["items"]

    def get_record_filter_values(self: Any) -> dict[str, list[str]]:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            values: dict[str, list[str]] = {}
            for field in ("status", "main_topic", "file_type"):
                cursor.execute(
                    f"SELECT DISTINCT COALESCE({field}, '') FROM files WHERE COALESCE({field}, '') <> '' ORDER BY {field}"
                )
                values[field] = [str(row[0]) for row in cursor.fetchall() if row and row[0]]
            return values
        except sqlite3.Error as exc:
            logger.error("get_record_filter_values failed: %s", exc)
            return {"status": [], "main_topic": [], "file_type": []}
        finally:
            if conn:
                conn.close()

    def get_records_page(
        self: Any,
        *,
        limit: int = 25,
        offset: int = 0,
        status: str | None = None,
        main_topic: str | None = None,
        file_type: str | None = None,
        search: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, object]:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            where_parts: list[str] = []
            params: list[object] = []

            if status:
                where_parts.append("f.status = ?")
                params.append(status)
            if main_topic:
                where_parts.append("f.main_topic = ?")
                params.append(main_topic)
            if file_type:
                where_parts.append("f.file_type = ?")
                params.append(file_type)
            if search:
                like = f"%{self._escape_like(search.strip())}%"
                where_parts.append(
                    "("
                    "f.original_name LIKE ? ESCAPE '\\' "
                    "OR COALESCE(f.main_topic, '') LIKE ? ESCAPE '\\' "
                    "OR COALESCE(f.summary, '') LIKE ? ESCAPE '\\' "
                    "OR EXISTS ("
                    "SELECT 1 "
                    "FROM file_tags sft "
                    "JOIN tags st ON sft.tag_id = st.tag_id "
                    "WHERE sft.file_id = f.file_id "
                    "AND COALESCE(st.tag_name, '') LIKE ? ESCAPE '\\'"
                    ")"
                    ")"
                )
                params.extend([like, like, like, like])
            if date_from:
                where_parts.append("date(f.created_at) >= date(?)")
                params.append(date_from)
            if date_to:
                where_parts.append("date(f.created_at) <= date(?)")
                params.append(date_to)

            where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM files f
                {where_sql}
                """,
                tuple(params),
            )
            total = int(cursor.fetchone()[0])

            query_params = [*params, int(limit), int(offset)]
            cursor.execute(
                f"""
                SELECT f.*, GROUP_CONCAT(DISTINCT t.tag_name) AS all_tags
                FROM files f
                LEFT JOIN file_tags ft ON f.file_id = ft.file_id
                LEFT JOIN tags t ON ft.tag_id = t.tag_id
                {where_sql}
                GROUP BY f.file_id
                ORDER BY f.created_at DESC, f.file_id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(query_params),
            )
            return {"items": [dict(row) for row in cursor.fetchall()], "total": total}
        except sqlite3.Error as exc:
            logger.error("get_records_page failed: %s", exc)
            return {"items": [], "total": 0}
        finally:
            if conn:
                conn.close()
