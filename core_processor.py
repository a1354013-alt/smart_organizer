from __future__ import annotations

import datetime
import hashlib
import logging
import os
import shutil
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import suppress
from functools import lru_cache
from types import ModuleType
from typing import Any

from contracts import ExtractedMetadata, FileType, VideoMetadata, validate_extracted_metadata
from core_classification import classify_multi_tag as _classify_multi_tag
from core_classification import sync_manual_topic as _sync_manual_topic
from core_utils import FileUtils

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
    import subprocess

    timeout = max(1, int(timeout_seconds or VIDEO_TOOL_TIMEOUT_SECONDS))
    return subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)


def _sniff_video_container(file_path: str, *, max_bytes: int = 4096) -> tuple[bool, str | None]:
    try:
        with open(file_path, "rb") as handle:
            header = handle.read(max(32, int(max_bytes)))
    except Exception as exc:
        return False, f"video container validation failed: {exc}"
    if len(header) < 12:
        return False, "video container validation failed: file is too small"
    if header.startswith(b"\x1aE\xdf\xa3"):
        return True, None
    if header.startswith(b"RIFF") and header[8:12] in {b"AVI ", b"WEBP"}:
        return True, None
    if header[4:8] == b"ftyp":
        return True, None
    if header.startswith(b"OggS"):
        return True, None
    return False, "video container validation failed: signature does not match a supported video container"


