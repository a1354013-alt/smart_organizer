from __future__ import annotations

from types import SimpleNamespace

import core_processor
from core import FileProcessor
from ui_home import (
    DEPENDENCY_STATUS_SESSION_KEY,
    cache_dependency_status,
    get_cached_dependency_status,
    refresh_dependency_status,
)


def test_dependency_status_cache_starts_empty():
    session_state: dict[str, object] = {}

    assert get_cached_dependency_status(session_state) is None
    assert DEPENDENCY_STATUS_SESSION_KEY not in session_state


def test_refresh_dependency_status_calls_processor_once_and_caches(monkeypatch):
    captured: list[str] = []
    session_state: dict[str, object] = {}
    context = SimpleNamespace(
        processor=SimpleNamespace(
            get_dependency_status=lambda: captured.append("called") or {"system": {"ffmpeg": True}}
        )
    )

    monkeypatch.setattr("ui_home.st.session_state", session_state)

    status = refresh_dependency_status(context)

    assert captured == ["called"]
    assert status == {"system": {"ffmpeg": True}}
    assert session_state[DEPENDENCY_STATUS_SESSION_KEY] == {"system": {"ffmpeg": True}}
    assert get_cached_dependency_status(session_state) == {"system": {"ffmpeg": True}}


def test_cache_dependency_status_normalizes_to_plain_dict():
    session_state: dict[str, object] = {}
    source = {"python": {"pypdf": True}}

    cached = cache_dependency_status(session_state, source)
    source["python"] = {"pypdf": False}

    assert cached == {"python": {"pypdf": True}}
    assert get_cached_dependency_status(session_state) == {"python": {"pypdf": True}}


def test_file_processor_dependency_status_checks_ffmpeg_lazily(monkeypatch):
    calls: list[bool] = []
    processor = FileProcessor()

    monkeypatch.setattr(core_processor, "FFMPEG_AVAILABLE", None)
    monkeypatch.setattr(
        core_processor,
        "_detect_ffmpeg_available",
        lambda: calls.append(True) or True,
    )

    assert calls == []

    status = processor.get_dependency_status()

    assert calls == [True]
    assert status["system"]["ffmpeg"] is True
