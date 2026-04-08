import hashlib

import pytest

from storage import StorageManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_finalize_failure_persists_last_error_for_diagnosis():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    res = storage.create_temp_file("x.pdf", payload, file_hash, "document")
    assert res["success"] is True
    file_id = res["file_id"]

    # 人為破壞 temp_path，模擬暫存檔遺失/被清掉，finalize 應寫入 last_error 供 UI/維護查看
    conn = storage._get_connection()
    try:
        conn.execute("UPDATE files SET temp_path = ? WHERE file_id = ?", ("mem://uploads/missing.pdf", file_id))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(FileNotFoundError):
        storage.finalize_organization(file_id, "2026-04-08", "發票", "x.pdf")

    info = storage.get_file_by_id(file_id)
    assert info.get("last_error")

