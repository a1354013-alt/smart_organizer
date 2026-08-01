"""
Release Hygiene Tests - Ensure release packages don't contain dev artifacts.

These tests verify that release/build directories don't contain:
- .coverage files
- __pycache__ directories
- .pyc files
- tests/_tmp_pytest/ directories
- .pytest_cache/ directories
- .mypy_cache/ directories
- .ruff_cache/ directories
- .git directories
"""

import os
from pathlib import Path

FORBIDDEN_PATTERNS = [
    ".coverage",
    ".coverage.*",
    "coverage.xml",
    "htmlcov/",
    "__pycache__",
    "*.pyc",
    "tests/_tmp_pytest/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".git/",
]


def get_release_directories():
    """Get list of potential release/build directories."""
    workspace = Path(__file__).parent.parent
    candidates = []

    # Check common release directory names
    for name in ["release", "dist", "build", "_release", "output"]:
        path = workspace / name
        if path.exists() and path.is_dir():
            candidates.append(path)

    return candidates


def scan_for_forbidden_items(directory: Path):
    """Scan directory for forbidden patterns."""
    violations = []

    for root, dirs, files in os.walk(directory):
        # Check directories
        for d in dirs[:]:  # Use slice to allow modification during iteration
            dir_path = Path(root) / d
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.endswith("/"):
                    # Directory pattern
                    if d == pattern.rstrip("/") or dir_path.match(f"*{pattern.rstrip('/')}"):
                        violations.append(str(dir_path))
                elif pattern == "__pycache__" and d == "__pycache__":
                    violations.append(str(dir_path))
        
        # Check files
        for f in files:
            file_path = Path(root) / f
            for pattern in FORBIDDEN_PATTERNS:
                if pattern == ".coverage" and f == ".coverage" or pattern.endswith(".pyc") and f.endswith(".pyc") or pattern == ".git/" and f.startswith(".git"):
                    violations.append(str(file_path))

    return violations


class TestReleaseHygiene:
    """Test suite for release package hygiene."""

    def test_no_forbidden_artifacts_in_release_dirs(self):
        """Verify release directories don't contain forbidden artifacts."""
        release_dirs = get_release_directories()

        if not release_dirs:
            # No release directories found, skip check
            return

        all_violations = []
        for release_dir in release_dirs:
            violations = scan_for_forbidden_items(release_dir)
            all_violations.extend(violations)

        assert len(all_violations) == 0, (
            f"Found {len(all_violations)} forbidden artifact(s) in release directories:\n"
            + "\n".join(f"  - {v}" for v in all_violations)
        )
    
    def test_gitignore_exists_and_valid(self):
        """Verify .gitignore exists and has valid syntax."""
        workspace = Path(__file__).parent.parent
        gitignore_path = workspace / ".gitignore"

        assert gitignore_path.exists(), ".gitignore file not found"

        content = gitignore_path.read_text()

        # Check for markdown code fences (common mistake)
        assert "```" not in content, (
            ".gitignore contains markdown code fences (```). "
            "This is invalid syntax."
        )
        
        # Check for required patterns
        required_patterns = [
            "__pycache__",
            ".coverage",
            ".coverage.*",
            "*.pyc",
        ]

        for pattern in required_patterns:
            assert pattern in content, (
                f".gitignore missing required pattern: {pattern}"
            )

    def test_release_hygiene_rules_cover_pycache_and_tmp_pytest_artifacts(self):
        """Verify the release hygiene policy forbids common generated test artifacts."""
        assert "__pycache__" in FORBIDDEN_PATTERNS
        assert "*.pyc" in FORBIDDEN_PATTERNS
        assert "tests/_tmp_pytest/" in FORBIDDEN_PATTERNS
        assert ".pytest_cache/" in FORBIDDEN_PATTERNS

    def test_tmp_pytest_directory_cleanable(self):
        """Verify tests/_tmp_pytest remains a developer-workspace artifact, not a release requirement."""
        tests_dir = Path(__file__).parent
        tmp_dir = tests_dir / "_tmp_pytest"

        if tmp_dir.exists():
            assert tmp_dir.is_dir(), "tests/_tmp_pytest should be a directory"
        assert "tests/_tmp_pytest/" in FORBIDDEN_PATTERNS