def _detect_ffmpeg_available() -> bool:
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        return False
    try:
        probe = _run_video_subprocess(["ffprobe", "-version"], timeout_seconds=VIDEO_TOOL_TIMEOUT_SECONDS)
        ffmpeg = _run_video_subprocess(["ffmpeg", "-version"], timeout_seconds=VIDEO_TOOL_TIMEOUT_SECONDS)
        return probe.returncode == 0 and ffmpeg.returncode == 0
    except Exception:
        return False


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
        python_deps = {
            "PIL": Image is not None,
            "exifread": exifread_module is not None,
            "pypdf": PdfReader is not None,
            "pdf2image": convert_from_path_fn is not None,
            "pytesseract": pytesseract is not None,
            "openai": OpenAI is not None,
        }
        system_deps = {
            "ffmpeg": get_ffmpeg_available(),
        }
        config = {
            "poppler_path": bool(self.poppler_path),
        }
        return {"python": python_deps, "system": system_deps, "config": config}

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
            try:
                timings[step] = round(time.perf_counter() - started_at, 4)
            except Exception:
                return

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
        except Exception:
            file_size_bytes = None

        max_heavy_bytes_raw = options.get("max_heavy_bytes")
        heavy_allowed = True
        if max_heavy_bytes_raw is not None and file_size_bytes is not None:
            try:
                heavy_allowed = file_size_bytes <= int(max_heavy_bytes_raw)
            except Exception:
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
                    invalid_video_metadata: ExtractedMetadata = {
                        "file_type": file_type,
                        "standard_date": FileUtils.normalize_standard_date(standard_date),
                        "extracted_text": extracted_text or "",
                        "is_scanned": bool(is_scanned),
                        "preview_path": preview_path,
                        "ocr_error": ocr_error,
                        "notes": notes,
                        "video": video,
                    }
                    return validate_extracted_metadata(invalid_video_metadata)
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
            except Exception as exc:
                ocr_error = str(exc)
        elif file_type == "photo":
            notes.append("OCR is disabled.")

        metadata: ExtractedMetadata = {
            "file_type": file_type,
            "standard_date": FileUtils.normalize_standard_date(standard_date),
            "extracted_text": extracted_text or "",
            "is_scanned": bool(is_scanned),
            "preview_path": preview_path,
            "ocr_error": ocr_error,
            "notes": notes,
        }
        if video:
            metadata["video"] = video
        return validate_extracted_metadata(metadata)

    def _ocr_image(self, file_path: str) -> str:
        if pytesseract is None or Image is None:
            return ""
        try:
            image = Image.open(file_path)
            return pytesseract.image_to_string(image, lang=os.getenv("TESSERACT_LANG", "chi_tra+eng")) or ""
        except Exception as exc:
            logger.error("Image OCR failed: %s", exc)
            return ""

    def _generate_pdf_preview(
        self,
        file_path: str,
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
                    poppler_path=self.poppler_path,
                    timeout=int(timeout_seconds or 0) or None,
                )
                if images:
                    images[0].save(preview_path, "PNG")
            return preview_path
        except Exception as exc:
            logger.error("PDF preview failed: %s", exc)
            return None

    def _get_photo_date(self, file_path: str) -> str | None:
        try:
            if exifread_module is None:
                return None
            with open(file_path, "rb") as handle:
                tags = exifread_module.process_file(handle, stop_tag="DateTimeOriginal")
                if "EXIF DateTimeOriginal" in tags:
                    date_str = str(tags["EXIF DateTimeOriginal"])
                    return FileUtils.normalize_standard_date(date_str.split(" ")[0].replace(":", "-"))
        except Exception as exc:
            logger.debug("EXIF date read failed: %s", exc)
        return None

    def _get_file_mtime(self, file_path: str) -> str:
        try:
            mtime = os.path.getmtime(file_path)
            return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        except Exception as exc:
            logger.error("File mtime read failed: %s", exc)
            return datetime.datetime.now().strftime("%Y-%m-%d")

    def _extract_video_metadata(self, file_path: str, timeout_seconds: int = 10) -> VideoMetadata:
        result: VideoMetadata = {
            "media_type": "video",
            "duration_seconds": None,
            "width": None,
            "height": None,
            "fps": None,
            "video_codec": None,
            "file_size": None,
            "created_at": None,
            "modified_at": None,
            "ffprobe_error": None,
        }

        if not is_ffmpeg_available():
            result["ffprobe_error"] = "ffprobe is unavailable; video metadata could not be collected."
            return result

        try:
            import json
            import subprocess

            with suppress(Exception):
                result["file_size"] = os.path.getsize(file_path)
            with suppress(Exception):
                mtime = os.path.getmtime(file_path)
                result["modified_at"] = datetime.datetime.fromtimestamp(mtime).isoformat()

            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", file_path]
            try:
                proc = _run_video_subprocess(cmd, timeout_seconds=timeout_seconds)
                if proc.returncode != 0:
                    result["ffprobe_error"] = (proc.stderr or "").strip() or "ffprobe failed"
                    return result

                data = json.loads(proc.stdout or "{}")
                fmt = data.get("format") or {}
                streams = data.get("streams") or []

                duration = fmt.get("duration")
                if duration is not None:
                    with suppress(Exception):
                        result["duration_seconds"] = float(duration)

                video_stream = next((stream for stream in streams if (stream.get("codec_type") or "") == "video"), None)
                if isinstance(video_stream, dict):
                    result["width"] = video_stream.get("width")
                    result["height"] = video_stream.get("height")
                    result["video_codec"] = video_stream.get("codec_name")
                    frame_rate = video_stream.get("r_frame_rate") or ""
                    if isinstance(frame_rate, str) and "/" in frame_rate:
                        try:
                            numerator, denominator = frame_rate.split("/", 1)
                            result["fps"] = float(numerator) / float(denominator) if float(denominator) else None
                        except Exception:
                            pass
            except subprocess.TimeoutExpired:
                result["ffprobe_error"] = f"ffprobe timed out after {timeout_seconds}s"
            except Exception as exc:
                result["ffprobe_error"] = f"ffprobe failed: {exc}"
        except Exception as exc:
            result["ffprobe_error"] = str(exc)
        return result

    def _generate_video_thumbnail(self, file_path: str, thumb_percent: float = 0.5, timeout_seconds: int = 10) -> tuple[str | None, str | None]:
        del thumb_percent  # Phase 1 keeps a fixed thumbnail extraction strategy.
        if not is_ffmpeg_available():
            return None, "ffmpeg is unavailable; thumbnail generation was skipped."
        try:
            import subprocess

            base_preview_path = FileUtils.build_preview_path(file_path)
            preview_path = os.path.splitext(base_preview_path)[0] + ".jpg"
            os.makedirs(os.path.dirname(preview_path), exist_ok=True)
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                file_path,
                "-vf",
                "thumbnail,scale=320:-1",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                preview_path,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=max(1, int(timeout_seconds or 10)), text=True)
                if os.path.exists(preview_path):
                    return preview_path, None
                stderr = (proc.stderr or "").strip()
                if stderr:
                    return None, stderr[:200]
                return None, "ffmpeg finished without creating a thumbnail."
            except subprocess.TimeoutExpired:
                return None, f"ffmpeg thumbnail generation timeout after {timeout_seconds}s"
            except Exception as exc:
                return None, f"ffmpeg failed: {str(exc)[:200]}"
        except Exception as exc:
            return None, str(exc)[:200]

    def _extract_pdf_text_with_timeout(self, file_path: str, *, max_pages: int, timeout_seconds: int) -> tuple[bool, str | None, str | None]:
        if PdfReader is None:
            return True, "", None
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._extract_pdf_text, file_path, max_pages=max_pages)
        try:
            value = future.result(timeout=max(1, int(timeout_seconds or 1)))
            return True, str(value or ""), None
        except FutureTimeoutError:
            return False, None, "timeout"
        except Exception as exc:
            return False, None, f"{type(exc).__name__}: {exc}"
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _extract_pdf_text(self, file_path: str, max_pages: int | None = None) -> str:
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(file_path)
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

    def _ocr_pdf_sample(
        self,
        file_path: str,
        max_pages: int = 3,
        timeout_seconds: int = 15,
    ) -> tuple[str, str | None]:
        if convert_from_path_fn is None or pytesseract is None:
            return "", "dependencies_missing: pdf2image/poppler or tesseract is unavailable"
        try:
            deadline = time.perf_counter() + max(1.0, float(timeout_seconds or 15))
            images = convert_from_path_fn(
                file_path,
                first_page=1,
                last_page=max(1, int(max_pages or 1)),
                poppler_path=self.poppler_path,
                timeout=max(1, int(timeout_seconds or 15)),
            )
            parts: list[str] = []
            for image in images:
                try:
                    remaining = max(1, int(deadline - time.perf_counter()))
                    parts.append(
                        pytesseract.image_to_string(
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

    def get_llm_summary(self, text: str, file_type: str, enabled: bool = False) -> tuple[str | None, list[str]]:
        note = None
        if not enabled:
            return None, []
        if OpenAI is None:
            return "OpenAI SDK is unavailable. Install the optional dependency to enable AI summaries.", []

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return "OPENAI_API_KEY is not configured, so AI summaries are disabled.", []

        max_chars = int(os.getenv("LLM_TRUNCATE_CHARS") or FileUtils.DEFAULT_LLM_TRUNCATE_CHARS)
        truncated, was_truncated = FileUtils.truncate_text(text, max_chars)
        if was_truncated:
            note = f"Input was truncated to {max_chars} characters before sending it to the AI service."

        try:
            import json

            client = OpenAI()
            system = (
                "You are a file organization assistant. Return STRICT JSON only with keys: "
                '{"summary": "...", "tags": ["..."]}. No markdown.'
            )
            user = (
                f"file_type={file_type}\n"
                "Please summarize the content in Traditional Chinese and suggest 3-10 tags.\n\n"
                f"{truncated}"
            )
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.2,
                timeout=self.openai_timeout_seconds,
            )
            content = (response.choices[0].message.content or "").strip()
            result = json.loads(content)
            summary = str(result.get("summary", "")).strip() or "AI returned an empty summary."
            tags = result.get("tags", []) or []
            if not isinstance(tags, list):
                tags = []
            normalized_tags = [str(tag).strip() for tag in tags if str(tag).strip()][:10]
            if note and note not in summary:
                summary = f"{summary} {note}"
            return summary, normalized_tags
        except Exception:
            logger.error("LLM summary generation failed", exc_info=True)
            message = "AI summary generation failed. Please review the logs for details."
            if note:
                message = f"{message} {note}"
            return message, []

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
