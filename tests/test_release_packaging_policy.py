from __future__ import annotations

import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "create_release_zip.py"


def _load_release_script():
    spec = importlib.util.spec_from_file_location("release_script_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_allowlist_is_importable_and_contains_runtime_files():
    module = _load_release_script()
    allowlist = list(module.RELEASE_ALLOWLIST)
    required = {
        "app_main.py",
        "core.py",
        "storage.py",
        "config.py",
        "supported_formats.py",
        "ui_common.py",
        "ui_home.py",
        "ui_labels.py",
        "folder_models.py",
        "folder_organizer.py",
        "folder_service.py",
        "folder_report.py",
        "report_exports.py",
        "scripts/check_workspace_clean.py",
        "docs/KNOWN_LIMITATIONS.md",
        "docs/PORTFOLIO_CASE_STUDY.md",
    }
    assert required.issubset(set(allowlist))
    assert "compileall.py" not in allowlist


def test_release_packaging_docs_match_current_policy():
    module = _load_release_script()
    allowlist = set(module.RELEASE_ALLOWLIST)
    packaging = (PROJECT_ROOT / "RELEASE_PACKAGING.md").read_text(encoding="utf-8")
    run_release = (PROJECT_ROOT / "RUN_RELEASE.md").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    ps1 = (PROJECT_ROOT / "create_release_zip.ps1").read_text(encoding="utf-8-sig")

    for expected in ["app.py", "app_main.py", "config.py", "docs/KNOWN_LIMITATIONS.md", "requirements.txt"]:
        assert expected in allowlist
        assert expected in packaging

    assert "python scripts/create_release_zip.py" in readme
    assert "python scripts/create_release_zip.py" in run_release
    assert "python -m pip install -r requirements.txt" in readme
    assert "python -m pip install -r requirements.txt" in run_release
    assert "streamlit run app.py" in readme
    assert "streamlit run app.py" in run_release
    assert "$includePaths" not in ps1
    assert "python scripts/create_release_zip.py" in ps1 or "scripts\\create_release_zip.py" in ps1


def test_release_validation_commands_are_consistent_and_cache_safe():
    docs = [
        (PROJECT_ROOT / "README.md").read_text(encoding="utf-8"),
        (PROJECT_ROOT / "RUN_RELEASE.md").read_text(encoding="utf-8"),
        (PROJECT_ROOT / "RELEASE_PACKAGING.md").read_text(encoding="utf-8"),
    ]
    required_commands = [
        "python scripts/safe_compileall.py -q .",
        "python -m ruff check .",
        "python -m mypy",
        "python -m pytest",
        "python scripts/create_release_zip.py --output-dir release_ci",
        "python scripts/verify_release_zip.py release_ci/*.zip",
        "python scripts/check_workspace_clean.py --project-root .",
    ]

    for content in docs:
        for command in required_commands:
            assert command in content
        assert "python -m compileall -q ." not in content
