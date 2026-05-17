from __future__ import annotations

import subprocess
import sys
import time
import zipfile
from pathlib import Path

from scripts.create_release_zip import (
    RELEASE_ALLOWLIST,
    build_zip,
    get_version,
    zip_contains_forbidden_entries,
)
from scripts.validate_release_source import run_step
from scripts.verify_release_zip import resolve_zip_paths, verify_release_zip

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def test_verify_release_zip_rejects_forbidden_and_extra_entries(tmp_path: Path):
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("app.py", "print('ok')\n")
        archive.writestr("__pycache__/bad.pyc", b"cached")

    try:
        verify_release_zip(zip_path)
    except ValueError as exc:
        assert "forbidden paths" in str(exc)
    else:
        raise AssertionError("Expected forbidden zip entry to fail verification")


def test_extracted_release_zip_smoke_imports_app_main(tmp_path: Path):
    output_dir = tmp_path / "release"
    extract_dir = tmp_path / "extracted"

    subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "create_release_zip.py"),
            "--output-dir",
            str(output_dir),
            "--zip-name",
            "smart-organizer-runtime-demo.zip",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )

    zip_path = output_dir / "smart-organizer-runtime-demo.zip"
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        archive.extractall(extract_dir)

    forbidden_roots = {
        ".github",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "logs",
        "node_modules",
        "previews",
        "repo",
        "release",
        "tests",
        "tmp",
        "uploads",
        "venv",
    }
    forbidden_suffixes = (".db", ".sqlite", ".sqlite3", ".pyc")
    required_files = {
        "app.py",
        "app_main.py",
        "requirements.txt",
        "RUN_RELEASE.md",
    }

    assert required_files.issubset(names)
    assert not any(Path(name).parts[0] in forbidden_roots for name in names)
    assert not any(name.endswith(forbidden_suffixes) for name in names)

    subprocess.run(
        [sys.executable, "-c", "import app_main"],
        cwd=extract_dir,
        check=True,
    )


def test_validate_release_run_step_streams_success(capsys):
    returncode = run_step(
        [sys.executable, "-c", "print('release validation alive')"],
        timeout_seconds=5,
        timeout_tail_lines=5,
    )

    captured = capsys.readouterr()
    assert returncode == 0
    assert "START" in captured.out
    assert "release validation alive" in captured.out
    assert "END" in captured.out


def test_validate_release_run_step_times_out_with_tail(capsys):
    returncode = run_step(
        [sys.executable, "-c", "import time; print('last visible line', flush=True); time.sleep(10)"],
        timeout_seconds=1,
        timeout_tail_lines=5,
    )

    captured = capsys.readouterr()
    assert returncode == 124
    assert "TIMEOUT" in captured.err
    assert "last visible line" in captured.err


def test_validate_release_run_step_times_out_with_partial_line(capsys):
    started = time.perf_counter()
    returncode = run_step(
        [
            sys.executable,
            "-c",
            "import sys, time; sys.stdout.write('partial stdout'); sys.stdout.flush(); time.sleep(10)",
        ],
        timeout_seconds=1,
        timeout_tail_lines=5,
    )
    duration = time.perf_counter() - started

    captured = capsys.readouterr()
    assert returncode == 124
    assert duration < 3
    assert "partial stdout" in captured.out
    assert "TIMEOUT" in captured.err
    assert "[stdout] partial stdout" in captured.err
