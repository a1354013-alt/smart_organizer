import hashlib

from storage import StorageManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_recover_target_cleanup_failure_writes_user_friendly_last_error():
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
    storage._mem_files[moving_target] = b"orphan-target"

    conn = storage._get_connection()
    try:
        conn.execute(
            "UPDATE files SET status='MOVING', moving_target_path=?, last_error=? WHERE file_id=?",
            (moving_target, "previous error", file_id),
        )
        conn.commit()
    finally:
        conn.close()

    original_remove = storage._remove_path

    def fail_remove(path_value):
        raise PermissionError("forced cleanup failure")

    storage._remove_path = fail_remove
    try:
        info2 = storage.get_file_by_id(file_id)
        storage._recover_moving_file(file_id, info2)
    finally:
        storage._remove_path = original_remove

    info3 = storage.get_file_by_id(file_id)
    assert info3["status"] == "PROCESSED"
    assert info3.get("moving_target_path") in (None, "")

    # temp 保留供重試
    assert storage._path_exists(temp_path)
    # target 仍殘留（因 cleanup 失敗）
    assert storage._path_exists(moving_target)

    # last_error 應保留既有訊息並追加「可理解摘要」，但不含 traceback
    le = info3.get("last_error") or ""
    assert "previous error" in le
    assert "Recovery:" in le
    assert "清理失敗" in le
