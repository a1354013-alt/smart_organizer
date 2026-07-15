from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from startup import (
    StartupError,
    initialize_startup,
    render_startup_error,
    run_with_startup_boundary,
)


class FakeStreamlit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_page_config(self, **kwargs: object) -> None:
        self.calls.append(("set_page_config", kwargs))

    def error(self, value: object) -> None:
        self.calls.append(("error", value))

    def markdown(self, value: object) -> None:
        self.calls.append(("markdown", value))

    def write(self, value: object) -> None:
        self.calls.append(("write", value))

    def info(self, value: object) -> None:
        self.calls.append(("info", value))

    def code(self, value: object) -> None:
        self.calls.append(("code", value))

    def button(self, value: object) -> bool:
        self.calls.append(("button", value))
        return False

    def rerun(self) -> None:
        self.calls.append(("rerun", None))


def test_startup_error_page_is_safe_and_has_reference_id():
    fake = FakeStreamlit()
    error = StartupError(
        stage="runtime-directory validation",
        summary="Directory is not writable.",
        remediation="Choose another directory.",
        config=SimpleNamespace(data_root=Path("C:/safe/data")),  # type: ignore[arg-type]
        legacy_detected=False,
    )

    render_startup_error(fake, error)
    rendered = "\n".join(str(value) for _name, value in fake.calls)

    assert "runtime-directory validation" in rendered
    assert "Directory is not writable." in rendered
    assert "Choose another directory." in rendered
    assert "SECRET" not in rendered
    assert any(name == "code" and value == error.reference_id for name, value in fake.calls)


def test_startup_boundary_prevents_normal_render_after_fatal_error():
    fake = FakeStreamlit()
    rendered_normal = False

    def fail() -> None:
        nonlocal rendered_normal
        rendered_normal = True
        raise StartupError(stage="database initialization", summary="DB failed", remediation="Retry later")

    run_with_startup_boundary(fake, fail)

    assert rendered_normal is True
    assert any(name == "error" for name, _value in fake.calls)
    assert not any(name == "rerun" for name, _value in fake.calls)


def test_initialize_startup_rejects_invalid_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bad_data_dir = tmp_path / "data-file"
    bad_data_dir.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("SMART_ORGANIZER_DATA_DIR", str(bad_data_dir))

    with pytest.raises(StartupError) as excinfo:
        initialize_startup(tmp_path / "source")

    assert excinfo.value.stage == "runtime-directory validation"
