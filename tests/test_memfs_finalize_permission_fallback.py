import hashlib

from storage import StorageManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_finalize_organization_memfs_permissionerror_fallback_uses_helpers():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    res = storage.create_temp_file("x.pdf", payload, file_hash, "document")
    assert res["success"] is True
    file_id = res["file_id"]

    original_move = storage._move_path

    def boom_move(src, dst):
        raise PermissionError("forced for test")

    storage._move_path = boom_move  # type: ignore[method-assign]
    try:
        final_path = storage.finalize_organization(file_id, "2026-04-08", "發票", "x.pdf")
    finally:
        storage._move_path = original_move  # type: ignore[method-assign]

    assert isinstance(final_path, str)
    assert final_path.startswith("mem://repo/")

    info = storage.get_file_by_id(file_id)
    assert info["status"] == "COMPLETED"
    assert info["final_path"] == final_path
    assert info.get("last_error") in (None, "")

