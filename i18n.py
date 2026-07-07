from __future__ import annotations

from collections.abc import Mapping

import streamlit as st

from i18n_core import (
    DEFAULT_LANGUAGE,
    LANGUAGE_LABELS,
    SESSION_UI_LANGUAGE,
    SUPPORTED_LANGUAGES,
    get_language_label,
    get_language_options,
    load_locale,
    normalize_language,
    translate,
)


def get_current_language(session_state: Mapping[str, object] | None = None) -> str:
    if session_state is not None:
        return normalize_language(session_state.get(SESSION_UI_LANGUAGE))
    try:
        return normalize_language(st.session_state.get(SESSION_UI_LANGUAGE))
    except Exception:
        return DEFAULT_LANGUAGE


def set_current_language(language: str, session_state: dict[str, object] | None = None) -> str:
    normalized = normalize_language(language)
    if session_state is not None:
        session_state[SESSION_UI_LANGUAGE] = normalized
        return normalized
    try:
        st.session_state[SESSION_UI_LANGUAGE] = normalized
    except Exception:
        return normalized
    return normalized


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    return translate(key, lang=lang or get_current_language(), **kwargs)


__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGE_LABELS",
    "SESSION_UI_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "get_current_language",
    "get_language_label",
    "get_language_options",
    "load_locale",
    "normalize_language",
    "set_current_language",
    "t",
]
