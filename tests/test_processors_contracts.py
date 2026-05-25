from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
from types import ModuleType

import processors.optional_deps as optional_deps
from processors.metadata_contract import build_invalid_video_metadata, build_metadata_payload
from processors.optional_deps import __file__ as optional_deps_file


def _load_optional_deps_with_blocked_imports(blocked_roots: set[str], monkeypatch) -> ModuleType:
    module_path = Path(str(optional_deps_file))
    spec = importlib.util.spec_from_file_location("test_optional_deps_isolated", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001, ANN002, ANN003
        root = name.split(".", 1)[0]
        if root in blocked_roots:
            raise ImportError(f"blocked import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    spec.loader.exec_module(module)
    return module


def test_optional_deps_exports_all_expected_symbols():
    for name in ("Image", "exifread_module", "PdfReader", "convert_from_path_fn", "pytesseract", "OpenAI"):
        assert hasattr(optional_deps, name)


def test_optional_deps_falls_back_to_none_when_optional_imports_fail(monkeypatch):
    module = _load_optional_deps_with_blocked_imports(
        {"PIL", "exifread", "pypdf", "pdf2image", "pytesseract", "openai"},
        monkeypatch,
    )

    assert module.Image is None
    assert module.exifread_module is None
    assert module.PdfReader is None
    assert module.convert_from_path_fn is None
    assert module.pytesseract is None
    assert module.OpenAI is None


def test_build_metadata_payload_normalizes_and_validates_video_payload():
    metadata = build_metadata_payload(
        file_type="video",
        standard_date="2026-05-25",
        extracted_text="clip",
        is_scanned=False,
        preview_path=None,
        ocr_error=None,
        notes=["degraded: ffprobe unavailable"],
        video={"media_type": "video", "ffprobe_error": "ffprobe unavailable"},
    )

    assert metadata["file_type"] == "video"
    assert metadata["standard_date"] == "2026-05-25"
    assert metadata["video"]["ffprobe_error"] == "ffprobe unavailable"


def test_build_invalid_video_metadata_keeps_duplicate_safe_contract():
    metadata = build_invalid_video_metadata(
        file_type="video",
        standard_date=None,
        extracted_text="",
        is_scanned=False,
        preview_path=None,
        ocr_error=None,
        notes=["partial: invalid container"],
        video={"media_type": "video", "ffprobe_error": "invalid container"},
    )

    assert metadata["file_type"] == "video"
    assert metadata["video"]["media_type"] == "video"
    assert metadata["notes"] == ["partial: invalid container"]
