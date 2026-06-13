from __future__ import annotations

from i18n import DEFAULT_LANGUAGE, get_language_label, t


def test_zh_tw_key_returns_localized_value():
    assert t("app.tabs.folder_scan", lang="zh-TW") == "資料夾掃描"


def test_en_key_returns_localized_value():
    assert t("app.tabs.folder_scan", lang="en") == "Folder Scan"


def test_missing_key_falls_back_without_crashing():
    assert t("missing.section.key", lang="zh-TW") == "missing.section.key"


def test_translation_supports_formatting_kwargs():
    assert t("home.scan.progress", lang="zh-TW", count=10) == "掃描中，已檢查 10 個檔案"


def test_default_language_is_zh_tw():
    assert DEFAULT_LANGUAGE == "zh-TW"
    assert get_language_label(DEFAULT_LANGUAGE) == "繁體中文"
