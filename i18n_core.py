from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

DEFAULT_LANGUAGE = "zh-TW"
SUPPORTED_LANGUAGES = ("zh-TW", "en")
LANGUAGE_LABELS: Mapping[str, str] = {
    "zh-TW": "繁體中文",
    "en": "English",
}
SESSION_UI_LANGUAGE = "ui_language"
_LOCALES_DIR = Path(__file__).with_name("locales")


class _SafeFormatDict(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def normalize_language(value: object) -> str:
    language = str(value or DEFAULT_LANGUAGE)
    return language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


@cache
def load_locale(language: str) -> dict[str, Any]:
    locale_path = _LOCALES_DIR / f"{normalize_language(language)}.json"
    with locale_path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def resolve_key(locale: Mapping[str, Any], key: str) -> str | None:
    current: Any = locale
    for part in key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current if isinstance(current, str) else None


def get_language_label(language: str) -> str:
    normalized = normalize_language(language)
    return LANGUAGE_LABELS.get(normalized, normalized)


def get_language_options() -> list[str]:
    return list(SUPPORTED_LANGUAGES)


def translate(key: str, *, lang: str | None = None, **kwargs: object) -> str:
    normalized = normalize_language(lang)
    for candidate in dict.fromkeys((normalized, DEFAULT_LANGUAGE, "en")):
        value = resolve_key(load_locale(candidate), key)
        if value is None:
            continue
        try:
            return value.format_map(_SafeFormatDict(kwargs))
        except Exception:
            return value
    return key
