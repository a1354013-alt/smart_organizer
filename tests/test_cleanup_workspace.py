from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import scripts.cleanup_workspace as cleanup_script


def test_cleanup_workspace_removes_generated_artifacts_without_touching_source_files(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    keep_py = project_root / "module.py"
    keep_lock = project_root / "requirements.lock.txt"
    keep_py.write_text("value = 1\n", encoding="utf-8")
    keep_lock.write_text("locked\n", encoding="utf-8")

    (project_root / "__pycache__").mkdir()
    (project_root / "__pycache__" / "module.cpython-311.pyc").write_bytes(b"cache")
    (project_root / "scripts" / "__pycache__").mkdir(parents=True)
    (project_root / "scripts" / "__pycache__" / "tool.cpython-311.pyc").write_bytes(b"cache")
    (project_root / "module.pyo").write_bytes(b"optimized")
    (project_root / ".coverage").write_text("coverage", encoding="utf-8")
    (project_root / "coverage.xml").write_text("<coverage />", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "scripts/cleanup_workspace.py",
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
    assert list(project_root.rglob("*.pyo")) == []
    assert not (project_root / ".coverage").exists()
    assert not (project_root / "coverage.xml").exists()
    assert keep_py.exists()
    assert keep_lock.exists()


def test_cleanup_workspace_main_accepts_project_root(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    artifact = project_root / ".ruff_cache"
    artifact.mkdir()

    assert cleanup_script.main(["--project-root", str(project_root)]) == 0
    assert not artifact.exists()
