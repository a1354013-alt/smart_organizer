import hashlib
import uuid
from pathlib import Path

from storage import StorageManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _make_workspace_tmp_dir() -> Path:
    root = Path("tests") / "_tmp"
    root.mkdir(parents=True, exist_ok=True)
    d = root / uuid.uuid4().hex
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_update_file_metadata_keeps_completed_status():
    storage = StorageManager(
        ":memory:",
        ":memory:",
        ":memory:",
    )

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    original_name = "done.pdf"
    res = storage.create_temp_file(original_name, payload, file_hash, "document")
    file_id = res["file_id"]

    final_path = storage.finalize_organization(file_id, "2026-04-08", "發票", original_name)
    assert isinstance(final_path, str)
    assert storage.get_file_by_id(file_id)["status"] == "COMPLETED"

    storage.update_file_metadata(file_id, {
        "standard_date": "2026-04-08",
        "main_topic": "發票",
        "summary": "updated",
        "content": "content",
        "is_scanned": False,
        "preview_path": None,
        "classification_reason": "test",
        "tag_scores": {"發票": 1.0},
    })

    info = storage.get_file_by_id(file_id)
    assert info["status"] == "COMPLETED"
    assert info["final_path"] == final_path


def test_update_file_metadata_sets_processed_when_not_completed():
    storage = StorageManager(
        ":memory:",
        ":memory:",
        ":memory:",
    )

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    res = storage.create_temp_file("pending.pdf", payload, file_hash, "document")
    file_id = res["file_id"]

    storage.update_file_metadata(file_id, {
        "standard_date": "2026-04-08",
        "main_topic": "其他文件",
        "summary": "s",
        "content": "c",
        "is_scanned": False,
        "preview_path": None,
        "classification_reason": "test",
        "tag_scores": {"其他文件": 1.0},
    })

    assert storage.get_file_by_id(file_id)["status"] == "PROCESSED"
