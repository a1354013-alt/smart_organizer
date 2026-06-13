from __future__ import annotations

import subprocess
from pathlib import Path

import core_processor
from core import FileProcessor, FileUtils
from services import UploadedFileData, analyze_upload_batch
from storage import StorageManager


def test_fake_pdf_with_missing_optional_tools_returns_fallback_notes(monkeypatch, tmp_path: Path):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"%PDF-1.4\nnot a complete pdf\n%%EOF\n")
    monkeypatch.setattr(core_processor, "PdfReader", None)
    monkeypatch.setattr(core_processor, "convert_from_path_fn", None)
    monkeypatch.setattr(core_processor, "pytesseract", None)

    metadata = FileProcessor().extract_metadata(
        str(pdf),
        {"enable_pdf_preview": True, "enable_ocr": True, "pdf_text_max_pages": 1},
    )

    notes = "\n".join(metadata.get("notes", []))
    assert metadata["file_type"] == "document"
    assert metadata["standard_date"] != FileUtils.DEFAULT_UNKNOWN_DATE
    assert metadata["preview_path"] is None
    assert "PDF preview generation failed or timed out" in notes
    assert "dependencies_missing" in notes


def test_corrupt_pdf_text_extraction_does_not_crash(monkeypatch, tmp_path: Path):
    pdf = tmp_path / "corrupt.pdf"
    pdf.write_bytes(b"%PDF-1.4\ncorrupt")
    processor = FileProcessor()
    monkeypatch.setattr(
        processor,
        "_extract_pdf_text_with_timeout",
        lambda *_args, **_kwargs: (False, None, "PdfReadError: broken xref"),
    )

    metadata = processor.extract_metadata(str(pdf), {"enable_pdf_preview": False, "enable_ocr": False})

    notes = "\n".join(metadata.get("notes", []))
    assert metadata["file_type"] == "document"
    assert "PDF text extraction failed: PdfReadError: broken xref" in notes


def test_pdf_text_failure_does_not_interrupt_batch_analysis(monkeypatch, tmp_path: Path):
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    processor = FileProcessor()
    broken_pdf = UploadedFileData(
        name="broken.pdf",
        content=b"%PDF-1.4\nbroken\n%%EOF\n",
        mime_type="application/pdf",
    )
    valid_image = UploadedFileData(
        name="photo.jpg",
        content=b"\xff\xd8\xff\xd9",
        mime_type="image/jpeg",
    )
    original_extract_metadata = processor.extract_metadata

    def fake_extract_metadata(file_path: str, options=None):
        if str(file_path).endswith("broken.pdf"):
            raise RuntimeError("forced PDF text failure")
        return original_extract_metadata(file_path, options)

    monkeypatch.setattr(processor, "extract_metadata", fake_extract_metadata)

    outcome = analyze_upload_batch(
        [broken_pdf, valid_image],
        processor=processor,
        storage=storage,
        processing_options={"enable_ocr": False, "enable_pdf_preview": False},
    )

    assert outcome.errors == []
    assert len(outcome.results) == 2
    assert outcome.results[0].analysis_status == "PARTIAL"
    assert "extract_metadata failed" in str(outcome.results[0].last_error or "")
    assert outcome.results[1].metadata["file_type"] == "photo"


def test_image_metadata_and_ocr_fallback_for_corrupt_image(monkeypatch, tmp_path: Path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\xff\xd8\xffnot-a-real-image")

    class BrokenImage:
        @staticmethod
        def open(_path: str) -> object:
            raise OSError("cannot identify image file")

    monkeypatch.setattr(core_processor, "Image", BrokenImage)
    monkeypatch.setattr(core_processor, "pytesseract", object())

    metadata = FileProcessor().extract_metadata(str(image), {"enable_ocr": True})

    assert metadata["file_type"] == "photo"
    assert metadata["preview_path"] == str(image)
    assert metadata["extracted_text"] == ""
    assert metadata["ocr_status"] == "failed"
    assert metadata["ocr_error"] == "cannot identify image file"


def test_video_ffprobe_and_thumbnail_failures_are_degraded_notes(monkeypatch, tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    monkeypatch.setattr(core_processor, "is_ffmpeg_available", lambda: True)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="ffprobe failed")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(core_processor, "_run_video_subprocess", fake_run)
    monkeypatch.setattr(subprocess, "run", fake_run)

    metadata = FileProcessor().extract_metadata(str(video))

    notes = "\n".join(metadata.get("notes", []))
    assert metadata["file_type"] == "video"
    assert metadata["preview_path"] is None
    assert metadata["video"]["ffprobe_error"] == "ffprobe failed"
    assert "ffmpeg finished without creating a thumbnail" in notes
    assert "ffprobe failed" in notes


def test_unknown_extension_stays_conservative(tmp_path: Path):
    unknown = tmp_path / "clip.notvideo"
    unknown.write_bytes(b"video-like bytes")

    metadata = FileProcessor().extract_metadata(str(unknown))

    assert metadata["file_type"] == "unknown"
    assert "video" not in metadata
