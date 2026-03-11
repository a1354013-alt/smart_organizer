import os
import re
import datetime
import hashlib
import logging
from PIL import Image
import exifread
from pypdf import PdfReader
from pdf2image import convert_from_path
from openai import OpenAI

# 設定 Logging
logger = logging.getLogger(__name__)

DOCUMENT_TAGS = ['發票', '合約', '報價', '請款', '證明文件', '會議紀錄', '掃描', '其他文件']
PHOTO_TAGS = ['人物', '美食', '旅行', '文件/收據', '工作', '截圖', '風景', '其他照片']

class FileProcessor:
    def __init__(self):
        try:
            self.client = OpenAI()
        except Exception as e:
            logger.warning(f"OpenAI Client 初始化失敗 (可能缺少 API Key): {e}")
            self.client = None

    def sanitize_filename(self, filename, max_length=200):
        """檔名安全處理：移除非法字元、限制長度"""
        # 移除非法字元
        filename = re.sub(r'[\\/*?:"<>|]', "", filename)
        # 移除控制字元與 ..
        filename = "".join(ch for ch in filename if ord(ch) >= 32)
        filename = filename.replace("..", "")
        
        name, ext = os.path.splitext(filename)
        # 限制長度
        if len(name) > max_length:
            name = name[:max_length]
        return f"{name}{ext}"

    def get_unique_path(self, target_path):
        """若檔名衝突，自動加序號"""
        if not os.path.exists(target_path):
            return target_path
        
        base, ext = os.path.splitext(target_path)
        counter = 1
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        return f"{base}_{counter}{ext}"

    def get_file_hash(self, file_path):
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error(f"計算 Hash 失敗: {e}")
            raise

    def extract_metadata(self, file_path):
        """提取中繼資料，明確標記掃描 PDF"""
        ext = os.path.splitext(file_path)[1].lower()
        metadata = {
            'file_type': 'unknown',
            'standard_date': None,
            'extracted_text': '',
            'is_scanned': False,
            'preview_path': None
        }

        try:
            if ext in ['.jpg', '.jpeg', '.png']:
                metadata['file_type'] = 'photo'
                metadata['standard_date'] = self._get_photo_date(file_path)
                metadata['preview_path'] = file_path
            elif ext == '.pdf':
                metadata['file_type'] = 'document'
                metadata['standard_date'] = self._get_file_mtime(file_path)
                metadata['extracted_text'] = self._extract_pdf_text(file_path)
                # 明確標記掃描 PDF
                if not metadata['extracted_text'].strip():
                    metadata['is_scanned'] = True
                    logger.info(f"偵測到掃描 PDF: {file_path}")
                metadata['preview_path'] = self._generate_pdf_preview(file_path)
            
            if not metadata['standard_date']:
                metadata['standard_date'] = self._get_file_mtime(file_path)
        except Exception as e:
            logger.error(f"提取中繼資料失敗 ({file_path}): {e}")
            
        return metadata

    def _generate_pdf_preview(self, file_path):
        try:
            preview_dir = os.path.join(os.path.dirname(file_path), 'previews')
            os.makedirs(preview_dir, exist_ok=True)
            preview_filename = os.path.basename(file_path) + ".jpg"
            preview_path = os.path.join(preview_dir, preview_filename)
            
            if not os.path.exists(preview_path):
                images = convert_from_path(file_path, first_page=1, last_page=1)
                if images:
                    images[0].save(preview_path, 'JPEG')
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
                    return date_str.split(' ')[0].replace(':', '-')
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
                model="gpt-4.1-mini",
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
        
        if metadata['file_type'] == 'document':
            tags = DOCUMENT_TAGS
            scores = {tag: 0.0 for tag in tags}
            text = metadata['extracted_text'].lower()
            
            rules = [
                (["統一編號", "發票", "收據", "invoice"], "發票", 0.8),
                (["合約", "協議", "contract", "agreement"], "合約", 0.9),
                (["報價", "quotation", "estimate"], "報價", 0.8),
                (["請款", "payment"], "請款", 0.7),
                (["證明", "證書", "certificate"], "證明文件", 0.8),
                (["會議", "紀錄", "minutes"], "會議紀錄", 0.8)
            ]
            
            for keywords, tag, weight in rules:
                if any(k in name_lower for k in keywords): scores[tag] += 0.4
                if any(k in text for k in keywords): scores[tag] += 0.6
            
            if metadata['is_scanned']: scores['掃描'] += 0.5
            default_tag = '其他文件'
            
        else:
            tags = PHOTO_TAGS
            scores = {tag: 0.0 for tag in tags}
            rules = [
                (["screenshot", "截圖"], "截圖", 0.9),
                (["food", "美食"], "美食", 0.8),
                (["trip", "travel", "旅行"], "旅行", 0.8),
                (["receipt", "收據"], "文件/收據", 0.9)
            ]
            for keywords, tag, weight in rules:
                if any(k in name_lower for k in keywords): scores[tag] += weight
            default_tag = '其他照片'

        results = {tag: min(score, 1.0) for tag, score in scores.items() if score > 0}
        if not results: results[default_tag] = 1.0
        main_topic = max(results, key=results.get)
        
        return main_topic, results
