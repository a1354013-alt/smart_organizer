from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from core_utils import FileUtils

logger = logging.getLogger(__name__)


def generate_pdf_preview(
    file_path: str,
    *,
    convert_from_path_fn: Callable[..., Any] | None,
    poppler_path: str | None,
    max_pages: int = 1,
    timeout_seconds: int = 10,
) -> str | None:
    if convert_from_path_fn is None:
        return None
    try:
        preview_path = FileUtils.build_preview_path(file_path)
        os.makedirs(os.path.dirname(preview_path), exist_ok=True)
        if not os.path.exists(preview_path):
            images = convert_from_path_fn(
                file_path,
                first_page=1,
                last_page=max(1, int(max_pages or 1)),
                poppler_path=poppler_path,
                timeout=int(timeout_seconds or 0) or None,
            )
            if images:
                images[0].save(preview_path, "PNG")
        return preview_path
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("PDF preview failed: %s", exc)
        return None


def extract_pdf_text_with_timeout(
    file_path: str,
    *,
    pdf_reader: Any,
    max_pages: int,
    timeout_seconds: int,
) -> tuple[bool, str | None, str | None]:
    if pdf_reader is None:
        return True, "", None
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(extract_pdf_text, file_path, pdf_reader=pdf_reader, max_pages=max_pages)
    try:
        value = future.result(timeout=max(1, int(timeout_seconds or 1)))
        return True, str(value or ""), None
    except FutureTimeoutError:
        return False, None, "timeout"
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def extract_pdf_text(file_path: str, *, pdf_reader: Any, max_pages: int | None = None) -> str:
    if pdf_reader is None:
        return ""
    try:
        reader = pdf_reader(file_path)
        pages = reader.pages[: int(max_pages)] if max_pages else reader.pages
        texts: list[str] = []
        for page in pages:
            try:
                text = page.extract_text()
            except Exception:
                text = None
            if text:
                texts.append(text)
        return "\n".join(texts)
    except Exception as exc:
        logger.error("PDF text extraction failed: %s", exc)
        return ""


def ocr_pdf_sample(
    file_path: str,
    *,
    convert_from_path_fn: Callable[..., Any] | None,
    pytesseract_module: Any,
    poppler_path: str | None,
    max_pages: int = 3,
    timeout_seconds: int = 15,
) -> tuple[str, str | None]:
    if convert_from_path_fn is None or pytesseract_module is None:
        return "", "dependencies_missing: pdf2image/poppler or tesseract is unavailable"
    try:
        deadline = time.perf_counter() + max(1.0, float(timeout_seconds or 15))
        images = convert_from_path_fn(
            file_path,
            first_page=1,
            last_page=max(1, int(max_pages or 1)),
            poppler_path=poppler_path,
            timeout=max(1, int(timeout_seconds or 15)),
        )
        parts: list[str] = []
        for image in images:
            try:
                remaining = max(1, int(deadline - time.perf_counter()))
                parts.append(
                    pytesseract_module.image_to_string(
                        image,
                        lang=os.getenv("TESSERACT_LANG", "chi_tra+eng"),
                        timeout=remaining,
                    )
                )
            except Exception:
                continue
        return "\n".join([part for part in parts if part]), None
    except Exception as exc:
        logger.error("PDF OCR failed: %s", exc)
        return "", str(exc)[:200]
