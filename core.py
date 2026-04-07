import os
import re
import datetime
import hashlib
import logging
from pathlib import Path
from PIL import Image
import exifread
from pypdf import PdfReader
from pdf2image import convert_from_path
import pytesseract
from openai import OpenAI

# 設定 Logging
logger = logging.getLogger(__name__)

DOCUMENT_TAGS = ['發票', '合約', '報價', '請款', '證明文件', '會議紀錄', '掃描', '其他文件']
PHOTO_TAGS = ['人物', '美食', '旅行', '文件/收據', '工作', '截圖', '風景', '其他照片']

class FileUtils:
    """純工具函式類別，不涉及業務邏輯與昂貴初始化"""
    DEFAULT_UNKNOWN_DATE = "UnknownDate"
    DEFAULT_UNKNOWN_YEAR = "UnknownYear"
    DEFAULT_UNKNOWN_MONTH = "UnknownMonth"
    ALLOWED_UPLOAD_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}

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
        try:
            self.client = OpenAI(timeout=30.0)
            # 【優化】從環境變數讀取模型名稱，預設為 gpt-4.1-mini
            self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        except Exception as e:
            logger.warning(f"OpenAI Client 初始化失敗: {e}")
            self.client = None
            self.model = "gpt-4.1-mini"
        try:
            self.pdf_ocr_max_pages = max(1, min(int(os.getenv("PDF_OCR_MAX_PAGES", "3")), 5))
        except ValueError:
            self.pdf_ocr_max_pages = 3

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

    def extract_metadata(self, file_path):
        ext = os.path.splitext(file_path)[1].lower()
        metadata = {
            'file_type': 'unknown',
            'standard_date': FileUtils.DEFAULT_UNKNOWN_DATE,
            'extracted_text': '',
            'is_scanned': False,
            'preview_path': None,
            'ocr_error': None
        }

        try:
            if ext in ['.jpg', '.jpeg', '.png']:
                metadata['file_type'] = 'photo'
                metadata['standard_date'] = self._get_photo_date(file_path)
                metadata['preview_path'] = file_path
                text, err = self._ocr_image(file_path)
                metadata['extracted_text'] = text
                metadata['ocr_error'] = err
            elif ext == '.pdf':
                metadata['file_type'] = 'document'
                metadata['standard_date'] = self._get_file_mtime(file_path)
                metadata['extracted_text'] = self._extract_pdf_text(file_path)
                metadata['preview_path'] = self._generate_pdf_preview(file_path)
                
                # 掃描檔補強
                if not metadata['extracted_text'].strip():
                    metadata['is_scanned'] = True
                    text, err = self._ocr_pdf_sample(file_path, max_pages=self.pdf_ocr_max_pages)
                    metadata['extracted_text'] = text
                    metadata['ocr_error'] = err
            
            metadata['standard_date'] = FileUtils.normalize_standard_date(metadata['standard_date'])
            if metadata['standard_date'] == FileUtils.DEFAULT_UNKNOWN_DATE:
                metadata['standard_date'] = FileUtils.normalize_standard_date(self._get_file_mtime(file_path))
        except Exception as e:
            logger.error(f"提取中繼資料失敗 ({file_path}): {e}")
            
        return metadata

    def _ocr_image(self, image_path):
        try:
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

    def _generate_pdf_preview(self, file_path):
        try:
            preview_path = FileUtils.build_preview_path(file_path)
            os.makedirs(os.path.dirname(preview_path), exist_ok=True)
            
            if not os.path.exists(preview_path):
                images = convert_from_path(file_path, first_page=1, last_page=1)
                if images:
                    images[0].save(preview_path, 'PNG')
            return preview_path
        except Exception as e:
            logger.error(f"PDF 預覽圖產生失敗: {e}")
            return None

    def _get_photo_date(self, file_path):
        try:
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

    def _extract_pdf_text(self, file_path):
        text = ""
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
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
            images = convert_from_path(file_path, first_page=1, last_page=max_pages)
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

    def get_llm_summary(self, text, file_type):
        if not self.client or not text.strip():
            return "無法生成摘要 (無 API Key 或無文字內容)", []

        try:
            prompt = f"""
            請分析以下{file_type}內容，並提供：
            1. 一句 50 字以內的簡短摘要。
            2. 3 個最相關的關鍵字標籤。
            內容：{text[:2000]}
            請以 JSON 格式回傳：{{"summary": "...", "tags": ["tag1", "tag2", "tag3"]}}
            """
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            import json
            result = json.loads(response.choices[0].message.content)
            return result.get('summary', ''), result.get('tags', [])
        except Exception as e:
            logger.error(f"LLM 處理失敗: {e}")
            return f"LLM 處理失敗: {e}", []

    def classify_multi_tag(self, metadata, original_name):
        scores = {}
        name_lower = original_name.lower()
        text = metadata['extracted_text'].lower()
        
        if metadata['file_type'] == 'document':
            tags = DOCUMENT_TAGS
            scores = {tag: 0.0 for tag in tags}
            rules = [
                (["統一編號", "發票", "收據", "invoice"], "發票", 0.8),
                (["合約", "協議", "contract", "agreement"], "合約", 0.9),
                (["報價", "quotation", "estimate"], "報價", 0.8),
                (["請款", "payment"], "請款", 0.7),
                (["證明", "證書", "certificate"], "證明文件", 0.8),
                (["會議", "紀錄", "minutes"], "會議紀錄", 0.8)
            ]
            for keywords, tag, weight in rules:
                if any(k in name_lower for k in keywords): scores[tag] += weight
                if any(k in text for k in keywords): scores[tag] += weight
            if metadata['is_scanned']: scores['掃描'] += 0.5
            default_tag = '其他文件'
        else:
            tags = PHOTO_TAGS
            scores = {tag: 0.0 for tag in tags}
            rules = [
                (["screenshot", "截圖"], "截圖", 0.9),
                (["food", "美食"], "美食", 0.8),
                (["trip", "travel", "旅行"], "旅行", 0.8),
                (["receipt", "收據", "發票", "統一編號"], "文件/收據", 0.9)
            ]
            for keywords, tag, weight in rules:
                if any(k in name_lower for k in keywords): scores[tag] += weight
                if any(k in text for k in keywords): scores[tag] += weight
            default_tag = '其他照片'

        results = {tag: min(score, 1.0) for tag, score in scores.items() if score > 0}
        if not results: results[default_tag] = 1.0
        main_topic = max(results, key=results.get)
        return main_topic, results

    def sync_manual_topic(self, main_topic, tag_scores, file_type):
        normalized_scores = dict(tag_scores or {})
        if not main_topic:
            return normalized_scores

        allowed_topics = DOCUMENT_TAGS if file_type == 'document' else PHOTO_TAGS
        if main_topic not in allowed_topics:
            return normalized_scores

        if not normalized_scores:
            normalized_scores[main_topic] = 1.0
            return normalized_scores

        current_max = max(normalized_scores.values(), default=0.0)
        normalized_scores[main_topic] = max(normalized_scores.get(main_topic, 0.0), current_max, 1.0)
        return normalized_scores
