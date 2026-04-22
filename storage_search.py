from __future__ import annotations

import logging
import sqlite3
from typing import Any

from core import FileUtils

from storage_base import SearchContentError

logger = logging.getLogger(__name__)


class StorageSearchMixin:
    _META_SCORE_ORIGINAL_NAME = 2.0
    _META_SCORE_MAIN_TOPIC = 1.2
    _META_SCORE_SUMMARY = 1.0
    _META_SCORE_TAG = 0.8

    def _escape_like(self, s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _score_metadata_row(self, q_lower: str, row_dict: dict[str, object]) -> float:
        score = 0.0
        if q_lower in (str(row_dict.get("original_name") or "")).lower():
            score += self._META_SCORE_ORIGINAL_NAME
        if q_lower in (str(row_dict.get("main_topic") or "")).lower():
            score += self._META_SCORE_MAIN_TOPIC
        if q_lower in (str(row_dict.get("summary") or "")).lower():
            score += self._META_SCORE_SUMMARY
        if q_lower in (str(row_dict.get("all_tags") or "")).lower():
            score += self._META_SCORE_TAG
        return score

    def search_content(self: Any, query: str, limit: int = 50):
        q = (query or "").strip()
        safe_query = FileUtils.escape_fts_query(q)

        if not safe_query or not safe_query.strip():
            return []

        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            merged: dict[int, dict[str, object]] = {}

            fts_ids: list[int] = []
            try:
                cursor.execute(
                    """
                    SELECT
                        f.file_id,
                        f.original_name,
                        f.standard_date,
                        f.main_topic,
                        f.summary,
                        f.final_path,
                        f.created_at,
                        snippet(file_content_fts, 3, '<b>', '</b>', '...', 20) as snippet,
                        bm25(file_content_fts) as fts_rank
                    FROM file_content_fts
                    JOIN files f ON file_content_fts.rowid = f.file_id
                    WHERE file_content_fts MATCH ?
                    ORDER BY bm25(file_content_fts)
                    LIMIT ?
                    """,
                    (safe_query, int(limit)),
                )

                for row in cursor.fetchall():
                    d = dict(row)
                    rank = d.get("fts_rank")
                    try:
                        rank = float(rank) if rank is not None else 9999.0
                    except Exception:
                        rank = 9999.0
                    d["_score"] = 1.0 / (1.0 + max(rank, 0.0))
                    d["all_tags"] = None
                    merged[int(d["file_id"])] = d
                    fts_ids.append(int(d["file_id"]))
            except Exception as fts_err:
                logger.error("FTS 主查詢失敗: %s", fts_err, exc_info=True)
                fts_ids = []

            if fts_ids:
                try:
                    placeholders = ",".join(["?"] * len(fts_ids))
                    cursor.execute(
                        f"""
                        SELECT ft.file_id, t.tag_name
                        FROM file_tags ft
                        JOIN tags t ON ft.tag_id = t.tag_id
                        WHERE ft.file_id IN ({placeholders})
                        """,
                        tuple(fts_ids),
                    )
                    tag_map: dict[int, list[str]] = {}
                    for file_id, tag_name in cursor.fetchall():
                        if not tag_name:
                            continue
                        tag_map.setdefault(int(file_id), []).append(tag_name)
                    for file_id in fts_ids:
                        tags = tag_map.get(int(file_id), [])
                        if tags and file_id in merged:
                            merged[file_id]["all_tags"] = ", ".join(sorted(set(tags)))
                except Exception as tag_err:
                    logger.warning("FTS tags 補查失敗（不影響主結果）: %s", tag_err)

            like = f"%{self._escape_like(q)}%"
            cursor.execute(
                """
                SELECT
                    f.*,
                    GROUP_CONCAT(t.tag_name) as all_tags
                FROM files f
                LEFT JOIN file_tags ft ON f.file_id = ft.file_id
                LEFT JOIN tags t ON ft.tag_id = t.tag_id
                WHERE
                    f.original_name LIKE ? ESCAPE '\\'
                    OR COALESCE(f.summary, '') LIKE ? ESCAPE '\\'
                    OR COALESCE(f.main_topic, '') LIKE ? ESCAPE '\\'
                    OR COALESCE(t.tag_name, '') LIKE ? ESCAPE '\\'
                GROUP BY f.file_id
                ORDER BY f.created_at DESC
                LIMIT ?
                """,
                (like, like, like, like, int(limit)),
            )

            q_lower = q.lower()
            for row in cursor.fetchall():
                d = dict(row)
                score = self._score_metadata_row(q_lower, d)
                fid = int(d["file_id"])

                if fid in merged:
                    base_score_obj = merged[fid].get("_score", 0.0)
                    try:
                        base_score = float(base_score_obj)  # type: ignore[arg-type]
                    except Exception:
                        base_score = 0.0
                    merged[fid]["_score"] = base_score + score
                    if not merged[fid].get("snippet"):
                        merged[fid]["snippet"] = (d.get("summary") or d.get("main_topic") or "")[:120]
                    if d.get("all_tags") and not merged[fid].get("all_tags"):
                        merged[fid]["all_tags"] = d.get("all_tags")
                else:
                    d["snippet"] = (d.get("summary") or d.get("main_topic") or "")[:120]
                    d["_score"] = score
                    merged[fid] = d

            results = list(merged.values())
            results.sort(key=lambda r: (r.get("_score", 0.0), r.get("created_at", "")), reverse=True)
            for r in results:
                r.pop("_score", None)
                r.pop("fts_rank", None)
            return results[: int(limit)]

        except Exception as e:
            logger.error("搜尋查詢失敗", exc_info=True)
            raise SearchContentError("搜尋功能暫時不可用，請稍後再試或檢查資料庫狀態。") from e
        finally:
            if conn:
                conn.close()

    def rebuild_fts_index(self: Any):
        conn: sqlite3.Connection | None = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("DROP TABLE IF EXISTS fts_rebuild_backup")
            cursor.execute("CREATE TEMP TABLE fts_rebuild_backup AS SELECT rowid, content FROM file_content_fts")
            cursor.execute("DELETE FROM file_content_fts")
            cursor.execute(
                """
                INSERT INTO file_content_fts(rowid, original_filename, title, summary, content)
                SELECT
                    f.file_id,
                    COALESCE(f.original_name, ''),
                    COALESCE(f.main_topic, ''),
                    COALESCE(f.summary, ''),
                    COALESCE(b.content, '')
                FROM files f
                LEFT JOIN fts_rebuild_backup b ON f.file_id = b.rowid
                """
            )
            cursor.execute("DROP TABLE IF EXISTS fts_rebuild_backup")
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error("重建 FTS 索引失敗: %s", e)
            if conn:
                conn.rollback()
            return {"success": False, "error": str(e)}
        finally:
            if conn:
                conn.close()
