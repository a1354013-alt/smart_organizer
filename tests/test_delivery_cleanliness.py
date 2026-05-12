from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

from scripts.create_release_zip import (
    FORBIDDEN_PATTERNS,
    RELEASE_ALLOWLIST,
    build_zip,
    zip_contains_forbidden_entries,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_DIR_NAMES = {"tmp_test_write", ".compileall_cache"}
FORBIDDEN_FILE_PATTERNS: tuple[str, ...] = ()
REQUIRED_GITIGNORE_RULES = [
    "release/",
    "release_ci*/",
    "*.zip",
    "__pycache__/",
    "*.pyc",
    "*.pyc*",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".venv/",
    "venv/",
    "uploads/",
    "repo/",
    "smart_organizer.db",
    "previews/",
    "tmp/",
    "tmp_*/",
    "logs/",
    "dist/",
    "build/",
    "node_modules/",
    "*.db",
    "*.sqlite",
    ".coverage",
    "htmlcov/",
]
REQUIRED_GITATTR_RULES = [
    "release/ export-ignore",
    "release_ci*/ export-ignore",
    "*.zip export-ignore",
    "__pycache__/ export-ignore",
    "*.pyc export-ignore",
    "*.pyc* export-ignore",
    ".pytest_cache/ export-ignore",
    ".mypy_cache/ export-ignore",
    ".ruff_cache/ export-ignore",
    "uploads/ export-ignore",
    "repo/ export-ignore",
    "previews/ export-ignore",
    "tmp/ export-ignore",
    "tmp_*/ export-ignore",
    "dist/ export-ignore",
    "build/ export-ignore",
    "node_modules/ export-ignore",
    "*.db export-ignore",
    "*.sqlite export-ignore",
]


def test_repo_has_no_delivery_pollution():
    for path in PROJECT_ROOT.rglob("*"):
        if path.is_dir() and path.name in FORBIDDEN_DIR_NAMES:
            raise AssertionError(f"forbidden directory exists: {path}")
    for pattern in FORBIDDEN_FILE_PATTERNS:
        matches = list(PROJECT_ROOT.rglob(pattern))
        assert not matches, f"forbidden files exist for {pattern}: {matches[:10]}"


def test_gitignore_contains_required_rules():
    content = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    for rule in REQUIRED_GITIGNORE_RULES:
        assert rule in content, f".gitignore missing rule: {rule}"


def test_gitattributes_contains_export_ignore_rules():
    content = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")
    for rule in REQUIRED_GITATTR_RULES:
        assert rule in content, f".gitattributes missing rule: {rule}"


def test_release_zip_excludes_forbidden_paths(tmp_path: Path):
    zip_path = build_zip(tmp_path / "release", "cleanliness-check.zip")
    assert zip_path.exists()
    assert not zip_contains_forbidden_entries(zip_path)

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()

    assert sorted(names) == sorted(RELEASE_ALLOWLIST)
    for fragment in FORBIDDEN_PATTERNS:
        token = fragment.rstrip("/")
        if "/" in token or "*" in token or "." in token:
            assert not any(token in name for name in names), f"forbidden zip entry matched: {fragment}"
        else:
            assert not any(token in [part for part in name.split("/") if part] for name in names), f"forbidden zip entry matched: {fragment}"


def test_release_zip_extracts_and_app_main_imports(tmp_path: Path):
    zip_path = build_zip(tmp_path / "release", "smoke-check.zip")
    extract_dir = tmp_path / "unzipped"
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)

    extracted_app_main = extract_dir / "app_main.py"
    extracted_app = extract_dir / "app.py"
    assert extracted_app_main.exists()
    assert extracted_app.exists()

    source = extracted_app_main.read_text(encoding="utf-8")
    compile(source, str(extracted_app_main), "exec")

    spec = importlib.util.spec_from_file_location("release_smoke_app_main", extracted_app_main)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(extract_dir))
    try:
        spec.loader.exec_module(module)
        assert hasattr(module, "main")
    finally:
        sys.path = [entry for entry in sys.path if entry != str(extract_dir)]


def test_workspace_no_longer_contains_root_compileall_wrapper():
    assert not (PROJECT_ROOT / "compileall.py").exists()
    assert (PROJECT_ROOT / "scripts" / "safe_compileall.py").exists()
