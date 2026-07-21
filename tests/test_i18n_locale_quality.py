from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EN_PATH = PROJECT_ROOT / "locales" / "en.json"
ZH_PATH = PROJECT_ROOT / "locales" / "zh-TW.json"

_MOJIBAKE_SNIPPETS = (
    "嚙窯",
    "鞈",
    "瑼",
    "銝",
    "嚗",
    "蝜",
)
_SUSPICIOUS_QUESTION_RUN = re.compile(r"\?{2,}")


def _walk(value: object, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_walk(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rows.extend(_walk(child, f"{prefix}[{index}]"))
    elif isinstance(value, str):
        rows.append((prefix, value))
    return rows


def test_zh_tw_locale_has_no_damaged_strings_and_no_empty_translations_for_nonempty_english():
    en = json.loads(EN_PATH.read_text(encoding="utf-8"))
    zh = json.loads(ZH_PATH.read_text(encoding="utf-8"))
    zh_values = dict(_walk(zh))
    failures: list[str] = []

    for key, en_value in _walk(en):
        zh_value = zh_values.get(key)
        if zh_value is None:
            continue
        if en_value.strip() and not zh_value.strip():
            failures.append(f"{key}: empty translation for non-empty English value")
            continue
        if any(snippet in zh_value for snippet in _MOJIBAKE_SNIPPETS):
            failures.append(f"{key}: {zh_value!r}")
            continue
        if "\ufffd" in zh_value:
            failures.append(f"{key}: {zh_value!r}")
            continue
        if _SUSPICIOUS_QUESTION_RUN.search(zh_value):
            failures.append(f"{key}: {zh_value!r}")

    assert not failures, "\n".join(failures)
