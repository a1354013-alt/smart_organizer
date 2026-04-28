from __future__ import annotations

import datetime
import hashlib
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from types import ModuleType
from typing import Any, Callable, Optional

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
exifread_module: Optional[ModuleType] = None
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

convert_from_path_fn: Optional[Callable[..., Any]] = None
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

# Video processing dependencies (optional, graceful degradation if missing)
FFMPEG_AVAILABLE = False
try:
    import subprocess

    _ffprobe_check = subprocess.run(
        ["ffprobe", "-version"],
        capture_output=True,
        timeout=5,
    )
    FFMPEG_AVAILABLE = _ffprobe_check.returncode == 0
except Exception:
    FFMPEG_AVAILABLE = False

logger = logging.getLogger(__name__)


class FileProcessor:
    def __init__(self):
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.openai_timeout_seconds = self._read_int_env(
            "OPENAI_TIMEOUT_SECONDS", 30, min_value=5, max_value=120
        )
        self.poppler_path = (os.getenv("POPPLER_PATH") or "").strip() or None
        self.pdf_preview_max_pages = self._read_int_env("PDF_PREVIEW_MAX_PAGES", 1, min_value=1, max_value=10)
        self.pdf_ocr_max_pages = self._read_int_env("PDF_OCR_MAX_PAGES", 3, min_value=1, max_value=10)

    def _read_int_env(self, key, default, min_value=None, max_value=None):
        raw = os.getenv(key, "")
        try:
            v = int(str(raw).strip())
        except Exception:
            v = int(default)
        if min_value is not None:
            v = max(int(min_value), v)
        if max_value is not None:
            v = min(int(max_value), v)
        return v

    def get_dependency_status(self):
        python_deps = {
            "PIL": Image is not None,
            "exifread": exifread_module is not None,
            "pypdf": PdfReader is not None,
            "pdf2image": convert_from_path_fn is not None,
            "pytesseract": pytesseract is not None,
            "openai": OpenAI is not None,
        }
        system_deps = {
            "ffmpeg": FFMPEG_AVAILABLE,
        }
        config = {
            "poppler_path": bool(self.poppler_path),
        }
        return {"python": python_deps, "system": system_deps, "config": config}

    def get_file_hash(self, file_path):
        if hasattr(file_path, "read"):
            data = file_path.read()
        else:
            with open(str(file_path), "rb") as f:
                data = f.read()
        return hashlib.sha256(data).hexdigest()


    def extract_metadata(self, file_path, options=None) -> ExtractedMetadata:
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
        preview_path = None
        ocr_error = None
        notes: list[str] = []
        video: VideoMetadata | None = None

        standard_date = self._get_file_mtime(file_path)

        file_size_bytes: int | None = None
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
                notes.append("?????????? metadata/?????????????????")
                video = {"media_type": "video"}  
            else:
                meta_timeout = int(options.get("video_metadata_timeout_seconds") or 10)
                thumb_timeout = int(options.get("video_thumbnail_timeout_seconds") or 10)

                started = time.perf_counter()
                video_meta = self._extract_video_metadata(file_path, timeout_seconds=meta_timeout)
                _record("video_metadata", started)
                video = video_meta

                started = time.perf_counter()
                thumb, thumb_error = self._generate_video_thumbnail(
                    file_path,
                    thumb_percent=0.5,
                    timeout_seconds=thumb_timeout,
                )
                _record("video_thumbnail", started)

                if thumb:
                    preview_path = thumb
                elif thumb_error and isinstance(video_meta, dict):
                    video_meta["thumbnail_error"] = thumb_error

        if file_type == "document" and ext == ".pdf":
            enable_pdf_preview = bool(options.get("enable_pdf_preview", False))
            enable_ocr = bool(options.get("enable_ocr", False))

            if not heavy_allowed:
                notes.append("檔案過大，已跳過 PDF 文字抽取 / 預覽 / OCR（可於側邊欄調整耗時處理上限）")
            else:
                text_timeout = int(options.get("pdf_text_timeout_seconds") or 10)
                text_pages = max(1, int(options.get("pdf_text_max_pages") or 3))

                started = time.perf_counter()
                ok, text_value, err = self._extract_pdf_text_with_timeout(
                    file_path,
                    max_pages=int(text_pages),
                    timeout_seconds=text_timeout,
                )
                _record("pdf_text", started)

                if ok and isinstance(text_value, str):
                    extracted_text = text_value
                elif err == "timeout":
                    notes.append("PDF 文字抽取逾時，已跳過")
                else:
                    notes.append(f"PDF 文字抽取失敗，已跳過（{err or 'unknown'}）")

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
                        notes.append("PDF 預覽產生失敗或逾時，已跳過")
                else:
                    notes.append("PDF 預覽已停用（預設）")

                if enable_ocr:
                    ocr_timeout = int(options.get("ocr_timeout_seconds") or 15)
                    ocr_pages = max(1, int(options.get("pdf_ocr_max_pages") or self.pdf_ocr_max_pages))
                    started = time.perf_counter()
                    ocr_text, ocr_err = self._ocr_pdf_sample(
                        file_path,
                        max_pages=ocr_pages,
                        timeout_seconds=ocr_timeout,
                    )
                    _record("ocr_pdf", started)

                    if ocr_text and len(ocr_text.strip()) > 10:
                        is_scanned = True
                        extracted_text = (extracted_text + "\\n" + ocr_text).strip()
                    elif ocr_err:
                        ocr_error = ocr_err
                        notes.append(f"OCR 失敗或逾時，已跳過（{ocr_err}）")
                else:
                    notes.append("OCR 已停用")
                    ocr_error = "OCR 已停用（設定）。"
                    if not (extracted_text or "").strip():
                        is_scanned = True

        if file_type == "photo" and options.get("enable_ocr", False):
            try:
                extracted_text = self._ocr_image(file_path) or extracted_text
            except Exception as e:
                ocr_error = str(e)
        elif file_type == "photo" and not options.get("enable_ocr", False):
            notes.append("OCR 已停用")

        metadata: ExtractedMetadata = {
            "file_type": file_type,
            "standard_date": FileUtils.normalize_standard_date(standard_date),
            "extracted_text": extracted_text or "",
            "is_scanned": bool(is_scanned),
            "preview_path": preview_path,
            "ocr_error": ocr_error,
            "notes": notes,
        }
        if video is not None:
            metadata["video"] = video
        return validate_extracted_metadata(metadata)

    def _ocr_image(self, image_path):
        if pytesseract is None or Image is None:
            return ""
        try:
            img = Image.open(image_path)
            return pytesseract.image_to_string(img, lang=os.getenv("TESSERACT_LANG", "chi_tra+eng")) or ""
        except Exception as e:
            logger.error(f"OCR 圖片失敗: {e}")
            return ""


    def _generate_pdf_preview(self, file_path, max_pages=1, timeout_seconds: int = 10):
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
        except Exception as e:
            logger.error("PDF preview failed: %s", e)
            return None


    def _get_photo_date(self, file_path):
        try:
            if exifread_module is None:
                return None
            with open(file_path, "rb") as f:
                tags = exifread_module.process_file(f, stop_tag="DateTimeOriginal")
                if "EXIF DateTimeOriginal" in tags:
                    date_str = str(tags["EXIF DateTimeOriginal"])
                    return FileUtils.normalize_standard_date(date_str.split(" ")[0].replace(":", "-"))
        except Exception as e:
            logger.debug(f"EXIF 讀取失敗: {e}")
        return None

    def _get_file_mtime(self, file_path):
        try:
            mtime = os.path.getmtime(file_path)
            return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        except Exception as e:
            logger.error(f"獲取修改時間失敗: {e}")
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

        if not FFMPEG_AVAILABLE:
            result["ffprobe_error"] = "ffprobe 不可用，無法解析影片 metadata"
            return result

        try:
            import json
            import subprocess

            try:
                result["file_size"] = os.path.getsize(file_path)
            except Exception:
                pass

            try:
                mtime = os.path.getmtime(file_path)
                result["modified_at"] = datetime.datetime.fromtimestamp(mtime).isoformat()
            except Exception:
                pass

            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                file_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=max(1, int(timeout_seconds or 10)))
            if proc.returncode != 0:
                result["ffprobe_error"] = (proc.stderr.decode("utf-8", errors="ignore") or "").strip() or "ffprobe failed"
                return result

            data = json.loads(proc.stdout.decode("utf-8", errors="ignore") or "{}")
            fmt = data.get("format") or {}
            streams = data.get("streams") or []

            try:
                dur = fmt.get("duration")
                if dur is not None:
                    result["duration_seconds"] = float(dur)
            except Exception:
                pass

            vstream = None
            for s in streams:
                if (s.get("codec_type") or "") == "video":
                    vstream = s
                    break
            if vstream:
                result["width"] = vstream.get("width")
                result["height"] = vstream.get("height")
                result["video_codec"] = vstream.get("codec_name")
                try:
                    fr = vstream.get("r_frame_rate") or ""
                    if isinstance(fr, str) and "/" in fr:
                        a, b = fr.split("/", 1)
                        result["fps"] = float(a) / float(b) if float(b) else None
                except Exception:
                    pass
            return result
        except Exception as e:
            result["ffprobe_error"] = str(e)
            return result

    def _generate_video_thumbnail(self, file_path: str, thumb_percent: float = 0.5, timeout_seconds: int = 10) -> tuple[str | None, str | None]:
        if not FFMPEG_AVAILABLE:
            return None, "ffmpeg 不可用，無法產生影片縮圖"
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
            proc = subprocess.run(cmd, capture_output=True, timeout=max(1, int(timeout_seconds or 10)))
            if os.path.exists(preview_path):
                return preview_path, None

            stderr = (proc.stderr.decode("utf-8", errors="ignore") or "").strip()
            if stderr:
                return None, stderr[:200]
            return None, "縮圖產生失敗（ffmpeg 未輸出錯誤訊息）"
        except Exception as e:
            return None, str(e)[:200]

    def _extract_pdf_text_with_timeout(
        self,
        file_path: str,
        *,
        max_pages: int,
        timeout_seconds: int,
    ) -> tuple[bool, str | None, str | None]:
        if PdfReader is None:
            return True, "", None

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._extract_pdf_text, file_path, max_pages=max_pages)
        try:
            value = future.result(timeout=max(1, int(timeout_seconds or 1)))
            return True, str(value or ""), None
        except FutureTimeoutError:
            return False, None, "timeout"
        except Exception as e:
            return False, None, f"{type(e).__name__}: {e}"
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _extract_pdf_text(self, file_path, max_pages=None):
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(file_path)
            texts = []
            pages = reader.pages
            if max_pages:
                pages = pages[: int(max_pages)]
            for p in pages:
                try:
                    t = p.extract_text()
                except Exception:
                    t = None
                if t:
                    texts.append(t)
            return "\n".join(texts)
        except Exception as e:
            logger.error(f"PDF 文字擷取失敗: {e}")
            return ""


    def _ocr_pdf_sample(self, file_path, max_pages=3, timeout_seconds: int = 15) -> tuple[str, str | None]:
        if convert_from_path_fn is None or pytesseract is None:
            return "", "dependencies_missing"
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
            for img in images:
                try:
                    remaining = max(1, int(deadline - time.perf_counter()))
                    parts.append(
                        pytesseract.image_to_string(
                            img,
                            lang=os.getenv("TESSERACT_LANG", "chi_tra+eng"),
                            timeout=remaining,
                        )
                    )
                except Exception:
                    continue
            return "\\n".join([p for p in parts if p]), None
        except Exception as e:
            logger.error("PDF OCR failed: %s", e)
            return "", str(e)[:200]


    def get_llm_summary(self, text, file_type, enabled=False):
        note = None
        if not enabled:
            return None, []
        if OpenAI is None:
            return "OpenAI SDK 不可用，請確認 requirements 與環境。", []

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return "未設定 OPENAI_API_KEY，AI 功能未啟用。", []

        max_chars = int(os.getenv("LLM_TRUNCATE_CHARS") or FileUtils.DEFAULT_LLM_TRUNCATE_CHARS)
        truncated, was_truncated = FileUtils.truncate_text(text, max_chars)
        if was_truncated:
            note = f"（已截斷內容至 {max_chars} 字元）"

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
        except Exception:
            logger.error("LLM 摘要呼叫失敗", exc_info=True)
            return "AI 摘要暫時不可用，請稍後再試。", []

        try:
            import json

            result = json.loads(content)
            summary = str(result.get("summary", "")).strip() or "（AI 未提供摘要）"
            tags = result.get("tags", []) or []
            if not isinstance(tags, list):
                tags = []
            tags = [str(t).strip() for t in tags if str(t).strip()][:10]
            if note and summary and note not in summary:
                summary = f"{summary} {note}"
            return summary, tags
        except Exception:
            logger.warning("AI 回應 JSON 解析失敗（已改用保守提示）", exc_info=True)
            msg = "AI 回應格式異常（JSON 解析失敗），請稍後再試。"
            if note:
                msg = f"{msg} {note}"
            return msg, []

    def classify_multi_tag(self, metadata, original_name, return_reason=False):
        return _classify_multi_tag(metadata, original_name, return_reason=return_reason)

    def sync_manual_topic(self, main_topic, tag_scores, file_type):
        return _sync_manual_topic(main_topic, tag_scores, file_type)
