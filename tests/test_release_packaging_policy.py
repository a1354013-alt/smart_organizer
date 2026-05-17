from __future__ import annotations

import importlib.util
import sys
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

    assert "python scripts/validate_release_source.py" in readme
    assert "python scripts/validate_release_source.py" in run_release
    assert "python -m pip install -r requirements.txt" in readme
    assert "python -m pip install -r requirements.txt" in run_release
    assert "streamlit run app.py" in readme
    assert "streamlit run app.py" in run_release
    assert "$includePaths" not in ps1
    assert "python scripts/create_release_zip.py" in ps1 or "scripts\\create_release_zip.py" in ps1


def test_release_validation_commands_are_consistent_and_cache_safe():
    from scripts.validate_release_source import build_validation_commands

    docs = [
        (PROJECT_ROOT / "README.md").read_text(encoding="utf-8"),
        (PROJECT_ROOT / "RUN_RELEASE.md").read_text(encoding="utf-8"),
        (PROJECT_ROOT / "RELEASE_PACKAGING.md").read_text(encoding="utf-8"),
    ]
    command_text = "\n".join(" ".join(command[1:]) for command in build_validation_commands())
    required_commands = [
        "scripts/safe_compileall.py -q .",
        "-m ruff check --no-cache .",
        "-m mypy --cache-dir=/dev/null",
        "-m pytest -q",
        "scripts/create_release_zip.py --output-dir release_ci",
        "scripts/verify_release_zip.py release_ci/*.zip",
        "scripts/check_workspace_clean.py --project-root .",
    ]

    for content in docs:
        assert "python scripts/validate_release_source.py" in content
        assert "python -m compileall -q ." not in content
        assert "python -m ruff check ." not in content
        assert "python -m mypy\n" not in content

    for command in required_commands:
        assert command in command_text

    assert "--no-cache" in command_text
    assert "--cache-dir=/dev/null" in command_text


def test_release_validation_dry_run_lists_expected_commands(capsys):
    from scripts.validate_release_source import main

    assert main(["--dry-run"]) == 0

    output = capsys.readouterr().out
    expected_commands = [
        "python scripts/safe_compileall.py -q .",
        "python -m ruff check --no-cache .",
        "python -m mypy --cache-dir=/dev/null",
        "python -m pytest -q",
        "python scripts/create_release_zip.py --output-dir release_ci",
        "python scripts/verify_release_zip.py release_ci/*.zip",
        "python scripts/check_workspace_clean.py --project-root .",
    ]

    for command in expected_commands:
        assert f"$ {command}" in output


def test_release_validation_commands_include_cache_safe_tool_options():
    from scripts.validate_release_source import build_validation_commands

    command_text = "\n".join(" ".join(command) for command in build_validation_commands())

    assert f"{sys.executable} -m ruff check --no-cache ." in command_text
    assert f"{sys.executable} -m mypy --cache-dir=/dev/null" in command_text


def test_release_validation_timeout_reports_command(monkeypatch, capsys):
    import scripts.validate_release_source as validate_release_source

    timed_out_command = [sys.executable, "-m", "mypy", "--cache-dir=/dev/null"]

    def fake_build_validation_commands(output_dir: str = "release_ci") -> list[list[str]]:
        return [timed_out_command]

    def fake_run_step(command: list[str], *, timeout_seconds: int, timeout_tail_lines: int) -> int:
        assert command == timed_out_command
        assert timeout_seconds > 0
        assert timeout_tail_lines > 0
        print("ERROR: command timed out after 180s: python -m mypy --cache-dir=/dev/null", file=sys.stderr)
        return 124

    monkeypatch.setattr(validate_release_source, "build_validation_commands", fake_build_validation_commands)
    monkeypatch.setattr(validate_release_source, "run_step", fake_run_step)

    assert validate_release_source.main([]) != 0

    captured = capsys.readouterr()
    assert "$ python -m mypy --cache-dir=/dev/null" in captured.out
    assert "timed out" in captured.err
    assert "python -m mypy --cache-dir=/dev/null" in captured.err


def test_release_validation_docs_reference_single_entrypoint():
    docs = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "RUN_RELEASE.md",
        PROJECT_ROOT / "RELEASE_PACKAGING.md",
    ]

    for path in docs:
        assert "python scripts/validate_release_source.py" in path.read_text(encoding="utf-8")
