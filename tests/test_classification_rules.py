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
    assert main_topic == "document.invoice"
    assert "document.invoice" in tags
    assert "matched extracted-text keyword set" in reason


def test_classify_photo_screenshot_from_filename():
    p = FileProcessor()
    metadata = {
        "file_type": "photo",
        "extracted_text": "",
        "is_scanned": False,
    }
    main_topic, tags, reason = p.classify_multi_tag(metadata, "Screenshot_2026-01-01.png", return_reason=True)
    assert main_topic == "photo.screenshot"
    assert "photo.screenshot" in tags
    assert "matched filename keyword set" in reason


def test_pdf_extension_forces_document_even_if_metadata_says_photo():
    p = FileProcessor()
    metadata = {"file_type": "photo", "extracted_text": "contract agreement", "is_scanned": False}
    main_topic, tags, _ = p.classify_multi_tag(metadata, "weird.pdf", return_reason=True)
    assert main_topic in tags
    assert "document.contract" in tags or "document.other" in tags


def test_classify_video_meeting_keywords_from_filename():
    p = FileProcessor()
    metadata = {"file_type": "video", "extracted_text": "", "is_scanned": False}
    main_topic, tags, reason = p.classify_multi_tag(metadata, "zoom_meeting_2026.mp4", return_reason=True)
    assert main_topic == "video.meeting"
    assert "video.meeting" in tags
    assert "matched keyword meeting" in reason


def test_classify_video_screen_recording_keywords_from_filename():
    p = FileProcessor()
    metadata = {"file_type": "video", "extracted_text": "", "is_scanned": False}
    main_topic, tags, reason = p.classify_multi_tag(metadata, "screen_recording_demo.mp4", return_reason=True)
    assert main_topic == "video.screen_recording"
    assert "video.screen_recording" in tags
    assert "matched keyword screen" in reason
