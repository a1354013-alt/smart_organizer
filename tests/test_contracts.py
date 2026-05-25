from __future__ import annotations

import pytest

from contracts import validate_extracted_metadata


def test_validate_extracted_metadata_normalizes_basic_shape():
    metadata = validate_extracted_metadata(
        {
            "file_type": "document",
            "standard_date": "2026-04-10",
            "extracted_text": None,
            "is_scanned": 1,
            "preview_path": None,
            "ocr_error": None,
            "notes": ["a", 123],
        }
    )

    assert metadata["file_type"] == "document"
    assert metadata["extracted_text"] == ""
    assert metadata["is_scanned"] is True
    assert metadata["notes"] == ["a", "123"]


def test_validate_extracted_metadata_rejects_contract_keys_in_extra():
    with pytest.raises(ValueError):
        validate_extracted_metadata(
            {
                "file_type": "document",
                "standard_date": "2026-04-10",
                "extracted_text": "",
                "is_scanned": False,
                "preview_path": None,
                "ocr_error": None,
                "notes": [],
                "extra": {"standard_date": "should-not-live-here"},
            }
        )


def test_validate_extracted_metadata_cleans_dirty_numeric_video_fields_and_truncates_text():
    metadata = validate_extracted_metadata(
        {
            "file_type": "video",
            "standard_date": "2026-04-10",
            "extracted_text": "x" * 30000,
            "is_scanned": "true",
            "preview_path": " /tmp/preview.png ",
            "ocr_status": "success",
            "ocr_error": "e" * 500,
            "notes": [" keep me ", "", "n" * 500],
            "video": {
                "duration_seconds": "12.5",
                "width": "1920",
                "height": "-1",
                "fps": "nan",
                "file_size": "2048",
                "video_codec": "h264" * 100,
                "ffprobe_error": "f" * 500,
                "thumbnail_error": "t" * 500,
            },
        }
    )

    assert metadata["is_scanned"] is True
    assert metadata["preview_path"] == "/tmp/preview.png"
    assert metadata["ocr_status"] == "success"
    assert len(metadata["extracted_text"]) == 20000
    assert len(metadata["ocr_error"] or "") == 300
    assert metadata["notes"][0] == "keep me"
    assert len(metadata["notes"][1]) == 300
    assert metadata["video"]["duration_seconds"] == 12.5
    assert metadata["video"]["width"] == 1920
    assert metadata["video"]["height"] is None
    assert metadata["video"]["fps"] is None
    assert metadata["video"]["file_size"] == 2048
    assert len(metadata["video"]["video_codec"] or "") == 120
    assert len(metadata["video"]["ffprobe_error"] or "") == 300
    assert len(metadata["video"]["thumbnail_error"] or "") == 300


def test_validate_extracted_metadata_promotes_legacy_video_extra_without_leaking_reserved_keys():
    metadata = validate_extracted_metadata(
        {
            "file_type": "video",
            "standard_date": "2026-04-10",
            "extracted_text": "",
            "is_scanned": False,
            "preview_path": None,
            "ocr_error": None,
            "notes": [],
            "extra": {
                "duration_seconds": "4.5",
                "width": "640",
                "video_codec": "vp9",
                "custom_hint": "keep",
            },
        }
    )

    assert metadata["video"]["duration_seconds"] == 4.5
    assert metadata["video"]["width"] == 640
    assert metadata["video"]["video_codec"] == "vp9"
    assert metadata["extra"] == {"custom_hint": "keep"}

