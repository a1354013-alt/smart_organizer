from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from services import (
    UploadedFileData,
    analyze_one_upload,
    discard_unfinished_record,
    reanalyze_unfinished_record,
    resume_unfinished_record,
)
from storage import CURRENT_SCHEMA_VERSION, StorageManager
from storage_lifecycle import MissingTemporaryFileError


class FakeProcessor:
    def get_file_hash(self, stream) -> str:
        return hashlib.sha256(stream.read()).hexdigest()

    def extract_metadata(self, file_path: str, options=None) -> dict[str, object]:
        return {
            "file_type": "document",
            "standard_date": "2026-07-15",
            "extracted_text": f"text from {Path(file_path).name}",
            "is_scanned": False,
            "preview_path": None,
            "ocr_error": None,
            "notes": [],
        }

    def classify_multi_tag(self, metadata, filename: str, return_reason: bool = False):
        del metadata, filename, return_reason
        return "document.invoice", {"document.invoice": 1.0}, "fake rule"


def _payload(label: str = "file") -> bytes:
    return f"%PDF-1.4\n% {label}\n%%EOF\n".encode()


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _storage(tmp_path: Path) -> StorageManager:
    return StorageManager(str(tmp_path / "smart.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))


def test_resume_after_session_loss_reanalyzes_saved_temp(tmp_path: Path):
    payload = _payload("resume")
    storage = _storage(tmp_path)
    created = storage.create_temp_file("resume.pdf", payload, _hash(payload), "document")
    file_id = int(created["file_id"])
    storage.close()

    resumed_storage = _storage(tmp_path)
    result = resume_unfinished_record(
        storage=resumed_storage,
        processor=FakeProcessor(),
        file_id=file_id,
    )

    record = resumed_storage.get_file_by_id(file_id)
    assert result.file_id == file_id
    assert record is not None
    assert record["status"] == "PROCESSED"
    assert record["main_topic"] == "document.invoice"


def test_duplicate_unfinished_upload_preserves_real_state(tmp_path: Path):
    payload = _payload("duplicate")
    storage = _storage(tmp_path)
    created = storage.create_temp_file("duplicate.pdf", payload, _hash(payload), "document")
    file_id = int(created["file_id"])
    storage.mark_unfinished_error(file_id, "retry later")

    analyzed, duplicate, error = analyze_one_upload(
        UploadedFileData(name="duplicate.pdf", content=payload, mime_type="application/pdf"),
        processor=FakeProcessor(),
        storage=storage,
    )

    assert analyzed is None
    assert error is None
    assert duplicate is not None
    assert duplicate.status == "ERROR"
    assert storage.get_file_by_id(file_id)["status"] == "ERROR"
    assert "reanalyze" in storage.get_unfinished_records()[0]["available_actions"]


def test_discard_unfinished_record_removes_db_references_and_allowed_artifacts(tmp_path: Path):
    payload = _payload("discard")
    storage = _storage(tmp_path)
    created = storage.create_temp_file("discard.pdf", payload, _hash(payload), "document")
    file_id = int(created["file_id"])
    preview = tmp_path / "uploads" / "previews" / "preview_discard.png"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"preview")
    unrelated = tmp_path / "uploads" / "notes-final.pdf"
    unrelated.write_bytes(b"keep")
    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-07-15",
            "main_topic": "document.invoice",
            "summary": "summary",
            "content": "searchable",
            "is_scanned": False,
            "preview_path": str(preview),
            "classification_reason": "rule",
            "final_decision_reason": "review",
            "manual_override": False,
            "tag_scores": {"document.invoice": 1.0},
        },
    )
    temp_path = Path(str(storage.get_file_path(file_id)))

    result = discard_unfinished_record(storage=storage, file_id=file_id)

    assert result["success"] is True
    assert storage.get_file_by_id(file_id) is None
    assert not temp_path.exists()
    assert not preview.exists()
    assert unrelated.exists()
    conn = storage._get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM file_tags WHERE file_id = ?", (file_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM file_content_fts WHERE rowid = ?", (file_id,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_missing_temp_file_marks_broken_and_can_discard(tmp_path: Path):
    payload = _payload("missing")
    storage = _storage(tmp_path)
    created = storage.create_temp_file("missing.pdf", payload, _hash(payload), "document")
    file_id = int(created["file_id"])
    temp_path = Path(str(storage.get_file_path(file_id)))
    temp_path.unlink()

    with pytest.raises(MissingTemporaryFileError):
        reanalyze_unfinished_record(storage=storage, processor=FakeProcessor(), file_id=file_id)

    assert storage.get_file_by_id(file_id)["status"] == "BROKEN"
    result = discard_unfinished_record(storage=storage, file_id=file_id)
    assert result["success"] is True
    assert storage.get_file_by_id(file_id) is None


def test_completed_duplicate_behavior_is_unchanged(tmp_path: Path):
    payload = _payload("completed")
    storage = _storage(tmp_path)
    created = storage.create_temp_file("completed.pdf", payload, _hash(payload), "document")
    file_id = int(created["file_id"])
    final_path = tmp_path / "repo" / "completed.pdf"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(payload)
    conn = storage._get_connection()
    try:
        conn.execute(
            "UPDATE files SET status = 'COMPLETED', final_path = ?, temp_path = NULL WHERE file_id = ?",
            (str(final_path), file_id),
        )
        conn.commit()
    finally:
        conn.close()

    analyzed, duplicate, error = analyze_one_upload(
        UploadedFileData(name="completed.pdf", content=payload, mime_type="application/pdf"),
        processor=FakeProcessor(),
        storage=storage,
    )

    assert analyzed is None
    assert error is None
    assert duplicate is not None
    assert duplicate.status == "COMPLETED"
    assert duplicate.final_path == str(final_path)


def test_schema_upgrade_adds_updated_at_without_data_loss(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE sys_config (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sys_config(key, value) VALUES ('schema_version', '15')")
        conn.execute(
            """
            CREATE TABLE files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT,
                safe_name TEXT,
                temp_path TEXT,
                file_hash TEXT UNIQUE,
                status TEXT DEFAULT 'PENDING',
                created_at TEXT DEFAULT '2026-07-15T00:00:00+00:00'
            )
            """
        )
        conn.execute(
            "INSERT INTO files(original_name, safe_name, temp_path, file_hash, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy.pdf", "legacy.pdf", str(tmp_path / "uploads" / "legacy.pdf"), "legacyhash", "PENDING", "2026-07-15T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    storage = StorageManager(str(db_path), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    record = storage.get_file_by_id(1)

    assert record is not None
    assert record["original_name"] == "legacy.pdf"
    assert record["updated_at"] == "2026-07-15T00:00:00+00:00"
    conn = storage._get_connection()
    try:
        assert conn.execute("SELECT value FROM sys_config WHERE key = 'schema_version'").fetchone()[0] == str(CURRENT_SCHEMA_VERSION)
    finally:
        conn.close()
