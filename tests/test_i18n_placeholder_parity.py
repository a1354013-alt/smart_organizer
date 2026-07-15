from __future__ import annotations

import re
from collections.abc import Mapping

from i18n_core import load_locale


def _flatten_locale(prefix: str, value: object) -> dict[str, str]:
    if isinstance(value, Mapping):
        flattened: dict[str, str] = {}
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_locale(child_prefix, child))
        return flattened
    return {prefix: value} if isinstance(value, str) else {}


def test_en_and_zh_tw_translation_keys_and_placeholders_match():
    en = _flatten_locale("", load_locale("en"))
    zh = _flatten_locale("", load_locale("zh-TW"))
    placeholder_pattern = re.compile(r"{([^{}]+)}")

    assert set(en) == set(zh)
    for key in sorted(en):
        assert set(placeholder_pattern.findall(en[key])) == set(placeholder_pattern.findall(zh[key])), key
