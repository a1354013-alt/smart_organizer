from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import scripts.check_workspace_clean as clean_script


def test_find_workspace_pollution_detects_forbidden_runtime_artifacts(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(clean_script, "PROJECT_ROOT", tmp_path)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "smart_organizer.db").write_bytes(b"db")
    (tmp_path / ".coverage").write_text("coverage", encoding="utf-8")
    (tmp_path / "demo_files").mkdir()
    (tmp_path / "runtime.zip").write_bytes(b"zip")

    pollution = clean_script.find_workspace_pollution()

    assert tmp_path / "__pycache__" in pollution
    assert tmp_path / "smart_organizer.db" in pollution
    assert tmp_path / ".coverage" in pollution
    assert tmp_path / "demo_files" in pollution
    assert tmp_path / "runtime.zip" in pollution


def test_find_workspace_pollution_detects_parallel_coverage_files(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(clean_script, "PROJECT_ROOT", tmp_path)
    parallel_coverage = tmp_path / ".coverage.worker1"
    parallel_coverage.write_text("coverage", encoding="utf-8")

    pollution = clean_script.find_workspace_pollution()

    assert parallel_coverage in pollution


def test_find_workspace_pollution_allows_release_ci_zip_output(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(clean_script, "PROJECT_ROOT", tmp_path)
    release_dir = tmp_path / "release_ci"
    release_dir.mkdir()
    (release_dir / "smart-organizer.zip").write_bytes(b"zip")

    pollution = clean_script.find_workspace_pollution()

    assert pollution == []


def test_find_workspace_pollution_rejects_non_zip_files_inside_release_ci(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(clean_script, "PROJECT_ROOT", tmp_path)
    release_dir = tmp_path / "release_ci"
    release_dir.mkdir()
    (release_dir / "notes.txt").write_text("not allowed", encoding="utf-8")

    pollution = clean_script.find_workspace_pollution()

    assert pollution == [release_dir / "notes.txt"]


def test_find_workspace_pollution_allows_release_ci_gitkeep(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(clean_script, "PROJECT_ROOT", tmp_path)
    release_dir = tmp_path / "release_ci"
    release_dir.mkdir()
    (release_dir / ".gitkeep").write_text("", encoding="utf-8")

    pollution = clean_script.find_workspace_pollution()

    assert pollution == []


def test_check_workspace_clean_does_not_create_bytecode(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "docs").mkdir()
    (project_root / "docs" / "python_bytecode_notes.md").write_text("notes", encoding="utf-8")
    (project_root / "coverage_notes.md").write_text("notes", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "scripts/check_workspace_clean.py",
            "--project-root",
            str(project_root),
        ],
        cwd=Path(__file__).resolve().parent.parent,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert list(project_root.rglob("__pycache__")) == []
    assert list(project_root.rglob("*.pyc")) == []


def test_check_workspace_clean_rejects_generated_bytecode(tmp_path: Path):
    project_root = tmp_path / "project"
    pycache_dir = project_root / "scripts" / "__pycache__"
    pycache_dir.mkdir(parents=True)
    artifact = pycache_dir / "module.cpython-311.pyc"
    artifact.write_bytes(b"cache")

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "scripts/check_workspace_clean.py",
            "--project-root",
            str(project_root),
        ],
        cwd=Path(__file__).resolve().parent.parent,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "scripts/__pycache__" in result.stderr or "scripts/__pycache__" in result.stdout


def test_check_workspace_clean_succeeds_twice_without_creating_artifacts(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    command = [
        sys.executable,
        "-B",
        "scripts/check_workspace_clean.py",
        "--project-root",
        str(project_root),
    ]
    for _ in range(2):
        result = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parent.parent,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert list(project_root.rglob("__pycache__")) == []
