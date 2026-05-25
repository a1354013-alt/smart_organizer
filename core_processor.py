from __future__ import annotations

import datetime
import hashlib
import logging
import os
import subprocess
import time
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from contracts import ExtractedMetadata, FileType, VideoMetadata
from core_classification import classify_multi_tag as _classify_multi_tag
from core_classification import sync_manual_topic as _sync_manual_topic
from core_utils import FileUtils
from processors.dependency_status import build_dependency_status
from processors.image_processor import get_photo_date, ocr_image
from processors.llm_summary import generate_llm_summary
from processors.metadata_contract import build_invalid_video_metadata, build_metadata_payload
from processors.optional_deps import (
    Image,
    OpenAI,
    PdfReader,
    convert_from_path_fn,
    exifread_module,
    pytesseract,
)
from processors.pdf_processor import (
    extract_pdf_text,
    extract_pdf_text_with_timeout,
    generate_pdf_preview,
    ocr_pdf_sample,
)
from processors.video_processor import (
    detect_ffmpeg_available,
    extract_video_metadata,
    generate_video_thumbnail,
    sniff_video_container,
)

logger = logging.getLogger(__name__)


def _warning_note(kind: str, message: str) -> str:
    return f"{kind}: {message}"


def _parse_int_env(value: object, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = int(default)
    if min_value is not None:
        parsed = max(int(min_value), parsed)
    if max_value is not None:
        parsed = min(int(max_value), parsed)
    return parsed


def _read_int_env(key: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    return _parse_int_env(os.getenv(key, ""), default, min_value=min_value, max_value=max_value)


VIDEO_TOOL_TIMEOUT_SECONDS = _read_int_env("VIDEO_TOOL_TIMEOUT_SECONDS", 10, min_value=1)


def _run_video_subprocess(cmd: list[str], *, timeout_seconds: int | None = None) -> Any:
    timeout = max(1, int(timeout_seconds or VIDEO_TOOL_TIMEOUT_SECONDS))
    return subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)


def _sniff_video_container(file_path: str, *, max_bytes: int = 4096) -> tuple[bool, str | None]:
    return sniff_video_container(file_path, max_bytes=max_bytes)


def _detect_ffmpeg_available() -> bool:
    return detect_ffmpeg_available(
        run_video_subprocess=lambda cmd: _run_video_subprocess(cmd, timeout_seconds=VIDEO_TOOL_TIMEOUT_SECONDS)
    )


FFMPEG_AVAILABLE: bool | None = None


def get_ffmpeg_available(*, refresh: bool = False) -> bool:
    global FFMPEG_AVAILABLE

    if refresh or FFMPEG_AVAILABLE is None:
        FFMPEG_AVAILABLE = _detect_ffmpeg_available()
    return bool(FFMPEG_AVAILABLE)

@lru_cache(maxsize=1)
def is_ffmpeg_available() -> bool:
    return _detect_ffmpeg_available()


class FileProcessor:
    def __init__(self) -> None:
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.openai_timeout_seconds = self._read_int_env("OPENAI_TIMEOUT_SECONDS", 30, min_value=5, max_value=120)
        self.poppler_path = (os.getenv("POPPLER_PATH") or "").strip() or None
        self.pdf_preview_max_pages = self._read_int_env("PDF_PREVIEW_MAX_PAGES", 1, min_value=1, max_value=10)
        self.pdf_ocr_max_pages = self._read_int_env("PDF_OCR_MAX_PAGES", 3, min_value=1, max_value=10)
        self.video_tool_timeout_seconds = self._read_int_env(
            "VIDEO_TOOL_TIMEOUT_SECONDS",
            VIDEO_TOOL_TIMEOUT_SECONDS,
            min_value=1,
            max_value=10,
        )

    def _read_int_env(
        self,
        key: str,
        default: int,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int:
        return _read_int_env(key, int(default), min_value=min_value, max_value=max_value)

    def get_dependency_status(self) -> dict[str, dict[str, bool]]:
        return build_dependency_status(
            image=Image,
            exifread_module=exifread_module,
            pdf_reader=PdfReader,
            convert_from_path_fn=convert_from_path_fn,
            pytesseract=pytesseract,
            openai_client=OpenAI,
            ffmpeg_available=get_ffmpeg_available(),
            poppler_path=self.poppler_path,
        )

    def get_file_hash(self, file_path: str | os.PathLike[str] | Any) -> str:
        if hasattr(file_path, "read"):
            data = file_path.read()
        else:
            with open(str(file_path), "rb") as handle:
                data = handle.read()
        return hashlib.sha256(data).hexdigest()

    def extract_metadata(
        self,
        file_path: str | os.PathLike[str],
        options: Mapping[str, Any] | None = None,
    ) -> ExtractedMetadata:
        options = options or {}
        file_path = str(file_path)
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()

        timings = options.get("_timings")
        if not isinstance(timings, dict):
            timings = None

        def _record(step: str, started_at: float) -> None:
            if timings is None:
                return
            timings[step] = round(time.perf_counter() - started_at, 4)

        file_type: FileType = "document"
        if ext in {".jpg", ".jpeg", ".png"}:
            file_type = "photo"
        elif ext in FileUtils.VIDEO_EXTENSIONS:
            file_type = "video"
        elif ext == ".pdf":
            file_type = "document"
        else:
            file_type = "unknown"

        extracted_text = ""
        is_scanned = False
        preview_path: str | None = None
        ocr_error: str | None = None
        notes: list[str] = []
        video: VideoMetadata | None = None

        standard_date = self._get_file_mtime(file_path)
        file_size_bytes: int | None
        try:
            file_size_bytes = int(os.path.getsize(file_path))
        except OSError:
            file_size_bytes = None

        max_heavy_bytes_raw = options.get("max_heavy_bytes")
        heavy_allowed = True
        if max_heavy_bytes_raw is not None and file_size_bytes is not None:
            try:
                heavy_allowed = file_size_bytes <= int(max_heavy_bytes_raw)
            except (TypeError, ValueError):
                heavy_allowed = True

        if file_type == "photo":
            preview_path = file_path
            photo_date = self._get_photo_date(file_path)
            if photo_date:
                standard_date = photo_date

        if file_type == "video":
            if not heavy_allowed:
                notes.append(_warning_note("partial", "Video metadata and thumbnail were skipped because the file exceeds the heavy-file limit."))
                video = {"media_type": "video"}
            else:
                container_ok, container_error = _sniff_video_container(file_path)
                if not container_ok:
                    video = {
                        "media_type": "video",
                        "file_size": file_size_bytes,
                        "ffprobe_error": container_error,
                    }
                    notes.append(_warning_note("partial", str(container_error or "video container validation failed")))
                    notes.append(_warning_note("degraded", str(container_error or "video container validation failed")))
                    return build_invalid_video_metadata(
                        file_type=file_type,
                        standard_date=standard_date,
                        extracted_text=extracted_text,
                        is_scanned=is_scanned,
                        preview_path=preview_path,
                        ocr_error=ocr_error,
                        notes=notes,
                        video=video,
                    )
                meta_timeout = int(options.get("video_metadata_timeout_seconds") or self.video_tool_timeout_seconds)
                thumb_timeout = int(options.get("video_thumbnail_timeout_seconds") or self.video_tool_timeout_seconds)

                started = time.perf_counter()
                video_meta = self._extract_video_metadata(file_path, timeout_seconds=meta_timeout)
                _record("video_metadata", started)
                video = video_meta

                started = time.perf_counter()
                thumb, thumb_error = self._generate_video_thumbnail(file_path, thumb_percent=0.5, timeout_seconds=thumb_timeout)
                _record("video_thumbnail", started)
                if thumb:
                    preview_path = thumb
                elif thumb_error:
                    video_meta["thumbnail_error"] = thumb_error
                    notes.append(_warning_note("degraded", thumb_error))

                ffprobe_error = video_meta.get("ffprobe_error")
                if ffprobe_error:
                    notes.append(_warning_note("degraded", str(ffprobe_error)))

        if file_type == "document" and ext == ".pdf":
            enable_pdf_preview = bool(options.get("enable_pdf_preview", False))
            enable_ocr = bool(options.get("enable_ocr", False))

            if not heavy_allowed:
                notes.append(
                    _warning_note(
                        "partial",
                        "PDF text extraction, preview generation, and OCR were skipped because the file exceeds the heavy-file limit.",
                    )
                )
            else:
                text_timeout = int(options.get("pdf_text_timeout_seconds") or 10)
                text_pages = max(1, int(options.get("pdf_text_max_pages") or 3))

                started = time.perf_counter()
                ok, text_value, err = self._extract_pdf_text_with_timeout(
                    file_path,
                    max_pages=text_pages,
                    timeout_seconds=text_timeout,
                )
                _record("pdf_text", started)
                if ok and isinstance(text_value, str):
                    extracted_text = text_value
                elif err == "timeout":
                    notes.append(_warning_note("timeout", "PDF text extraction timed out."))
                else:
                    notes.append(_warning_note("degraded", f"PDF text extraction failed: {err or 'unknown'}"))

                if enable_pdf_preview:
                    preview_timeout = int(options.get("pdf_preview_timeout_seconds") or 10)
                    preview_pages = max(1, int(options.get("pdf_preview_max_pages") or 1))
                    started = time.perf_counter()
                    preview_path = self._generate_pdf_preview(
                        file_path,
                        max_pages=preview_pages,
                        timeout_seconds=preview_timeout,
                    )
                    _record("pdf_preview", started)
                    if not preview_path:
                        notes.append(_warning_note("degraded", "PDF preview generation failed or timed out."))
                else:
                    notes.append("PDF preview generation is disabled.")

                if enable_ocr:
                    ocr_timeout = int(options.get("ocr_timeout_seconds") or 15)
                    ocr_pages = max(1, int(options.get("pdf_ocr_max_pages") or self.pdf_ocr_max_pages))
                    started = time.perf_counter()
                    ocr_text, ocr_err = self._ocr_pdf_sample(file_path, max_pages=ocr_pages, timeout_seconds=ocr_timeout)
                    _record("ocr_pdf", started)
                    if ocr_text and len(ocr_text.strip()) > 10:
                        is_scanned = True
                        extracted_text = (extracted_text + "\n" + ocr_text).strip()
                    elif ocr_err:
                        ocr_error = ocr_err
                        notes.append(_warning_note("degraded", f"PDF OCR failed: {ocr_err}"))
                else:
                    notes.append("OCR is disabled.")
                    ocr_error = "OCR is disabled."
                    if not extracted_text.strip():
                        is_scanned = True

        if file_type == "photo" and bool(options.get("enable_ocr", False)):
            try:
                extracted_text = self._ocr_image(file_path) or extracted_text
            except (OSError, RuntimeError, ValueError) as exc:
                ocr_error = str(exc)
        elif file_type == "photo":
            notes.append("OCR is disabled.")

        return build_metadata_payload(
            file_type=file_type,
            standard_date=standard_date,
            extracted_text=extracted_text,
            is_scanned=is_scanned,
            preview_path=preview_path,
            ocr_error=ocr_error,
            notes=notes,
            video=video,
        )

    def _ocr_image(self, file_path: str) -> str:
        return ocr_image(file_path, image_module=Image, pytesseract_module=pytesseract)

    def _generate_pdf_preview(
        self,
        file_path: str,
        max_pages: int = 1,
        timeout_seconds: int = 10,
    ) -> str | None:
        return generate_pdf_preview(
            file_path,
            convert_from_path_fn=convert_from_path_fn,
            poppler_path=self.poppler_path,
            max_pages=max_pages,
            timeout_seconds=timeout_seconds,
        )

    def _get_photo_date(self, file_path: str) -> str | None:
        return get_photo_date(file_path, exifread_module=exifread_module)

    def _get_file_mtime(self, file_path: str) -> str:
        try:
            mtime = os.path.getmtime(file_path)
            return datetime.datetime.fromtimestamp(mtime, tz=datetime.UTC).date().isoformat()
        except OSError as exc:
            logger.error("File mtime read failed: %s", exc)
            return datetime.datetime.now(datetime.UTC).date().isoformat()

    def _extract_video_metadata(self, file_path: str, timeout_seconds: int = 10) -> VideoMetadata:
        return extract_video_metadata(
            file_path,
            ffmpeg_available=is_ffmpeg_available(),
            timeout_seconds=timeout_seconds,
            run_video_subprocess=lambda cmd, timeout: _run_video_subprocess(cmd, timeout_seconds=timeout),
        )

    def _generate_video_thumbnail(self, file_path: str, thumb_percent: float = 0.5, timeout_seconds: int = 10) -> tuple[str | None, str | None]:
        return generate_video_thumbnail(
            file_path,
            ffmpeg_available=is_ffmpeg_available(),
            timeout_seconds=timeout_seconds,
            thumb_percent=thumb_percent,
        )

    def _extract_pdf_text_with_timeout(self, file_path: str, *, max_pages: int, timeout_seconds: int) -> tuple[bool, str | None, str | None]:
        return extract_pdf_text_with_timeout(
            file_path,
            pdf_reader=PdfReader,
            max_pages=max_pages,
            timeout_seconds=timeout_seconds,
        )

    def _extract_pdf_text(self, file_path: str, max_pages: int | None = None) -> str:
        return extract_pdf_text(file_path, pdf_reader=PdfReader, max_pages=max_pages)

    def _ocr_pdf_sample(
        self,
        file_path: str,
        max_pages: int = 3,
        timeout_seconds: int = 15,
    ) -> tuple[str, str | None]:
        return ocr_pdf_sample(
            file_path,
            convert_from_path_fn=convert_from_path_fn,
            pytesseract_module=pytesseract,
            poppler_path=self.poppler_path,
            max_pages=max_pages,
            timeout_seconds=timeout_seconds,
        )

    def get_llm_summary(self, text: str, file_type: str, enabled: bool = False) -> tuple[str | None, list[str]]:
        return generate_llm_summary(
            text,
            file_type=file_type,
            enabled=enabled,
            openai_client_class=OpenAI,
            model=self.model,
            timeout_seconds=self.openai_timeout_seconds,
        )

    def classify_multi_tag(
        self,
        metadata: Mapping[str, Any],
        original_name: object,
        return_reason: bool = False,
    ) -> Any:
        return _classify_multi_tag(dict(metadata), str(original_name), return_reason=return_reason)

    def sync_manual_topic(
        self,
        main_topic: str,
        tag_scores: dict[str, float] | None,
        file_type: str,
    ) -> Any:
        return _sync_manual_topic(main_topic, tag_scores, file_type)
