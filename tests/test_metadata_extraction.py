from __future__ import annotations

from pathlib import Path

import core_processor
from core import FileProcessor, FileUtils


def test_extract_metadata_pdf_scanned_when_no_text_and_ocr_disabled(tmp_path: Path):
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%EOF\n")

    processor = FileProcessor()
    metadata = processor.extract_metadata(
        str(pdf),
        {
            "enable_ocr": False,
            "enable_pdf_preview": False,
            "pdf_text_max_pages": 1,
            "pdf_ocr_max_pages": 1,
            "pdf_preview_max_pages": 1,
            "max_heavy_bytes": 1024 * 1024,
        },
    )

    assert metadata["file_type"] == "document"
    assert metadata["standard_date"] != FileUtils.DEFAULT_UNKNOWN_DATE
    assert metadata["is_scanned"] is True
    assert metadata["ocr_error"] == "OCR is disabled."
    assert any("PDF preview generation is disabled." in note for note in metadata.get("notes", []))


def test_extract_metadata_image_ocr_disabled_note(tmp_path: Path):
    image_path = tmp_path / "a.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xd9")

    processor = FileProcessor()
    metadata = processor.extract_metadata(str(image_path), {"enable_ocr": False})
    assert metadata["file_type"] == "photo"
    assert metadata["preview_path"] == str(image_path)
    assert metadata["ocr_status"] == "disabled"
    assert any("OCR is disabled." in note for note in metadata.get("notes", []))


def test_extract_metadata_video_reports_degraded_dependency_warning(monkeypatch, tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"video")

    monkeypatch.setattr(core_processor, "is_ffmpeg_available", lambda: False)
    processor = FileProcessor()
    metadata = processor.extract_metadata(str(video_path))

    assert metadata["file_type"] == "video"
    assert any("degraded:" in note.lower() for note in metadata.get("notes", []))
    assert metadata["video"]["ffprobe_error"] is not None


def test_extract_metadata_photo_ocr_unavailable_sets_status(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "a.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xd9")

    monkeypatch.setattr(core_processor, "Image", None)
    monkeypatch.setattr(core_processor, "pytesseract", None)

    metadata = FileProcessor().extract_metadata(str(image_path), {"enable_ocr": True})

    assert metadata["ocr_status"] == "unavailable"
    assert metadata["ocr_error"] == "OCR dependencies are unavailable."
    assert any("Image OCR unavailable" in note for note in metadata.get("notes", []))


def test_extract_metadata_photo_ocr_empty_text_sets_status(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "a.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xd9")

    class FakeImageModule:
        @staticmethod
        def open(_path: str) -> object:
            return object()

    class FakeTesseract:
        @staticmethod
        def image_to_string(_image: object, **_kwargs) -> str:
            return "   "

    monkeypatch.setattr(core_processor, "Image", FakeImageModule)
    monkeypatch.setattr(core_processor, "pytesseract", FakeTesseract)

    metadata = FileProcessor().extract_metadata(str(image_path), {"enable_ocr": True})

    assert metadata["ocr_status"] == "empty_text"
    assert metadata["ocr_error"] is None
