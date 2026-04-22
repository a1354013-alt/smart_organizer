from __future__ import annotations

from core import FileProcessor


def test_classify_document_invoice_keywords_from_text():
    p = FileProcessor()
    metadata = {
        "file_type": "document",
        "extracted_text": "公司 統一編號 12345678 發票",
        "is_scanned": False,
    }
    main_topic, tags, reason = p.classify_multi_tag(metadata, "any.pdf", return_reason=True)
    assert main_topic == "發票"
    assert "發票" in tags
    assert "內容包含關鍵字" in reason or "檔名包含關鍵字" in reason


def test_classify_photo_screenshot_from_filename():
    p = FileProcessor()
    metadata = {
        "file_type": "photo",
        "extracted_text": "",
        "is_scanned": False,
    }
    main_topic, tags, reason = p.classify_multi_tag(metadata, "Screenshot_2026-01-01.png", return_reason=True)
    assert main_topic == "截圖"
    assert "截圖" in tags
    assert "檔名包含關鍵字" in reason


def test_pdf_extension_forces_document_even_if_metadata_says_photo():
    p = FileProcessor()
    metadata = {"file_type": "photo", "extracted_text": "contract agreement", "is_scanned": False}
    main_topic, tags, _ = p.classify_multi_tag(metadata, "weird.pdf", return_reason=True)
    # Because ext is .pdf, it must be treated as document.
    assert main_topic in tags
    assert "合約" in tags or "其他文件" in tags


def test_classify_video_meeting_keywords_from_filename():
    p = FileProcessor()
    metadata = {"file_type": "video", "extracted_text": "", "is_scanned": False}
    main_topic, tags, reason = p.classify_multi_tag(metadata, "zoom_meeting_2026.mp4", return_reason=True)
    assert main_topic == "Meeting"
    assert "Meeting" in tags
    assert "命中關鍵字" in reason


def test_classify_video_screen_recording_keywords_from_filename():
    p = FileProcessor()
    metadata = {"file_type": "video", "extracted_text": "", "is_scanned": False}
    main_topic, tags, reason = p.classify_multi_tag(metadata, "screen_recording_demo.mp4", return_reason=True)
    assert main_topic == "Screen Recording"
    assert "Screen Recording" in tags
    assert "命中關鍵字" in reason

