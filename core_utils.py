from __future__ import annotations

import datetime
import os
import re
from pathlib import Path


class FileUtils:
    """純工具函式類別，不涉及業務邏輯與昂貴初始化"""

    DEFAULT_UNKNOWN_DATE = "UnknownDate"
    DEFAULT_UNKNOWN_YEAR = "UnknownYear"
    DEFAULT_UNKNOWN_MONTH = "UnknownMonth"
    ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".mp4", ".mov", ".mkv"}
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}
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
        clean_query = str(query)
        for ch in ['"', ":", "-", "*", "(", ")"]:
            clean_query = clean_query.replace(ch, " ")
        words = [f'"{w}"' for w in clean_query.split() if w]
        return " ".join(words)

    @staticmethod
    def normalize_standard_date(raw_value):
        if raw_value is None:
            return FileUtils.DEFAULT_UNKNOWN_DATE

        value = str(raw_value).strip()
        if not value or value == FileUtils.DEFAULT_UNKNOWN_DATE:
            return FileUtils.DEFAULT_UNKNOWN_DATE

        trimmed = value.replace("T", " ").split(" ")[0]
        normalized = re.sub(r"[./_]", "-", trimmed)

        match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", normalized)
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
