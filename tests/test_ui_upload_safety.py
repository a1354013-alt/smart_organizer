from __future__ import annotations

from dataclasses import dataclass

from ui_common import safe_css_class_name, safe_display_text
from ui_upload import validate_upload_batch_limits


@dataclass
class FakeUpload:
    name: str
    size: int


def test_safe_display_text_escapes_html_like_user_input():
    assert safe_display_text("<img src=x onerror=alert(1)>") == "&lt;img src=x onerror=alert(1)&gt;"


def test_safe_css_class_name_rejects_html_injection_tokens():
    assert safe_css_class_name("status-card") == "status-card"
    try:
        safe_css_class_name('status-card" onclick="alert(1)')
    except ValueError as exc:
        assert "Unsafe CSS class name" in str(exc)
    else:
        raise AssertionError("Expected invalid CSS class name to be rejected")


def test_upload_batch_limit_reports_clear_error_with_escaped_filename():
    errors = validate_upload_batch_limits(
        [
            FakeUpload(name="<script>.pdf", size=7),
            FakeUpload(name="large.pdf", size=8),
        ],
        max_file_bytes=10,
        max_batch_bytes=12,
    )

    assert len(errors) == 1
    assert "Batch size" in errors[0]
    assert "upload batch limit" in errors[0]


def test_upload_per_file_limit_escapes_filename_in_error():
    errors = validate_upload_batch_limits(
        [FakeUpload(name="<b>bad.pdf", size=11)],
        max_file_bytes=10,
        max_batch_bytes=100,
    )

    assert len(errors) == 1
    assert "&lt;b&gt;bad.pdf" in errors[0]
    assert "per-file limit" in errors[0]
