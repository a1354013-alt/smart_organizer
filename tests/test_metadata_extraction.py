from __future__ import annotations

from pathlib import Path

from core import FileProcessor, FileUtils


def test_extract_metadata_pdf_scanned_when_no_text_and_ocr_disabled(tmp_path: Path):
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%EOF\n")

    p = FileProcessor()
    meta = p.extract_metadata(
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

    assert meta["file_type"] == "document"
    assert meta["standard_date"] != FileUtils.DEFAULT_UNKNOWN_DATE
    assert meta["is_scanned"] is True
    assert meta["ocr_error"] == "OCR 已停用（設定）。"
    assert any("PDF 預覽已停用" in n for n in meta.get("notes", []))


def test_extract_metadata_image_ocr_disabled_note(tmp_path: Path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")  # minimal JPEG markers

    p = FileProcessor()
    meta = p.extract_metadata(str(img), {"enable_ocr": False})
    assert meta["file_type"] == "photo"
    assert meta["preview_path"] == str(img)
    assert any("OCR 已停用" in n for n in meta.get("notes", []))

