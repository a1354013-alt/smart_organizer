from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from contracts import OCRStatus
from core_utils import FileUtils

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OCRImageResult:
    text: str
    status: OCRStatus
    error: str | None = None


def get_photo_date(file_path: str, *, exifread_module: Any) -> str | None:
    try:
        if exifread_module is None:
            return None
        with open(file_path, "rb") as handle:
            tags = exifread_module.process_file(handle, stop_tag="DateTimeOriginal")
            if "EXIF DateTimeOriginal" in tags:
                date_str = str(tags["EXIF DateTimeOriginal"])
                return FileUtils.normalize_standard_date(date_str.split(" ")[0].replace(":", "-"))
    except (OSError, ValueError, AttributeError) as exc:
        logger.debug("EXIF date read failed: %s", exc)
    return None


def ocr_image(file_path: str, *, image_module: Any, pytesseract_module: Any) -> OCRImageResult:
    if pytesseract_module is None or image_module is None:
        return OCRImageResult(text="", status="unavailable", error="OCR dependencies are unavailable.")
    try:
        image = image_module.open(file_path)
        text = pytesseract_module.image_to_string(image, lang=os.getenv("TESSERACT_LANG", "chi_tra+eng")) or ""
        if text.strip():
            return OCRImageResult(text=text, status="success", error=None)
        return OCRImageResult(text="", status="empty_text", error=None)
    except subprocess.TimeoutExpired as exc:
        logger.warning("Image OCR timed out: %s", exc)
        return OCRImageResult(text="", status="timeout", error="OCR timed out.")
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("Image OCR failed: %s", exc)
        return OCRImageResult(text="", status="failed", error=str(exc)[:200] or "OCR failed.")
