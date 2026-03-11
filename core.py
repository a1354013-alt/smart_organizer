import os
import datetime
import hashlib
from PIL import Image
import exifread
from pypdf import PdfReader
from pdf2image import convert_from_path
from openai import OpenAI

# 預設主題定義
DOCUMENT_TAGS = ['發票', '合約', '報價', '請款', '證明文件', '會議紀錄', '掃描', '其他文件']
PHOTO_TAGS = ['人物', '美食', '旅行', '文件/收據', '工作', '截圖', '風景', '其他照片']

class FileProcessor:
    def __init__(self):
        # 初始化 OpenAI Client (使用環境變數中的 API Key)
        try:
            self.client = OpenAI()
        except:
            self.client = None

    def get_file_hash(self, file_path):
        """計算檔案 SHA256 Hash"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def extract_metadata(self, file_path):
        """提取檔案中繼資料與時間"""
        ext = os.path.splitext(file_path)[1].lower()
        metadata = {
            'file_type': 'unknown',
            'standard_date': None,
            'extracted_text': '',
            'is_scanned': False,
            'preview_path': None
        }

        if ext in ['.jpg', '.jpeg', '.png']:
            metadata['file_type'] = 'photo'
            metadata['standard_date'] = self._get_photo_date(file_path)
            metadata['preview_path'] = file_path # 照片直接預覽
        elif ext == '.pdf':
            metadata['file_type'] = 'document'
            metadata['standard_date'] = self._get_file_mtime(file_path)
            metadata['extracted_text'] = self._extract_pdf_text(file_path)
            if not metadata['extracted_text'].strip():
                metadata['is_scanned'] = True
            # 產生 PDF 預覽圖
            metadata['preview_path'] = self._generate_pdf_preview(file_path)
        
        if not metadata['standard_date']:
            metadata['standard_date'] = self._get_file_mtime(file_path)
            
        return metadata

    def _generate_pdf_preview(self, file_path):
        """將 PDF 第一頁轉為圖片供預覽"""
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
            print(f"PDF 預覽圖產生失敗: {e}")
            return None

    def _get_photo_date(self, file_path):
        """從 EXIF 提取日期"""
        try:
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, stop_tag='DateTimeOriginal')
                if 'EXIF DateTimeOriginal' in tags:
                    date_str = str(tags['EXIF DateTimeOriginal'])
                    return date_str.split(' ')[0].replace(':', '-')
        except:
            pass
        return None

    def _get_file_mtime(self, file_path):
        """獲取檔案修改時間"""
        mtime = os.path.getmtime(file_path)
        return datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')

    def _extract_pdf_text(self, file_path):
        """提取 PDF 文字"""
        text = ""
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        except Exception as e:
            print(f"PDF 提取錯誤: {e}")
        return text

    def get_llm_summary(self, text, file_type):
        """使用 LLM 生成摘要與建議標籤"""
        if not self.client or not text.strip():
            return "無法生成摘要 (無 API Key 或無文字內容)", []

        try:
            prompt = f"""
            請分析以下{file_type}內容，並提供：
            1. 一句 50 字以內的簡短摘要。
            2. 3 個最相關的關鍵字標籤。
            
            內容：
            {text[:2000]}
            
            請以 JSON 格式回傳：
            {{"summary": "...", "tags": ["tag1", "tag2", "tag3"]}}
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
            return f"LLM 處理失敗: {e}", []

    def classify_multi_tag(self, metadata, original_name):
        """強化版多標籤分類邏輯"""
        scores = {}
        name_lower = original_name.lower()
        
        if metadata['file_type'] == 'document':
            tags = DOCUMENT_TAGS
            scores = {tag: 0.0 for tag in tags}
            text = metadata['extracted_text'].lower()
            
            rules = [
                (["統一編號", "發票", "收據", "invoice", "號碼"], "發票", 0.8),
                (["合約", "協議", "contract", "agreement", "甲方", "乙方"], "合約", 0.9),
                (["報價", "quotation", "estimate", "總價"], "報價", 0.8),
                (["請款", "撥款", "payment", "金額"], "請款", 0.7),
                (["證明", "證書", "certificate", "證"], "證明文件", 0.8),
                (["會議", "紀錄", "minutes", "會"], "會議紀錄", 0.8)
            ]
            
            for keywords, tag, weight in rules:
                if any(k in name_lower for k in keywords): scores[tag] += 0.4
                if any(k in text for k in keywords): scores[tag] += 0.6
            
            if metadata['is_scanned']: scores['掃描'] += 0.5
            default_tag = '其他文件'
            
        else: # photo
            tags = PHOTO_TAGS
            scores = {tag: 0.0 for tag in tags}
            rules = [
                (["screenshot", "截圖"], "截圖", 0.9),
                (["line_", "line"], "截圖", 0.5),
                (["food", "美食", "eat"], "美食", 0.8),
                (["trip", "travel", "旅行"], "旅行", 0.8),
                (["receipt", "收據"], "文件/收據", 0.9),
                (["work", "工作"], "工作", 0.7)
            ]
            for keywords, tag, weight in rules:
                if any(k in name_lower for k in keywords): scores[tag] += weight
            default_tag = '其他照片'

        results = {tag: min(score, 1.0) for tag, score in scores.items() if score > 0}
        if not results: results[default_tag] = 1.0
        main_topic = max(results, key=results.get)
        
        return main_topic, results
