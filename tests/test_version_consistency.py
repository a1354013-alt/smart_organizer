from __future__ import annotations

from pathlib import Path


def test_version_is_single_source_and_consistent():
    # Single source of truth
    from version import __version__, APP_TITLE

    assert __version__
    assert f"v{__version__}" in APP_TITLE

    readme = Path("README.md").read_text(encoding="utf-8")
    assert f"(v{__version__}" in readme, "README version must match version.py"

    # App UI should not hardcode old versions
    app_py = Path("app.py").read_text(encoding="utf-8")
    assert "v2.7." not in app_py, "App should not hardcode version literals"
    assert "APP_TITLE" in app_py, "App should render version from version.py"

    ps1 = Path("create_release_zip.ps1").read_text(encoding="utf-8-sig")
    assert "version.py" in ps1, "Release script must include version.py"
    assert "Get-ProjectVersion" in ps1, "Release zip naming must read version from version.py"
