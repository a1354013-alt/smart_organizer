from __future__ import annotations

import re

from core import FileProcessor
from services import (
    BatchAnalysisOutcome,
    UploadedFileData,
    analyze_upload_batch,
    analyze_upload_batch_async,
)
from storage import StorageManager


def test_analyze_upload_batch_async_importable_and_callable():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    processor = FileProcessor()
    outcome = analyze_upload_batch_async([], processor=processor, storage=storage, max_workers=1)
    assert isinstance(outcome, BatchAnalysisOutcome)


def test_analyze_upload_batch_async_empty_batch_returns_ok():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    processor = FileProcessor()
    outcome = analyze_upload_batch_async([], processor=processor, storage=storage, max_workers=1)
    assert outcome.results == []
    assert outcome.duplicates == []
    assert outcome.errors == []


def test_analyze_upload_batch_async_minimal_batch_progress_and_contract():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    processor = FileProcessor()

    png_bytes = b"\x89PNG\r\n\x1a\n" + (b"0" * 32)
    uploaded = UploadedFileData(name="Screenshot_2026-01-01.png", content=png_bytes, mime_type="image/png")

    progress_events: list[tuple[int, int]] = []

    def on_progress(current: int, total: int) -> None:
        progress_events.append((int(current), int(total)))

    outcome = analyze_upload_batch_async(
        [uploaded],
        processor=processor,
        storage=storage,
        processing_options={"enable_ocr": False, "enable_pdf_preview": False},
        progress_callback=on_progress,
        max_workers=1,
    )

    assert outcome.duplicates == []
    assert outcome.errors == []
    assert len(outcome.results) == 1

    analyzed = outcome.results[0]
    assert analyzed.file_id > 0
    assert analyzed.original_name == uploaded.name
    assert analyzed.file_type in {"photo", "document", "unknown"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", analyzed.standard_date)

    # Progress callback contract: (current, total) integers and completes to (1, 1) for 1-item batch.
    assert progress_events
    assert progress_events[-1] == (1, 1)


def test_sync_and_async_batch_validation_share_total_size_limit(monkeypatch):
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    processor = FileProcessor()
    uploads = [
        UploadedFileData(name="one.pdf", content=b"%PDF-1.4\n" + b"a" * 8, mime_type="application/pdf"),
        UploadedFileData(name="two.pdf", content=b"%PDF-1.4\n" + b"b" * 8, mime_type="application/pdf"),
    ]

    monkeypatch.setattr("services_analysis.MAX_UPLOAD_BATCH_BYTES", 12)
    monkeypatch.setattr("services_analysis.MAX_UPLOAD_BYTES", 100)

    sync_outcome = analyze_upload_batch(uploads, processor=processor, storage=storage)
    async_outcome = analyze_upload_batch_async(uploads, processor=processor, storage=storage, max_workers=1)

    expected = "Batch size 34 bytes exceeds the upload batch limit of 12 bytes."
    assert sync_outcome.errors == [expected]
    assert async_outcome.errors == [expected]


def test_sync_and_async_batch_validation_share_single_file_errors(monkeypatch):
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    processor = FileProcessor()
    uploads = [UploadedFileData(name="huge.pdf", content=b"%PDF-1.4\n" + b"x" * 20, mime_type="application/pdf")]

    monkeypatch.setattr("services_analysis.MAX_UPLOAD_BATCH_BYTES", 100)
    monkeypatch.setattr("services_analysis.MAX_UPLOAD_BYTES", 10)

    sync_outcome = analyze_upload_batch(uploads, processor=processor, storage=storage)
    async_outcome = analyze_upload_batch_async(uploads, processor=processor, storage=storage, max_workers=1)

    expected = "huge.pdf: file size 29 bytes exceeds the per-file limit of 10 bytes."
    assert sync_outcome.errors == [expected]
    assert async_outcome.errors == [expected]
