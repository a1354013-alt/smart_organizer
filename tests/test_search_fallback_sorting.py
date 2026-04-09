from __future__ import annotations

import sqlite3

import pytest

from storage import StorageManager


class _ProxyCursor:
    def __init__(self, real: sqlite3.Cursor):
        self._real = real

    def execute(self, sql, params=()):
        if "FROM file_content_fts" in sql:
            raise sqlite3.OperationalError("simulated fts failure")
        return self._real.execute(sql, params)

    def fetchall(self):
        return self._real.fetchall()

    def fetchone(self):
        return self._real.fetchone()

    @property
    def lastrowid(self):
        return self._real.lastrowid


class _ProxyConn:
    def __init__(self, real: sqlite3.Connection):
        self._real = real

    def cursor(self):
        return _ProxyCursor(self._real.cursor())

    def execute(self, *a, **k):
        return self._real.execute(*a, **k)

    def commit(self):
        return self._real.commit()

    def rollback(self):
        return self._real.rollback()

    def close(self):
        return self._real.close()

    @property
    def row_factory(self):
        return self._real.row_factory

    @row_factory.setter
    def row_factory(self, v):
        self._real.row_factory = v


def test_search_fallback_sorting_prefers_original_name(monkeypatch: pytest.MonkeyPatch):
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    # Insert two files with different metadata match strengths
    pdf_bytes = b"%PDF-1.4\n%EOF\n"
    r1 = storage.create_temp_file("alpha_document.pdf", pdf_bytes, "a" * 64, "document")
    r2 = storage.create_temp_file("other.pdf", pdf_bytes, "b" * 64, "document")
    assert r1["success"] and r2["success"]
    id1 = int(r1["file_id"])
    id2 = int(r2["file_id"])

    storage.update_file_metadata(
        id1,
        {
            "standard_date": "2026-01-01",
            "main_topic": "其他文件",
            "summary": "",
            "content": "",
            "is_scanned": False,
            "preview_path": None,
            "classification_reason": "",
            "final_decision_reason": "採用規則建議",
            "manual_override": False,
            "tag_scores": {},
        },
    )
    storage.update_file_metadata(
        id2,
        {
            "standard_date": "2026-01-01",
            "main_topic": "其他文件",
            "summary": "this contains alpha",
            "content": "",
            "is_scanned": False,
            "preview_path": None,
            "classification_reason": "",
            "final_decision_reason": "採用規則建議",
            "manual_override": False,
            "tag_scores": {},
        },
    )

    # Force FTS stage to fail so we verify fallback sorting deterministically.
    real_get_conn = storage._get_connection

    def _get_conn(*a, **k):
        return _ProxyConn(real_get_conn(*a, **k))

    monkeypatch.setattr(storage, "_get_connection", _get_conn)

    results = storage.search_content("alpha", limit=10)
    assert len(results) >= 2
    assert results[0]["file_id"] == id1  # original_name weight > summary weight (stable contract)
    assert results[1]["file_id"] == id2
