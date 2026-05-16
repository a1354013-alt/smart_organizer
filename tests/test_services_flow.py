from __future__ import annotations

import re

from core import FileProcessor
from services import UploadedFileData, analyze_one_upload, finalize_one_file
from storage import StorageManager
from storage_base import MAX_UPLOAD_BYTES


def test_analyze_and_finalize_in_mem_mode():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    processor = FileProcessor()

    png_bytes = b"\x89PNG\r\n\x1a\n" + (b"0" * 32)
    uploaded = UploadedFileData(name="Screenshot_2026-01-01.png", content=png_bytes, mime_type="image/png")
    analyzed, dup, err = analyze_one_upload(
        uploaded,
        processor=processor,
        storage=storage,
        processing_options={"enable_ocr": False, "enable_pdf_preview": False},
    )
    assert dup is None
    assert err is None
    assert analyzed is not None
    assert analyzed.file_id > 0
    assert analyzed.file_type in {"photo", "document", "unknown"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", analyzed.standard_date)

    # Force deterministic finalize target path parts
    analyzed.standard_date = "2026-01-02"
    analyzed.main_topic = "截圖"
    exec_res = finalize_one_file(analyzed, storage=storage)
    assert exec_res.status == "SUCCESS"
    assert exec_res.new_path is not None
    assert exec_res.new_path.startswith("mem://repo/2026/2026-01/")


def test_analyze_one_upload_preserves_storage_validation_messages():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    processor = FileProcessor()

    cases = [
        UploadedFileData(name="notes.exe", content=b"not empty", mime_type="application/octet-stream"),
        UploadedFileData(name="empty.pdf", content=b"", mime_type="application/pdf"),
        UploadedFileData(name="fake.pdf", content=b"not a real pdf", mime_type="application/pdf"),
    ]

    messages: list[str] = []
    for uploaded in cases:
        analyzed, duplicate, error = analyze_one_upload(
            uploaded,
            processor=processor,
            storage=storage,
            processing_options={"enable_ocr": False, "enable_pdf_preview": False},
        )
        assert analyzed is None
        assert duplicate is None
        assert error is not None
        messages.append(error)

    assert "Unsupported upload extension: .exe" in messages[0]
    assert "Uploaded file is empty" in messages[1]
    assert "Invalid PDF signature" in messages[2]


def test_analyze_one_upload_preserves_large_file_message():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    processor = FileProcessor()
    uploaded = UploadedFileData(
        name="large.pdf",
        content=b"%PDF-" + (b"0" * MAX_UPLOAD_BYTES),
        mime_type="application/pdf",
    )

    analyzed, duplicate, error = analyze_one_upload(
        uploaded,
        processor=processor,
        storage=storage,
        processing_options={"enable_ocr": False, "enable_pdf_preview": False},
    )

    assert analyzed is None
    assert duplicate is None
    assert error is not None
    assert "File exceeds upload limit" in error
