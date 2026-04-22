from __future__ import annotations

import datetime
import hashlib
import logging
import os
from types import ModuleType
from typing import Any, Callable, Optional

from contracts import ExtractedMetadata, FileType
from core_classification import classify_multi_tag as _classify_multi_tag
from core_classification import sync_manual_topic as _sync_manual_topic
from core_utils import FileUtils

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

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

try:
    import pytesseract
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
        status = {
            "PIL": Image is not None,
            "exifread": exifread_module is not None,
            "pypdf": PdfReader is not None,
            "pdf2image": convert_from_path_fn is not None,
            "pytesseract": pytesseract is not None,
            "openai": OpenAI is not None,
            "ffmpeg": FFMPEG_AVAILABLE,
        }
        status["poppler_path"] = bool(self.poppler_path)
        return status

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

        standard_date = self._get_file_mtime(file_path)

        if file_type == "photo":
            # For photos we always have a "preview" (the file itself).
            preview_path = file_path
            photo_date = self._get_photo_date(file_path)
            if photo_date:
                standard_date = photo_date

        if file_type == "video":
            video_meta = self._extract_video_metadata(file_path)
            if isinstance(video_meta, dict):
                notes.append("video_phase1")
            thumb = self._generate_video_thumbnail(file_path, thumb_percent=0.5)
            if thumb:
                preview_path = thumb

        if file_type == "document" and ext == ".pdf":
            try:
                extracted_text = self._extract_pdf_text(file_path, max_pages=int(options.get("pdf_text_max_pages") or 10))
            except Exception as e:
                logger.error("PDF 文字擷取失敗: %s", e)
                extracted_text = ""

            if options.get("enable_pdf_preview", True):
                preview_path = self._generate_pdf_preview(file_path, max_pages=int(options.get("pdf_preview_max_pages") or 1))
            else:
                notes.append("PDF 預覽已停用")

            if options.get("enable_ocr", False):
                try:
                    ocr_text = self._ocr_pdf_sample(file_path, max_pages=int(options.get("pdf_ocr_max_pages") or self.pdf_ocr_max_pages))
                    if ocr_text and len(ocr_text.strip()) > 10:
                        is_scanned = True
                        extracted_text = (extracted_text + "\n" + ocr_text).strip()
                except Exception as e:
                    ocr_error = str(e)
            else:
                # Compatibility: when OCR is disabled and extracted text is empty, mark as scanned.
                if not (extracted_text or "").strip():
                    is_scanned = True
                ocr_error = "OCR 已停用（設定）。"
                notes.append("OCR 已停用")

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
        return metadata

    def _ocr_image(self, image_path):
        if pytesseract is None or Image is None:
            return ""
        try:
            img = Image.open(image_path)
            return pytesseract.image_to_string(img, lang=os.getenv("TESSERACT_LANG", "chi_tra+eng")) or ""
        except Exception as e:
            logger.error(f"OCR 圖片失敗: {e}")
            return ""

    def _generate_pdf_preview(self, file_path, max_pages=1):
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
                )
                if images:
                    images[0].save(preview_path, "PNG")
            return preview_path
        except Exception as e:
            logger.error(f"PDF 預覽圖產生失敗: {e}")
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

    def _extract_video_metadata(self, file_path):
        result = {
            "media_type": "video",
            "duration_seconds": None,
            "width": None,
            "height": None,
            "fps": None,
            "video_codec": None,
            "file_size": None,
            "created_at": None,
            "modified_at": None,
        }

        if not FFMPEG_AVAILABLE:
            result["error"] = "ffprobe 不可用，無法解析影片 metadata"
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
            proc = subprocess.run(cmd, capture_output=True, timeout=10)
            if proc.returncode != 0:
                result["error"] = (proc.stderr.decode("utf-8", errors="ignore") or "").strip() or "ffprobe failed"
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
            result["error"] = str(e)
            return result

    def _generate_video_thumbnail(self, file_path, thumb_percent=0.5):
        if not FFMPEG_AVAILABLE:
            return None
        try:
            import subprocess

            preview_path = FileUtils.build_preview_path(file_path)
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
                preview_path,
            ]
            subprocess.run(cmd, capture_output=True, timeout=10)
            if os.path.exists(preview_path):
                return preview_path
            return None
        except Exception:
            return None

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

    def _ocr_pdf_sample(self, file_path, max_pages=3):
        if convert_from_path_fn is None or pytesseract is None:
            return ""
        try:
            images = convert_from_path_fn(
                file_path,
                first_page=1,
                last_page=max(1, int(max_pages or 1)),
                poppler_path=self.poppler_path,
            )
            parts = []
            for img in images:
                try:
                    parts.append(pytesseract.image_to_string(img, lang=os.getenv("TESSERACT_LANG", "chi_tra+eng")))
                except Exception:
                    continue
            return "\n".join([p for p in parts if p])
        except Exception as e:
            logger.error(f"PDF OCR 失敗: {e}")
            return ""

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
