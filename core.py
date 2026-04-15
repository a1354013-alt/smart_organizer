import os
import re
import datetime
import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any
from contracts import ExtractedMetadata

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

try:
    import exifread
except Exception:  # pragma: no cover
    exifread = None  # type: ignore[assignment]

PdfReader: Any
try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

try:
    from pdf2image import convert_from_path
except Exception:  # pragma: no cover
    convert_from_path = None  # type: ignore[assignment]

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None

OpenAI: Any
try:
    from openai import OpenAI
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

# 設定 Logging
logger = logging.getLogger(__name__)

DOCUMENT_TAGS = ['發票', '合約', '報價', '請款', '證明文件', '會議紀錄', '掃描', '其他文件']
PHOTO_TAGS = ['人物', '美食', '旅行', '文件/收據', '工作', '截圖', '風景', '其他照片']
VIDEO_TAGS = ['Unclassified', 'Screen Recording', 'Tutorial', 'Meeting', 'Promo', 'Raw Footage', 'Animation']

# Video classification keywords (for batch scanning phase 2)
VIDEO_KEYWORD_RULES = {
    'Screen Recording': ['screen', 'record', 'screenshot', 'desktop', '螢幕', '錄製', '畫面'],
    'Tutorial': ['tutorial', 'howto', 'how-to', 'guide', '教學', '入門', '技巧', 'lesson'],
    'Meeting': ['meeting', 'conference', 'zoom', 'teams', 'hangout', '會議', '簡報', 'presentation'],
    'Promo': ['promo', 'trailer', 'teaser', 'advertisement', '廣告', '宣傳', '預告'],
    'Raw Footage': ['raw', 'footage', 'clip', 'rushes', '原始', '素材'],
    'Animation': ['animation', 'animated', 'cartoon', 'anime', '動畫', '動漫'],
}

class FileUtils:
    """純工具函式類別，不涉及業務邏輯與昂貴初始化"""
    DEFAULT_UNKNOWN_DATE = "UnknownDate"
    DEFAULT_UNKNOWN_YEAR = "UnknownYear"
    DEFAULT_UNKNOWN_MONTH = "UnknownMonth"
    ALLOWED_UPLOAD_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.mp4', '.mov', '.mkv'}
    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv'}
    DEFAULT_LLM_TRUNCATE_CHARS = 6000

    @staticmethod
    def truncate_text(text, max_chars):
        if text is None:
            return "", False
        s = str(text)
        if max_chars is None or int(max_chars) <= 0:
            return s, False
        max_chars = int(max_chars)
        if len(s) <= max_chars:
            return s, False
        return s[:max_chars], True

    @staticmethod
    def sanitize_filename(filename, max_length=200):
        # 先分離檔名與副檔名
        name, ext = os.path.splitext(filename)
        # 移除非法字元
        name = re.sub(r'[\\/*?:"<>|]', "", name)
        # 移除控制字元
        name = "".join(ch for ch in name if ord(ch) >= 32)
        # 移除路徑遍歷風險
        while ".." in name:
            name = name.replace("..", "")
        # 移除開頭或結尾的點
        name = name.strip(".")
        
        # 【邊界處理】若檔名被洗成空的，給予預設值
        if not name:
            name = "untitled_file"
            
        if len(name) > max_length:
            name = name[:max_length]
        return f"{name}{ext}"

    @staticmethod
    def get_unique_path(target_path):
        if not os.path.exists(target_path):
            return target_path
        base, ext = os.path.splitext(target_path)
        counter = 1
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        return f"{base}_{counter}{ext}"

    @staticmethod
    def escape_fts_query(query):
        """【FTS 安全化】轉義特殊字元並處理分詞"""
        if not query:
            return ""
        # 移除 FTS5 特殊語法字元，防止 SQL 報錯
        # 僅保留基本文字與空白
        clean_query = re.sub(r'[":\-*()]', " ", query)
        # 將輸入拆成多個詞並以空白連接，交由 FTS5 做多詞匹配 (空白在 FTS5 隱含 AND 行為)
        words = [f'"{w}"' for w in clean_query.split() if w]
        return " ".join(words)

    @staticmethod
    def normalize_standard_date(raw_value):
        if raw_value is None:
            return FileUtils.DEFAULT_UNKNOWN_DATE

        value = str(raw_value).strip()
        if not value or value == FileUtils.DEFAULT_UNKNOWN_DATE:
            return FileUtils.DEFAULT_UNKNOWN_DATE

        candidates = [value]
        trimmed = value.replace("T", " ").split(" ")[0]
        if trimmed != value:
            candidates.append(trimmed)

        normalized = re.sub(r"[./_]", "-", trimmed)
        if normalized != trimmed:
            candidates.append(normalized)

        for candidate in candidates:
            try:
                parsed = datetime.date.fromisoformat(candidate)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue

        match = re.fullmatch(r"(\d{4})[-/._](\d{1,2})[-/._](\d{1,2})", value)
        if match:
            try:
                parsed = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                return FileUtils.DEFAULT_UNKNOWN_DATE

        return FileUtils.DEFAULT_UNKNOWN_DATE

    @staticmethod
    def get_date_directory_parts(raw_value):
        normalized = FileUtils.normalize_standard_date(raw_value)
        if normalized == FileUtils.DEFAULT_UNKNOWN_DATE:
            return normalized, FileUtils.DEFAULT_UNKNOWN_YEAR, FileUtils.DEFAULT_UNKNOWN_MONTH
        return normalized, normalized[:4], normalized[:7]

    @staticmethod
    def build_preview_path(file_path):
        source_path = Path(file_path)
        preview_dir = source_path.parent / "previews"
        preview_filename = f"preview_{source_path.name}.png"
        return str(preview_dir / preview_filename)

