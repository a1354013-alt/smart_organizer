from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from i18n import t
from ui_common import UIContext, safe_css_class_name, safe_display_text
from ui_upload import resolve_upload_limits, validate_upload_batch_limits


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
    assert t("upload.limit_batch", size="15 B", max_size="12 B") == errors[0]


def test_upload_per_file_limit_escapes_filename_in_error():
    errors = validate_upload_batch_limits(
        [FakeUpload(name="<b>bad.pdf", size=11)],
        max_file_bytes=10,
        max_batch_bytes=100,
    )

    assert len(errors) == 1
    assert "&lt;b&gt;bad.pdf" in errors[0]
    assert t("upload.limit_file", name="&lt;b&gt;bad.pdf", size="11 B", max_size="10 B") == errors[0]


def test_upload_batch_limit_reports_when_total_exceeds_even_if_each_file_is_individually_valid():
    errors = validate_upload_batch_limits(
        [
            FakeUpload(name="first.pdf", size=9),
            FakeUpload(name="second.pdf", size=9),
        ],
        max_file_bytes=10,
        max_batch_bytes=16,
    )

    assert errors == [t("upload.limit_batch", size="18 B", max_size="16 B")]


def test_upload_batch_limits_allow_valid_multi_file_selection():
    errors = validate_upload_batch_limits(
        [
            FakeUpload(name="first.pdf", size=4),
            FakeUpload(name="second.pdf", size=5),
        ],
        max_file_bytes=10,
        max_batch_bytes=12,
    )

    assert errors == []


def test_resolve_upload_limits_uses_explicit_batch_limit():
    context = UIContext(
        processor=object(),
        storage=object(),
        project_root=Path("."),
        upload_dir=Path("uploads"),
        repo_root=Path("repo"),
        db_path=Path("app.db"),
        max_upload_bytes=10,
        max_upload_batch_bytes=30,
    )

    assert resolve_upload_limits(context) == (10, 30)
