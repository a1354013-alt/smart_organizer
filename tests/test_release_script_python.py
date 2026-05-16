from __future__ import annotations

import zipfile

from scripts.create_release_zip import (
    RELEASE_ALLOWLIST,
    build_zip,
    get_version,
    zip_contains_forbidden_entries,
)
from scripts.verify_release_zip import resolve_zip_paths


def test_python_release_script_builds_clean_zip(tmp_path):
    zip_path = build_zip(tmp_path, "package.zip")
    assert zip_path.exists()
    assert not zip_contains_forbidden_entries(zip_path)
    assert zip_path.name == "package.zip"
    assert "README.md" in RELEASE_ALLOWLIST

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert not any(name.endswith(".zip") for name in names)
    assert not any(name.startswith("release/") for name in names)
    assert not any(name.startswith("release_ci") for name in names)
    assert not any(name.startswith(".git/") for name in names)
    assert not any(name.startswith("uploads/") for name in names)
    assert not any(name.startswith("repo/") for name in names)
    assert not any(name.endswith(".db") for name in names)
    assert "app_main.py" in names
    assert "core.py" in names
    assert "storage.py" in names
    assert "config.py" in names
    assert "supported_formats.py" in names
    assert "ui_common.py" in names
    assert "ui_home.py" in names
    assert "ui_labels.py" in names
    assert "folder_models.py" in names
    assert "folder_organizer.py" in names
    assert "folder_service.py" in names
    assert "folder_report.py" in names
    assert "report_exports.py" in names
    assert "scripts/check_workspace_clean.py" in names
    assert "docs/KNOWN_LIMITATIONS.md" in names
    assert "docs/PORTFOLIO_CASE_STUDY.md" in names


def test_get_version_uses_static_parsing(monkeypatch):
    import scripts.create_release_zip as release_script

    monkeypatch.setattr(
        release_script.Path,
        "read_text",
        lambda self, encoding="utf-8": "__version__ = '9.9.9'\nraise RuntimeError('should not execute')\n",
    )

    assert get_version() == "9.9.9"


def test_verify_release_zip_expands_glob_patterns(tmp_path):
    zip_path = build_zip(tmp_path, "package.zip")

    matches = resolve_zip_paths(str(tmp_path / "*.zip"))

    assert matches == [zip_path]
