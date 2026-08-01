from __future__ import annotations

import importlib

import app_main


def test_optional_import_returns_none_when_module_is_missing(monkeypatch):
    real_import_module = importlib.import_module

    def fake_import_module(name: str):
        if name == "missing_optional_package":
            raise ModuleNotFoundError("No module named 'missing_optional_package'", name="missing_optional_package")
        return real_import_module(name)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    assert app_main._optional_import("missing_optional_package") is None


def test_optional_import_returns_module_when_import_succeeds():
    module = app_main._optional_import("math")

    assert module is not None
    assert module.sqrt(9) == 3


def test_optional_import_logs_and_returns_none_for_unexpected_import_failure(monkeypatch):
    messages: list[tuple[str, tuple[object, ...], bool]] = []
    real_get_logger = app_main.logging.getLogger

    class _Logger:
        def warning(self, message: str, *args: object, exc_info: bool = False) -> None:
            messages.append((message, args, exc_info))

    monkeypatch.setattr(app_main, "setup_logging", lambda: None)
    monkeypatch.setattr(
        app_main.logging,
        "getLogger",
        lambda name=None: _Logger() if name == app_main.__name__ else real_get_logger(name),
    )
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(RuntimeError("broken optional dependency")),
    )

    assert app_main._optional_import("broken_optional_package") is None
    assert messages == [
        (
            "Optional dependency %s raised during import and was disabled.",
            ("broken_optional_package",),
            True,
        )
    ]


def test_optional_import_logs_nested_module_not_found_as_broken_dependency(monkeypatch):
    messages: list[tuple[str, tuple[object, ...], bool]] = []
    real_get_logger = app_main.logging.getLogger

    class _Logger:
        def warning(self, message: str, *args: object, exc_info: bool = False) -> None:
            messages.append((message, args, exc_info))

    monkeypatch.setattr(app_main, "setup_logging", lambda: None)
    monkeypatch.setattr(
        app_main.logging,
        "getLogger",
        lambda name=None: _Logger() if name == app_main.__name__ else real_get_logger(name),
    )

    def fake_import_module(_name: str):
        raise ModuleNotFoundError("No module named 'nested_missing'", name="nested_missing")

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    assert app_main._optional_import("optional_package") is None
    assert messages == [
        (
            "Optional dependency %s failed because a nested import is missing: %s",
            ("optional_package", "nested_missing"),
            True,
        )
    ]
