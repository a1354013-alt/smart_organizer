from __future__ import annotations

import datetime
import os
import re
from pathlib import Path

from supported_formats import SUPPORTED_UPLOAD_SUFFIXES, SUPPORTED_VIDEO_SUFFIXES


class FileUtils:
    """Shared filename, date, and preview-path helpers."""

    DEFAULT_UNKNOWN_DATE = "UnknownDate"
    DEFAULT_UNKNOWN_YEAR = "UnknownYear"
    DEFAULT_UNKNOWN_MONTH = "UnknownMonth"
    ALLOWED_UPLOAD_EXTENSIONS = frozenset(SUPPORTED_UPLOAD_SUFFIXES)
    VIDEO_EXTENSIONS = frozenset(SUPPORTED_VIDEO_SUFFIXES)
    DEFAULT_LLM_TRUNCATE_CHARS = 6000
    WINDOWS_RESERVED_NAMES = frozenset(
        {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{index}" for index in range(1, 10)),
            *(f"LPT{index}" for index in range(1, 10)),
        }
    )
    _INVALID_FILENAME_CHARS = re.compile(r'[\\/*?:"<>|]')

    @staticmethod
    def truncate_text(text: object, max_chars: object) -> tuple[str, bool]:
        if text is None:
            return "", False
        s = str(text)
        parsed_max_chars = FileUtils._coerce_int(max_chars)
        if parsed_max_chars is None or parsed_max_chars <= 0:
            return s, False
        if len(s) <= parsed_max_chars:
            return s, False
        return s[:parsed_max_chars], True

    @staticmethod
    def sanitize_filename(filename: str, max_length: int = 200) -> str:
        raw_name = os.path.basename(str(filename or ""))
        name, ext = os.path.splitext(raw_name)
        total_limit = max(1, int(max_length))

        cleaned_name = FileUtils._sanitize_filename_part(name)
        cleaned_ext = FileUtils._sanitize_extension(ext, total_limit=total_limit)

        if not cleaned_name:
            cleaned_name = "untitled_file"

        max_name_length = max(1, total_limit - len(cleaned_ext))
        cleaned_name = FileUtils._trim_filename_stem(cleaned_name, max_length=max_name_length)
        cleaned_name = FileUtils._avoid_windows_reserved_name(cleaned_name, max_length=max_name_length)

        return f"{cleaned_name}{cleaned_ext}"

    @staticmethod
    def _sanitize_filename_part(value: str) -> str:
        cleaned = FileUtils._INVALID_FILENAME_CHARS.sub("", str(value or ""))
        cleaned = "".join(ch for ch in cleaned if ord(ch) >= 32)
        while ".." in cleaned:
            cleaned = cleaned.replace("..", "")
        return cleaned.strip(" .")

    @staticmethod
    def _sanitize_extension(ext: str, *, total_limit: int) -> str:
        cleaned_ext = FileUtils._INVALID_FILENAME_CHARS.sub("", str(ext or ""))
        cleaned_ext = "".join(ch for ch in cleaned_ext if ord(ch) >= 32)
        cleaned_ext = cleaned_ext.rstrip(" .")
        if len(cleaned_ext) >= total_limit:
            cleaned_ext = cleaned_ext[: max(0, total_limit - 1)]
        return cleaned_ext

    @staticmethod
    def _trim_filename_stem(name: str, *, max_length: int) -> str:
        trimmed = str(name or "").strip(" .")
        if len(trimmed) > max_length:
            trimmed = trimmed[:max_length].rstrip(" .")
        return trimmed or "untitled_file"

    @staticmethod
    def _coerce_int(value: object) -> int | None:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _avoid_windows_reserved_name(name: str, *, max_length: int) -> str:
        candidate = (name or "").strip(" .") or "untitled_file"
        if candidate.upper() not in FileUtils.WINDOWS_RESERVED_NAMES:
            return candidate

        suffix = "_file"
        base_limit = max(1, max_length - len(suffix))
        base = candidate[:base_limit].rstrip(" .") or "file"
        adjusted = f"{base}{suffix}"
        if len(adjusted) > max_length:
            adjusted = adjusted[:max_length].rstrip(" .")
        return adjusted or "file"

    @staticmethod
    def get_unique_path(target_path: str | os.PathLike[str]) -> str | os.PathLike[str]:
        if not os.path.exists(target_path):
            return target_path
        base, ext = os.path.splitext(target_path)
        counter = 1
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        return f"{base}_{counter}{ext}"

    @staticmethod
    def escape_fts_query(query: object) -> str:
        if not query:
            return ""
        clean_query = str(query)
        for ch in ['"', ":", "-", "*", "(", ")"]:
            clean_query = clean_query.replace(ch, " ")
        words = [f'"{w}"' for w in clean_query.split() if w]
        return " ".join(words)

    @staticmethod
    def normalize_standard_date(raw_value: object) -> str:
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
    def get_date_directory_parts(raw_value: object) -> tuple[str, str, str]:
        normalized = FileUtils.normalize_standard_date(raw_value)
        if normalized == FileUtils.DEFAULT_UNKNOWN_DATE:
            return normalized, FileUtils.DEFAULT_UNKNOWN_YEAR, FileUtils.DEFAULT_UNKNOWN_MONTH
        return normalized, normalized[:4], normalized[:7]

    @staticmethod
    def build_preview_path(file_path: str | os.PathLike[str]) -> str:
        source_path = Path(file_path)
        preview_dir = source_path.parent / "previews"
        preview_filename = f"preview_{source_path.name}.png"
        return str(preview_dir / preview_filename)
