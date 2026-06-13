from __future__ import annotations

from typing import Any


def build_dependency_status(
    *,
    image: Any,
    exifread_module: Any,
    pdf_reader: Any,
    convert_from_path_fn: Any,
    pytesseract: Any,
    openai_client: Any,
    ffmpeg_available: bool,
    poppler_path: str | None,
) -> dict[str, dict[str, bool]]:
    python_deps = {
        "PIL": image is not None,
        "exifread": exifread_module is not None,
        "pypdf": pdf_reader is not None,
        "pdf2image": convert_from_path_fn is not None,
        "pytesseract": pytesseract is not None,
        "openai": openai_client is not None,
    }
    system_deps = {"ffmpeg": ffmpeg_available}
    config = {"poppler_path": bool(poppler_path)}
    return {"python": python_deps, "system": system_deps, "config": config}
