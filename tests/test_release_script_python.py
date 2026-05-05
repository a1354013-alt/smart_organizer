from __future__ import annotations

from scripts.create_release_zip import RELEASE_ALLOWLIST, build_zip, zip_contains_forbidden_entries


def test_python_release_script_builds_clean_zip(tmp_path):
    zip_path = build_zip(tmp_path, "package.zip")
    assert zip_path.exists()
    assert not zip_contains_forbidden_entries(zip_path)
    assert zip_path.name == "package.zip"
    assert "README.md" in RELEASE_ALLOWLIST
