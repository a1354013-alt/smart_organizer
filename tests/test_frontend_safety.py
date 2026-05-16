from __future__ import annotations

import frontend_safety


def test_inject_browser_storage_sanitizer_uses_st_html(monkeypatch):
    captured: dict[str, object] = {}

    def fake_html(body: object, **kwargs: object) -> None:
        captured["body"] = body
        captured["kwargs"] = kwargs

    monkeypatch.setattr(frontend_safety.st, "html", fake_html)

    frontend_safety.inject_browser_storage_sanitizer(enabled=True)

    assert "localStorage" in str(captured["body"])
    assert "sessionStorage" in str(captured["body"])
    assert captured["kwargs"] == {
        "width": "content",
        "unsafe_allow_javascript": True,
    }


def test_inject_browser_storage_sanitizer_skips_when_disabled(monkeypatch):
    called = False

    def fake_html(body: object, **kwargs: object) -> None:
        del body, kwargs
        nonlocal called
        called = True

    monkeypatch.setattr(frontend_safety.st, "html", fake_html)

    frontend_safety.inject_browser_storage_sanitizer(enabled=False)

    assert called is False
