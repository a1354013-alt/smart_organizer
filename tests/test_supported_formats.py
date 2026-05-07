from __future__ import annotations

from pathlib import Path

from core import FileUtils
from supported_formats import SUPPORTED_UPLOAD_EXTENSIONS, supported_upload_extensions_label
from ui_upload import get_supported_upload_caption, get_supported_upload_types


def test_ui_upload_types_match_backend_extensions():
    assert tuple(get_supported_upload_types()) == SUPPORTED_UPLOAD_EXTENSIONS
    assert set(f".{ext}" for ext in get_supported_upload_types()) == set(FileUtils.ALLOWED_UPLOAD_EXTENSIONS)


def test_readme_supported_formats_match_single_source():
    readme = Path("README.md").read_text(encoding="utf-8")
    expected_line = f"Supported upload formats: `{supported_upload_extensions_label()}`."

    assert get_supported_upload_caption() == supported_upload_extensions_label()
    assert expected_line in readme
