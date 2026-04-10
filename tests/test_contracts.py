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

