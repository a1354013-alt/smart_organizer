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


def test_inject_browser_storage_sanitizer_falls_back_on_type_error(monkeypatch):
    captured: dict[str, object] = {}

    def fake_html(*args: object, **kwargs: object) -> None:
        raise TypeError("unsupported keyword")

    def fake_components_html(body: object, **kwargs: object) -> None:
        captured["body"] = body
        captured["kwargs"] = kwargs

    monkeypatch.setattr(frontend_safety.st, "html", fake_html)
    monkeypatch.setattr(frontend_safety.st_components, "html", fake_components_html)

    frontend_safety.inject_browser_storage_sanitizer(enabled=True)

    assert "localStorage" in str(captured["body"])
    assert captured["kwargs"] == {"height": 0, "width": 0}


def test_inject_browser_storage_sanitizer_does_not_swallow_unrelated_errors(monkeypatch):
    def fake_html(*args: object, **kwargs: object) -> None:
        raise RuntimeError("streamlit exploded")

    monkeypatch.setattr(frontend_safety.st, "html", fake_html)

    try:
        frontend_safety.inject_browser_storage_sanitizer(enabled=True)
    except RuntimeError as exc:
        assert "streamlit exploded" in str(exc)
    else:
        raise AssertionError("Expected unrelated Streamlit error to propagate")
