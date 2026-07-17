from __future__ import annotations

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