class FileProcessor:
    def __init__(self):
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.openai_timeout_seconds = self._read_int_env("OPENAI_TIMEOUT_SECONDS", 30, min_value=5, max_value=120)
        self.llm_max_chars = self._read_int_env(
            "OPENAI_MAX_CHARS",
            FileUtils.DEFAULT_LLM_TRUNCATE_CHARS,
            min_value=500,
            max_value=20000,
        )

        # AI 摘要開關由 UI 控制；此處只做初始化與錯誤降級，避免缺依賴直接崩潰。
        self.client = None
        if OpenAI is None:
            logger.warning("OpenAI Python SDK 未安裝：AI 摘要功能將停用。")
        else:
            try:
                self.client = OpenAI(timeout=float(self.openai_timeout_seconds))
            except Exception as e:
                logger.warning(f"OpenAI Client 初始化失敗，AI 摘要功能將停用：{e}")
                self.client = None
        try:
            self.pdf_ocr_max_pages = max(1, min(int(os.getenv("PDF_OCR_MAX_PAGES", "3")), 5))
        except ValueError:
            self.pdf_ocr_max_pages = 3

        self.pdf_text_max_pages = self._read_int_env("PDF_TEXT_MAX_PAGES", 10, min_value=1, max_value=50)
        self.pdf_preview_max_pages = self._read_int_env("PDF_PREVIEW_MAX_PAGES", 1, min_value=1, max_value=3)
        self.max_heavy_process_bytes = self._read_int_env("MAX_HEAVY_PROCESS_MB", 15, min_value=1, max_value=200) * 1024 * 1024
        self.poppler_path = os.getenv("POPPLER_PATH") or None

    def _read_int_env(self, key, default, min_value=None, max_value=None):
        try:
            v = int(os.getenv(key, str(default)))
        except Exception:
            return default
        if min_value is not None:
            v = max(int(min_value), v)
        if max_value is not None:
            v = min(int(max_value), v)
        return v

    def get_dependency_status(self):
        """回傳可用性診斷，供 UI 顯示。"""
        return {
            "python": {
                "Pillow": Image is not None,
                "exifread": exifread is not None,
                "pypdf": PdfReader is not None,
                "pdf2image": convert_from_path is not None,
                "pytesseract": pytesseract is not None,
                "openai": OpenAI is not None,
            },
            "system": {
                "tesseract": shutil.which("tesseract") is not None,
                "pdftoppm": shutil.which("pdftoppm") is not None,
                "pdftocairo": shutil.which("pdftocairo") is not None,
            },
            "config": {
                "OPENAI_MODEL": self.model,
                "OPENAI_TIMEOUT_SECONDS": self.openai_timeout_seconds,
                "OPENAI_MAX_CHARS": self.llm_max_chars,
                "PDF_TEXT_MAX_PAGES": self.pdf_text_max_pages,
                "PDF_OCR_MAX_PAGES": self.pdf_ocr_max_pages,
                "PDF_PREVIEW_MAX_PAGES": self.pdf_preview_max_pages,
                "MAX_HEAVY_PROCESS_MB": int(self.max_heavy_process_bytes / (1024 * 1024)),
                "POPPLER_PATH": self.poppler_path or "",
            },
        }

    def get_file_hash(self, file_path):
        sha256_hash = hashlib.sha256()
        try:
            if hasattr(file_path, 'read'):
                file_path.seek(0)
                for byte_block in iter(lambda: file_path.read(4096), b""):
                    sha256_hash.update(byte_block)
                file_path.seek(0)
            else:
                with open(file_path, "rb") as f:
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error(f"計算 Hash 失敗: {e}")
            raise

    def extract_metadata(self, file_path, options=None) -> ExtractedMetadata:
        ext = os.path.splitext(file_path)[1].lower()
        opts = dict(options or {})
        enable_ocr = bool(opts.get("enable_ocr", True))
        enable_pdf_preview = bool(opts.get("enable_pdf_preview", True))
        max_heavy_bytes = int(opts.get("max_heavy_bytes", self.max_heavy_process_bytes))
        pdf_text_max_pages = int(opts.get("pdf_text_max_pages", self.pdf_text_max_pages))
        pdf_ocr_max_pages = int(opts.get("pdf_ocr_max_pages", self.pdf_ocr_max_pages))
        pdf_preview_max_pages = int(opts.get("pdf_preview_max_pages", self.pdf_preview_max_pages))

        metadata: ExtractedMetadata = {
            "file_type": "unknown",
            "standard_date": FileUtils.DEFAULT_UNKNOWN_DATE,
            "extracted_text": "",
            "is_scanned": False,
            "preview_path": None,
            "ocr_error": None,
            "notes": [],
        }

        try:
            try:
                file_size = os.path.getsize(file_path)
            except Exception:
                file_size = 0

            if ext in [".jpg", ".jpeg", ".png"]:
                metadata["file_type"] = "photo"
                metadata["standard_date"] = self._get_photo_date(file_path)
                metadata["preview_path"] = file_path
                if enable_ocr:
                    text, err = self._ocr_image(file_path)
                    metadata["extracted_text"] = text
                    metadata["ocr_error"] = err
                else:
                    metadata["notes"].append("OCR 已停用（設定）。")

            elif ext == ".pdf":
                metadata["file_type"] = "document"
                metadata["standard_date"] = self._get_file_mtime(file_path)

                metadata["extracted_text"] = self._extract_pdf_text(file_path, max_pages=pdf_text_max_pages)

                if enable_pdf_preview and convert_from_path is None:
                    metadata["notes"].append("pdf2image 未安裝，已跳過 PDF 預覽。")
                elif enable_pdf_preview and not self.poppler_path and shutil.which("pdftoppm") is None and shutil.which("pdftocairo") is None:
                    metadata["notes"].append("未找到 poppler（pdftoppm/pdftocairo），已跳過 PDF 預覽。")
                elif enable_pdf_preview and (not file_size or file_size <= max_heavy_bytes):
                    metadata["preview_path"] = self._generate_pdf_preview(file_path, max_pages=pdf_preview_max_pages)
                else:
                    if not enable_pdf_preview:
                        metadata["notes"].append("PDF 預覽已停用（設定）。")
                    elif file_size > max_heavy_bytes:
                        metadata["notes"].append("PDF 預覽已跳過（檔案過大，避免阻塞 UI）。")

                # 掃描檔補強（OCR）
                if not metadata["extracted_text"].strip():
                    metadata["is_scanned"] = True
                    if not enable_ocr:
                        metadata["ocr_error"] = "OCR 已停用（設定）。"
                    elif file_size and file_size > max_heavy_bytes:
                        metadata["ocr_error"] = "OCR 已跳過（檔案過大，避免阻塞 UI）。"
                    else:
                        text, err = self._ocr_pdf_sample(file_path, max_pages=pdf_ocr_max_pages)
                        metadata["extracted_text"] = text
                        metadata["ocr_error"] = err

            elif ext in FileUtils.VIDEO_EXTENSIONS:
                # Video file handling: extract metadata and generate thumbnail
                metadata["file_type"] = "video"
                metadata["standard_date"] = self._get_file_mtime(file_path)
                video_info = self._extract_video_metadata(file_path)
                if video_info.get("error"):
                    metadata["notes"].append(f"影片解析提示：{video_info['error']}")
                # Store video metadata in extra field
                metadata.setdefault("extra", {}).update(video_info)
                # Generate thumbnail (graceful degradation on failure)
                thumb_path = self._generate_video_thumbnail(file_path)
                if thumb_path:
                    metadata["preview_path"] = thumb_path
                else:
                    metadata.setdefault("extra", {})["thumbnail_error"] = "縮圖產生失敗或 ffprobe 不可用"

            metadata["standard_date"] = FileUtils.normalize_standard_date(metadata["standard_date"])
            if metadata["standard_date"] == FileUtils.DEFAULT_UNKNOWN_DATE:
                metadata["standard_date"] = FileUtils.normalize_standard_date(self._get_file_mtime(file_path))
        except Exception as e:
            logger.error(f"提取中繼資料失敗 ({file_path}): {e}")

        return metadata

    def _ocr_image(self, image_path):
        try:
            if pytesseract is None or Image is None:
                return "", "OCR 依賴未安裝（pytesseract/Pillow）。"
            if shutil.which("tesseract") is None:
                return "", "系統未找到 tesseract 可執行檔，OCR 已停用。"
            text = pytesseract.image_to_string(Image.open(image_path), lang='chi_tra+eng')
            return text.strip(), None
        except Exception as e:
            err_msg = str(e)
            logger.error(f"OCR 失敗: {err_msg}")
            if "tesseract is not installed" in err_msg.lower():
                return "", "系統未安裝 Tesseract OCR 引擎"
            if "chi_tra" in err_msg.lower():
                return "", "系統缺少繁體中文語言包 (chi_tra)"
            return "", f"OCR 錯誤: {err_msg[:50]}"

    def _generate_pdf_preview(self, file_path, max_pages=1):
        try:
            if convert_from_path is None:
                return None
            preview_path = FileUtils.build_preview_path(file_path)
            os.makedirs(os.path.dirname(preview_path), exist_ok=True)
            
            if not os.path.exists(preview_path):
                images = convert_from_path(
                    file_path,
                    first_page=1,
                    last_page=max(1, int(max_pages or 1)),
                    poppler_path=self.poppler_path,
                )
                if images:
                    images[0].save(preview_path, 'PNG')
            return preview_path
        except Exception as e:
            logger.error(f"PDF 預覽圖產生失敗: {e}")
            return None

    def _get_photo_date(self, file_path):
        try:
            if exifread is None:
                return None
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, stop_tag='DateTimeOriginal')
                if 'EXIF DateTimeOriginal' in tags:
                    date_str = str(tags['EXIF DateTimeOriginal'])
                    return FileUtils.normalize_standard_date(date_str.split(' ')[0].replace(':', '-'))
        except Exception as e:
            logger.debug(f"EXIF 讀取失敗: {e}")
        return None

    def _get_file_mtime(self, file_path):
        try:
            mtime = os.path.getmtime(file_path)
            return datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
        except Exception as e:
            logger.error(f"獲取修改時間失敗: {e}")
            return datetime.datetime.now().strftime('%Y-%m-%d')


    def _extract_video_metadata(self, file_path):
        """
        Extract video metadata using ffprobe.
        Returns dict with: media_type, duration_seconds, width, height, fps, video_codec, file_size, created_at, modified_at.
        Graceful degradation: returns partial data or error message if ffprobe unavailable.
        """
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
            import subprocess
            import json
            
            # Get file size
            try:
                result["file_size"] = os.path.getsize(file_path)
            except Exception:
                pass
            
            # Get modification time
            try:
                mtime = os.path.getmtime(file_path)
                result["modified_at"] = datetime.datetime.fromtimestamp(mtime).isoformat()
            except Exception:
                pass
            
            # Run ffprobe to get video stream info
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                result["error"] = f"ffprobe 執行失敗：{proc.stderr.strip()[:100]}"
                return result
            
            data = json.loads(proc.stdout)
            
            # Find video stream
            video_stream = None
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break
            
            if video_stream:
                result["width"] = video_stream.get("width")
                result["height"] = video_stream.get("height")
                result["video_codec"] = video_stream.get("codec_name")
                
                # FPS calculation
                fps = video_stream.get("r_frame_rate")
                if fps and "/" in fps:
                    num, den = fps.split("/")
                    try:
                        result["fps"] = round(float(num) / float(den), 2) if float(den) != 0 else None
                    except (ValueError, ZeroDivisionError):
                        result["fps"] = None
                elif fps:
                    try:
                        result["fps"] = float(fps)
                    except ValueError:
                        pass
            
            # Duration from format
            fmt = data.get("format", {})
            duration = fmt.get("duration")
            if duration:
                try:
                    result["duration_seconds"] = round(float(duration), 2)
                except ValueError:
                    pass
            
            # Creation time if available
            creation_time = fmt.get("tags", {}).get("creation_time")
            if creation_time:
                result["created_at"] = creation_time
                
        except subprocess.TimeoutExpired:
            result["error"] = "ffprobe 超時（影片可能損毀或過大）"
        except json.JSONDecodeError:
            result["error"] = "ffprobe 輸出解析失敗"
        except Exception as e:
            logger.error(f"影片 metadata 抽取失敗 ({file_path}): {e}")
            result["error"] = f"解析錯誤：{str(e)[:80]}"
        
        return result

    def _generate_video_thumbnail(self, file_path, thumb_percent=0.5):
        """
        Generate a thumbnail for a video file by extracting a frame from the middle.
        Returns thumbnail path on success, None on failure (graceful degradation).
        """
        if not FFMPEG_AVAILABLE:
            return None
        
        try:
            import subprocess
            
            # Get video duration first
            cmd_duration = [
                "ffprobe",
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ]
            proc = subprocess.run(cmd_duration, capture_output=True, text=True, timeout=10)
            if proc.returncode != 0:
                return None
            
            try:
                duration = float(proc.stdout.strip())
            except ValueError:
                duration = 1.0
            
            # Pick a timestamp around the middle (avoid black frames at start)
            thumb_time = max(1.0, duration * thumb_percent)
            
            # Build thumbnail path
            source_path = Path(file_path)
            thumb_dir = source_path.parent / "previews"
            thumb_filename = f"thumb_{source_path.name}.jpg"
            thumb_path = str(thumb_dir / thumb_filename)
            
            os.makedirs(str(thumb_dir), exist_ok=True)
            
            # Skip if already exists
            if os.path.exists(thumb_path):
                return thumb_path
            
            # Extract frame using ffmpeg
            cmd = [
                "ffmpeg",
                "-ss", str(thumb_time),
                "-i", file_path,
                "-vframes", "1",
                "-q:v", "2",
                "-y",
                thumb_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=60)
            if proc.returncode == 0 and os.path.exists(thumb_path):
                return thumb_path
            else:
                logger.warning(f"縮圖產生失敗 ({file_path}): {proc.stderr.decode('utf-8', errors='ignore')[:200]}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.warning(f"縮圖產生超時 ({file_path})")
            return None
        except Exception as e:
            logger.error(f"縮圖產生異常 ({file_path}): {e}")
            return None

    def _extract_pdf_text(self, file_path, max_pages=None):
        text = ""
        try:
            if PdfReader is None:
                return ""
            reader = PdfReader(file_path)
            pages = reader.pages
            if max_pages is not None:
                try:
                    max_pages = int(max_pages)
                except Exception:
                    max_pages = None
            if max_pages is not None and max_pages > 0:
                pages = pages[:max_pages]
            for page in pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        except Exception as e:
            logger.error(f"PDF 文字提取錯誤: {e}")
        return text

    def _ocr_pdf_sample(self, file_path, max_pages=3):
        collected_text = []
        errors = []
        try:
            if convert_from_path is None:
                return "", "PDF OCR 依賴未安裝（pdf2image）。"
            if pytesseract is None:
                return "", "PDF OCR 依賴未安裝（pytesseract）。"
            if shutil.which("tesseract") is None:
                return "", "系統未找到 tesseract 可執行檔，PDF OCR 已停用。"
            images = convert_from_path(
                file_path,
                first_page=1,
                last_page=max_pages,
                poppler_path=self.poppler_path,
            )
            for image in images:
                try:
                    text = pytesseract.image_to_string(image, lang='chi_tra+eng').strip()
                    if text:
                        collected_text.append(text)
                except Exception as e:
                    errors.append(str(e))
            if collected_text:
                return "\n".join(collected_text).strip(), None
        except Exception as e:
            errors.append(str(e))

        if not errors:
            return "", None

        err_msg = errors[0]
        logger.error(f"PDF OCR 失敗: {err_msg}")
        if "tesseract is not installed" in err_msg.lower():
            return "", "系統未安裝 Tesseract OCR 引擎"
        if "chi_tra" in err_msg.lower():
            return "", "系統缺少繁體中文 OCR 語言包 (chi_tra)"
        return "", f"PDF OCR 錯誤: {err_msg[:50]}"

    def get_llm_summary(self, text, file_type, enabled=False):
        """AI 摘要：預設不送出任何內容，必須明確 enabled=True 才會呼叫 OpenAI。"""
        if not enabled:
            return "AI 摘要未啟用（已阻止送出內容）。", []

        if not text or not str(text).strip():
            return "無可摘要的文字內容。", []

        if not self.client:
            return "AI 摘要不可用（OpenAI SDK 初始化失敗或未安裝）。", []

        text_to_send, was_truncated = FileUtils.truncate_text(text, self.llm_max_chars)
        note = "（內容已截斷）" if was_truncated else ""

        prompt = (
            "請閱讀以下內容，輸出 JSON 物件，包含：\n"
            '1) "summary": 50 字內重點摘要\n'
            '2) "tags": 3 個以中文為主的關鍵詞（字串陣列）\n'
            "只輸出 JSON，不要輸出其他文字。\n\n"
            f"檔案類型：{file_type}\n"
            f"內容：\n{text_to_send}\n"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
        except Exception:
            # 對使用者：友善訊息；詳細錯誤留在 log
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
            # JSON 解析失敗：不噴底層錯誤到 UI，保留可理解訊息
            logger.warning("AI 回應 JSON 解析失敗（已改用保守提示）", exc_info=True)
            msg = "AI 回應格式異常（JSON 解析失敗），請稍後再試。"
            if note:
                msg = f"{msg} {note}"
            return msg, []

    def classify_multi_tag(self, metadata, original_name, return_reason=False):
        """多訊號加權分類（檔名 / 文字(OCR) / 掃描特徵 / 副檔名）。"""
        scores = {}
        reasons = []
        original_name = original_name or ""
        name_lower = original_name.lower()
        text_lower = (metadata.get("extracted_text") or "").lower()
        ext = os.path.splitext(original_name)[1].lower()
        is_scanned = bool(metadata.get("is_scanned"))

        def add(tag, weight, why):
            scores[tag] = scores.get(tag, 0.0) + float(weight)
            reasons.append(f"{tag}: {why} (+{weight})")

        def sub(tag, weight, why):
            scores[tag] = scores.get(tag, 0.0) - float(weight)
            reasons.append(f"{tag}: {why} (-{weight})")

        is_document = metadata.get("file_type") == "document" or ext == ".pdf"
        is_video = metadata.get("file_type") == "video" or ext in FileUtils.VIDEO_EXTENSIONS

        if is_video:
            # Video files use simple tagging - just mark as video
            scores = {tag: 0.0 for tag in VIDEO_TAGS}
            scores["影片"] = 1.0
            reasons.append("影片：自動標記為影片類別")
            default_tag = "影片"
        elif is_document:
            scores = {tag: 0.0 for tag in DOCUMENT_TAGS}
            rules = [
                (["統一編號", "發票", "收據", "invoice", "receipt"], "發票", 0.9),
                (["合約", "契約", "協議", "contract", "agreement"], "合約", 0.9),
                (["報價", "quotation", "estimate"], "報價", 0.8),
                (["請款", "付款", "payment"], "請款", 0.7),
                (["證明", "證書", "certificate"], "證明文件", 0.8),
                (["會議", "紀錄", "minutes", "meeting"], "會議紀錄", 0.8),
            ]

            for keywords, tag, w in rules:
                if any(k.lower() in name_lower for k in keywords):
                    add(tag, w, f"檔名包含關鍵字 {keywords}")
                if any(k.lower() in text_lower for k in keywords):
                    add(tag, w * 0.6, f"內容包含關鍵字 {keywords}")

            if is_scanned:
                add("掃描", 0.5, "偵測為掃描件（PDF 文字不足）")

            # 負面規則：圖片副檔名降低文件信心（避免誤判）
            if ext in {".jpg", ".jpeg", ".png"}:
                for t in DOCUMENT_TAGS:
                    sub(t, 0.2, "副檔名為圖片，降低文件類別信心")

            default_tag = "其他文件"
        else:
            scores = {tag: 0.0 for tag in PHOTO_TAGS}
            rules = [
                (["screenshot", "截圖", "螢幕截圖"], "截圖", 0.9),
                (["food", "美食", "餐"], "美食", 0.8),
                (["trip", "travel", "旅行", "旅遊"], "旅行", 0.8),
                (["receipt", "收據", "發票", "統一編號", "invoice"], "文件/收據", 0.9),
            ]

            for keywords, tag, w in rules:
                if any(k.lower() in name_lower for k in keywords):
                    add(tag, w, f"檔名包含關鍵字 {keywords}")
                if any(k.lower() in text_lower for k in keywords):
                    add(tag, w * 0.6, f"OCR/內容包含關鍵字 {keywords}")

            # 負面規則：PDF 不應落在照片分類
            if ext == ".pdf":
                for t in PHOTO_TAGS:
                    sub(t, 0.5, "副檔名為 PDF，降低照片類別信心")

            default_tag = "其他照片"

        # 只保留正分數並上限 1.0，避免 UI 顯示負分噪音
        results = {tag: min(max(score, 0.0), 1.0) for tag, score in scores.items() if score > 0.0}
        if not results:
            results[default_tag] = 1.0
            reasons.append(f"{default_tag}: 無明確規則命中，使用預設分類 (+1.0)")

        main_topic = max(results, key=results.get)
        if return_reason:
            return main_topic, results, "\n".join(reasons[:30])
        return main_topic, results

    def sync_manual_topic(self, main_topic, tag_scores, file_type):
        normalized_scores = dict(tag_scores or {})
        if not main_topic:
            return normalized_scores

        if file_type == 'video':
            allowed_topics = VIDEO_TAGS
        elif file_type == 'document':
            allowed_topics = DOCUMENT_TAGS
        else:
            allowed_topics = PHOTO_TAGS
            
        if main_topic not in allowed_topics:
            return normalized_scores

        if not normalized_scores:
            normalized_scores[main_topic] = 1.0
            return normalized_scores

        current_max = max(normalized_scores.values(), default=0.0)
        normalized_scores[main_topic] = max(normalized_scores.get(main_topic, 0.0), current_max, 1.0)
        return normalized_scores
