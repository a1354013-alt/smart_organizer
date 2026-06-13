from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any

Image: Any = None
try:
    from PIL import Image as _Image

    Image = _Image
except Exception:  # pragma: no cover
    Image = None

exifread_module: ModuleType | None = None
try:
    import exifread as _exifread

    exifread_module = _exifread
except Exception:  # pragma: no cover
    exifread_module = None

PdfReader: Any = None
try:
    from pypdf import PdfReader as _PdfReader

    PdfReader = _PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

convert_from_path_fn: Callable[..., Any] | None = None
try:
    from pdf2image import convert_from_path as _convert_from_path

    convert_from_path_fn = _convert_from_path
except Exception:  # pragma: no cover
    convert_from_path_fn = None

pytesseract: Any = None
try:
    import pytesseract as _pytesseract

    pytesseract = _pytesseract
except Exception:  # pragma: no cover
    pytesseract = None

OpenAI: Any = None
try:
    from openai import OpenAI as _OpenAI

    OpenAI = _OpenAI
except Exception:  # pragma: no cover
    OpenAI = None
