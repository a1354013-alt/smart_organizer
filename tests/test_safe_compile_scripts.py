from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts import safe_compileall

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_safe_compileall_compiles_without_creating_pycache(tmp_path: Path):
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")

    assert safe_compileall._compile_targets(  # type: ignore[attr-defined]
        object(),
        [str(tmp_path)],
        quiet=2,
        force=False,
        legacy=True,
        recurse=True,
    )
    assert not (tmp_path / "__pycache__").exists()


def test_safe_compileall_reports_syntax_error(tmp_path: Path):
    source = tmp_path / "broken.py"
    source.write_text("def broken(:\n", encoding="utf-8")

    assert not safe_compileall._compile_targets(  # type: ignore[attr-defined]
        object(),
        [str(tmp_path)],
        quiet=2,
        force=False,
        legacy=True,
        recurse=True,
    )


def test_safe_compile_wrapper_defaults_to_project_root():
    before = {path.resolve() for path in PROJECT_ROOT.rglob("__pycache__")}
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "safe_compile.py"), "-q"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    after = {path.resolve() for path in PROJECT_ROOT.rglob("__pycache__")}
    assert after == before
