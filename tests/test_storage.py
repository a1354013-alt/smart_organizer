import hashlib
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest

from storage import StorageManager


def _make_workspace_tmp_dir() -> Path:
    # 已改用 storage 的 in-memory 檔案模式；保留函式避免大改動（不再建立資料夾）。
    return Path("tests") / ("_unused_" + uuid.uuid4().hex)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    # 只需通過簽章檢查（%PDF-）即可
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_create_temp_file_and_duplicate_detection():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)

    res1 = storage.create_temp_file('inv<>:"/\\\\|?*..a.pdf', payload, file_hash, "document")
    assert res1["success"] is True

    info = storage.get_file_by_id(res1["file_id"])
    assert info["original_name"].endswith(".pdf")
    assert info["safe_name"].endswith(".pdf")
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

    final_path = storage.finalize_organization(file_id, "2026-04-08", "發票", original_name)
    assert isinstance(final_path, str)
    assert "<" not in os.path.basename(final_path)
    assert ">" not in os.path.basename(final_path)

    info = storage.get_file_by_id(file_id)
    assert info["status"] == "COMPLETED"
    assert info["final_path"] == final_path
    assert info["final_name"] == os.path.basename(final_path)


def test_search_content_fts_and_fallback():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    res = storage.create_temp_file("invoice.pdf", payload, file_hash, "document")
    file_id = res["file_id"]

    storage.update_file_metadata(file_id, {
        "standard_date": "2026-04-08",
        "main_topic": "發票",
        "summary": "測試摘要",
        "content": "hello world invoice 123",
        "is_scanned": False,
        "preview_path": None,
        "classification_reason": "test",
        "tag_scores": {"發票": 1.0},
    })

    r1 = storage.search_content("hello")
    assert any(r["file_id"] == file_id for r in r1)

    # fallback：不依賴 content，也能用 main_topic / tags 命中
    r2 = storage.search_content("發票")
    assert any(r["file_id"] == file_id for r in r2)

    # 特殊字元不應造成崩潰
    r3 = storage.search_content('(" )')
    assert r3 == []


def test_migration_failure_aborts_startup():
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "bad.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE sys_config (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute('INSERT INTO sys_config(key, value) VALUES ("schema_version", "not-an-int")')
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(RuntimeError):
            StorageManager(db_path, ":memory:", ":memory:")
