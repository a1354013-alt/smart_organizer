from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from storage import StorageManager


def _make_workspace_tmp_dir() -> Path:
    return Path("tests") / ("_unused_" + uuid.uuid4().hex)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _require_record(record: dict[str, object] | None) -> Mapping[str, object]:
    assert record is not None
    return record


def _page_items(page: dict[str, object]) -> list[Mapping[str, object]]:
    items = page.get("items")
    assert isinstance(items, list)
    return items


def test_create_temp_file_and_duplicate_detection():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)

    res1 = storage.create_temp_file('inv<>:"/\\\\|?*..a.pdf', payload, file_hash, "document")
    assert res1["success"] is True

    info = _require_record(storage.get_file_by_id(res1["file_id"]))
    assert str(info["original_name"]).endswith(".pdf")
    assert str(info["safe_name"]).endswith(".pdf")
    assert isinstance(info["temp_path"], str)

    res2 = storage.create_temp_file("anything.pdf", payload, file_hash, "document")
    assert res2["success"] is False
    assert res2["reason"] == "DUPLICATE"


def test_finalize_organization_uses_safe_name():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    original_name = 'inv<>:"/\\\\|?*..a.pdf'

    res = storage.create_temp_file(original_name, payload, file_hash, "document")
    file_id = res["file_id"]

    final_path = storage.finalize_organization(file_id, "2026-04-08", "?潛巨", original_name)
    assert isinstance(final_path, str)
    assert "<" not in os.path.basename(final_path)
    assert ">" not in os.path.basename(final_path)

    info = _require_record(storage.get_file_by_id(file_id))
    assert info["status"] == "COMPLETED"
    assert info["final_path"] == final_path
    assert info["final_name"] == os.path.basename(final_path)


def test_search_content_fts_and_fallback():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    res = storage.create_temp_file("invoice.pdf", payload, file_hash, "document")
    file_id = res["file_id"]

    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-04-08",
            "main_topic": "?潛巨",
            "summary": "皜祈岫??",
            "content": "hello world invoice 123",
            "is_scanned": False,
            "preview_path": None,
            "classification_reason": "test",
            "tag_scores": {"?潛巨": 1.0},
        },
    )

    r1 = storage.search_content("hello")
    assert any(r["file_id"] == file_id for r in r1)

    r2 = storage.search_content("?潛巨")
    assert any(r["file_id"] == file_id for r in r2)

    r3 = storage.search_content('(" )')
    assert r3 == []


def test_migration_failure_aborts_startup(tmp_path: Path):
    db_path = os.path.join(str(tmp_path), "bad.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE sys_config (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute('INSERT INTO sys_config(key, value) VALUES ("schema_version", "not-an-int")')
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError):
        StorageManager(db_path, ":memory:", ":memory:")


def test_close_is_idempotent():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    storage.close()
    storage.close()


def test_get_records_page_escapes_like_wildcards():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    payload = _minimal_pdf_bytes()

    names = ["100%complete.pdf", "under_score.pdf", "ordinary.pdf"]
    summaries = ["literal percent", "literal underscore", "plain text"]

    for name, summary in zip(names, summaries, strict=True):
        result = storage.create_temp_file(name, payload, _sha256(name.encode("utf-8")), "document")
        file_id = result["file_id"]
        storage.update_file_metadata(
            file_id,
            {
                "standard_date": "2026-05-07",
                "main_topic": "Docs",
                "summary": summary,
                "content": summary,
                "is_scanned": False,
                "preview_path": None,
                "classification_reason": "test",
                "tag_scores": {"Docs": 1.0},
            },
        )

    percent_hits = storage.get_records_page(search="%")
    underscore_hits = storage.get_records_page(search="_")
    keyword_hits = storage.get_records_page(search="ordinary")

    assert [item["original_name"] for item in _page_items(percent_hits)] == ["100%complete.pdf"]
    assert [item["original_name"] for item in _page_items(underscore_hits)] == ["under_score.pdf"]
    assert [item["original_name"] for item in _page_items(keyword_hits)] == ["ordinary.pdf"]


def test_search_content_returns_plain_text_snippets_without_html_tags():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    res = storage.create_temp_file("invoice.pdf", payload, _sha256(payload + b"plain"), "document")
    file_id = res["file_id"]

    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-04-08",
            "main_topic": "Invoices",
            "summary": "invoice summary",
            "content": "alpha invoice beta",
            "is_scanned": False,
            "preview_path": None,
            "classification_reason": "test",
            "tag_scores": {"Invoices": 1.0},
        },
    )

    hits = storage.search_content("invoice")
    assert hits
    snippet = str(hits[0].get("snippet") or "")
    assert "<b>" not in snippet
    assert "</b>" not in snippet
    assert "<mark>" not in snippet


class _FailingInsertCursor:
    def __init__(self, real_cursor: sqlite3.Cursor) -> None:
        self._real = real_cursor

    def execute(self, sql: str, params: Iterable[object] = ()) -> sqlite3.Cursor:
        if "INSERT INTO files" in sql:
            raise sqlite3.OperationalError("forced insert failure")
        return self._real.execute(sql, tuple(params))

    def fetchone(self) -> object:
        return self._real.fetchone()

    @property
    def lastrowid(self) -> int:
        return int(self._real.lastrowid or 0)


class _FailingInsertConnection:
    def __init__(self, real_conn: sqlite3.Connection) -> None:
        self._real = real_conn

    def cursor(self) -> _FailingInsertCursor:
        return _FailingInsertCursor(self._real.cursor())

    def rollback(self) -> None:
        self._real.rollback()

    def commit(self) -> None:
        self._real.commit()

    def close(self) -> None:
        self._real.close()


def test_create_temp_file_cleans_orphan_temp_file_when_db_insert_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = str(tmp_path / "test.db")
    repo_root = str(tmp_path / "repo")
    upload_dir = str(tmp_path / "uploads")
    storage = StorageManager(db_path, repo_root, upload_dir)
    real_get_connection = storage._get_connection

    def failing_get_connection() -> _FailingInsertConnection:
        return _FailingInsertConnection(real_get_connection())

    monkeypatch.setattr(storage, "_get_connection", failing_get_connection)

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload + b"dbfail")
    result = storage.create_temp_file("broken.pdf", payload, file_hash, "document")

    assert result["success"] is False
    assert list(Path(upload_dir).glob("*broken.pdf")) == []
