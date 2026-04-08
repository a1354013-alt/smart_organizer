import hashlib

from storage import StorageManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_recover_moving_file_cleans_lingering_target_when_both_exist():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    res = storage.create_temp_file("x.pdf", payload, file_hash, "document")
    assert res["success"] is True
    file_id = res["file_id"]

    info = storage.get_file_by_id(file_id)
    temp_path = info["temp_path"]
    assert temp_path and storage._path_exists(temp_path)

    moving_target = "mem://repo/2026/04/target.pdf"
    # 模擬目標殘留：來源(temp)與目標(target)同時存在
    storage._mem_files[moving_target] = b"orphan-target"

    # 同時讓 DB 處於 MOVING 狀態，等待 recovery 處理
    conn = storage._get_connection()
    try:
        conn.execute(
            "UPDATE files SET status='MOVING', moving_target_path=?, last_error=? WHERE file_id=?",
            (moving_target, "previous error", file_id),
        )
        conn.commit()
    finally:
        conn.close()

    info2 = storage.get_file_by_id(file_id)
    assert info2["status"] == "MOVING"

    # 直接呼叫 recovery（finalize_organization 也會先呼叫它）
    storage._recover_moving_file(file_id, info2)

    info3 = storage.get_file_by_id(file_id)
    assert info3["status"] == "PROCESSED"
    assert info3.get("moving_target_path") in (None, "")
    # temp 應保留供重試
    assert storage._path_exists(temp_path)
    # target 殘留應被清掉
    assert not storage._path_exists(moving_target)
    # 不應清掉既有 last_error（避免覆蓋原始語意）
    assert info3.get("last_error") == "previous error"

