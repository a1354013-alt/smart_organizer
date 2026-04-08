import hashlib

import pytest

from storage import StorageManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_finalize_partial_copy_failure_cleans_target_and_rolls_back_state():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    res = storage.create_temp_file("x.pdf", payload, file_hash, "document")
    assert res["success"] is True
    file_id = res["file_id"]

    original_move = storage._move_path
    original_copy = storage._copy_path

    def force_perm_error(src, dst):
        raise PermissionError("forced move error")

    def partial_then_fail(src, dst):
        # 模擬「target 已建立但 copy 中途失敗」
        storage._mem_files[dst] = b"partial"
        raise RuntimeError("forced copy failure after creating target")

    storage._move_path = force_perm_error  # type: ignore[method-assign]
    storage._copy_path = partial_then_fail  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError):
            storage.finalize_organization(file_id, "2026-04-08", "發票", "x.pdf")
    finally:
        storage._move_path = original_move  # type: ignore[method-assign]
        storage._copy_path = original_copy  # type: ignore[method-assign]

    info = storage.get_file_by_id(file_id)
    assert info["status"] == "PROCESSED"
    assert info.get("moving_target_path") in (None, "")
    assert info.get("last_error")

    # temp_path 應仍在（可重試），target 應已被清理（避免髒檔）
    temp_path = info.get("temp_path")
    assert temp_path and storage._path_exists(temp_path)
    # 無法直接從 DB 得知 target_path（已被清空），但可用 mem_files 確認 repo 內沒有任何目標檔
    assert all(not k.startswith("mem://repo/") for k in storage._mem_files.keys())

