import hashlib

from storage import StorageManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_recover_double_missing_writes_diagnostic_last_error():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    res = storage.create_temp_file("x.pdf", payload, file_hash, "document")
    assert res["success"] is True
    file_id = res["file_id"]

    # 模擬 MOVING 狀態，但來源與目標都不存在（雙失蹤）
    missing_temp = "mem://uploads/missing.pdf"
    missing_target = "mem://repo/2026/04/missing_target.pdf"

    conn = storage._get_connection()
    try:
        conn.execute(
            "UPDATE files SET status='MOVING', temp_path=?, moving_target_path=?, last_error=? WHERE file_id=?",
            (missing_temp, missing_target, "previous error", file_id),
        )
        conn.commit()
    finally:
        conn.close()

    info = storage.get_file_by_id(file_id)
    assert info["status"] == "MOVING"

    storage._recover_moving_file(file_id, info)

    info2 = storage.get_file_by_id(file_id)
    assert info2["status"] == "PROCESSED"
    assert info2.get("moving_target_path") in (None, "")

    le = info2.get("last_error") or ""
    assert "previous error" in le
    assert "Recovery:" in le
    assert "來源與目標皆不存在" in le
