from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_DIR_NAMES = {"tmp_test_write", "__pycache__"}
FORBIDDEN_FILE_PATTERNS = ("*.pyc", "*.pyc.*")
REQUIRED_GITIGNORE_RULES = [
    "__pycache__/",
    "*.pyc",
    "*.pyc*",
    "*.pyo",
    "*.pyd",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".coverage",
    "coverage/",
    "htmlcov/",
    "tmp_test_write/",
    "tests/_tmp*/",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.log",
    ".env",
    ".env.*",
    "uploads/",
    "repo/",
    "dist/",
    "build/",
]
REQUIRED_GITATTR_RULES = [
    "__pycache__/ export-ignore",
    "*.pyc export-ignore",
    "*.pyc* export-ignore",
    ".pytest_cache/ export-ignore",
    ".mypy_cache/ export-ignore",
    ".ruff_cache/ export-ignore",
    ".coverage export-ignore",
    "coverage/ export-ignore",
    "htmlcov/ export-ignore",
    "tmp_test_write/ export-ignore",
    "tests/_tmp*/ export-ignore",
    "uploads/ export-ignore",
    "repo/ export-ignore",
    "*.db export-ignore",
    "*.sqlite export-ignore",
    "*.sqlite3 export-ignore",
    "*.log export-ignore",
    ".env export-ignore",
    ".env.* export-ignore",
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
    script = PROJECT_ROOT / "create_release_zip.ps1"
    if not script.exists():
        return

    release_dir = tmp_path / "release"
    zip_name = "cleanliness-check.zip"
    subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-OutputDir",
            str(release_dir),
            "-ZipName",
            zip_name,
        ],
        check=True,
        cwd=PROJECT_ROOT,
        capture_output=True,
        timeout=60,
    )

    zip_path = release_dir / zip_name
    assert zip_path.exists()
    forbidden_fragments = [
        "__pycache__",
        ".pyc",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "tmp_test_write",
        "tests/_tmp",
        "uploads/",
        "repo/",
    ]
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    for fragment in forbidden_fragments:
        assert not any(fragment in name for name in names), f"forbidden zip entry matched: {fragment}"
