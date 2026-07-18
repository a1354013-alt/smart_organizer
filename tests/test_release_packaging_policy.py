from __future__ import annotations

import importlib.util
import re
import sys
import zipfile
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
        "runtime_config.py",
        "startup.py",
        "requirements.lock.txt",
        "i18n_core.py",
        "supported_formats.py",
        "ui_common.py",
        "ui_home.py",
        "ui_labels.py",
        "folder_models.py",
        "folder_organizer.py",
        "folder_service.py",
        "folder_report.py",
        "report_exports.py",
        "malware_scanner.py",
        "scripts/create_demo_folder.py",
        "docs/KNOWN_LIMITATIONS.md",
        "docs/PORTFOLIO_CASE_STUDY.md",
    }
    assert required.issubset(set(allowlist))
    assert "compileall.py" not in allowlist
    for source_only_path in (
        "scripts/build_release_zip.py",
        "scripts/check_workspace_clean.py",
        "scripts/cleanup_workspace.py",
        "scripts/cleanup_validation_artifacts.py",
        "scripts/conflict_markers.py",
        "scripts/create_release_zip.py",
        "scripts/regenerate_dependency_locks.py",
        "scripts/release_policy.py",
        "scripts/safe_compileall.py",
        "scripts/validate_dependency_locks.py",
        "scripts/validate_release_source.py",
        "scripts/verify_release_zip.py",
    ):
        assert source_only_path not in allowlist


def test_release_packaging_docs_match_current_policy():
    module = _load_release_script()
    allowlist = set(module.RELEASE_ALLOWLIST)
    packaging = (PROJECT_ROOT / "RELEASE_PACKAGING.md").read_text(encoding="utf-8")
    run_release = (PROJECT_ROOT / "RUN_RELEASE.md").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    ps1 = (PROJECT_ROOT / "create_release_zip.ps1").read_text(encoding="utf-8-sig")

    for expected in [
        "app.py",
        "app_main.py",
        "config.py",
        "runtime_config.py",
        "startup.py",
        "docs/KNOWN_LIMITATIONS.md",
        "requirements.txt",
        "requirements.lock.txt",
    ]:
        assert expected in allowlist
        assert expected in packaging

    assert "python -B scripts/validate_release_source.py" in run_release
    assert "python -m pip install -r requirements.lock.txt" in readme
    assert "requirements-dev.txt" not in readme
    assert "Source Repository Release Validation" in readme
    assert "RUN_RELEASE.md" in readme
    assert "python -m pip install -r requirements.lock.txt" in run_release
    assert "streamlit run app.py" in readme
    assert "streamlit run app.py" in run_release
    assert "$includePaths" not in ps1
    assert "-B" in ps1
    assert "scripts\\create_release_zip.py" in ps1
    assert "source-only scripts" in packaging
    assert "source-only scripts" in run_release


def test_release_validation_commands_are_consistent_and_cache_safe():
    from scripts.validate_release_source import build_validation_commands

    docs = [
        (PROJECT_ROOT / "RUN_RELEASE.md").read_text(encoding="utf-8"),
        (PROJECT_ROOT / "RELEASE_PACKAGING.md").read_text(encoding="utf-8"),
    ]
    command_text = "\n".join(" ".join(command[1:]) for command in build_validation_commands())
    required_commands = [
        "-B scripts/validate_dependency_locks.py --mode static",
        "-B scripts/safe_compileall.py -q .",
        "-m ruff check --no-cache .",
        "-m mypy --cache-dir=/dev/null",
        "-W error::ResourceWarning -m pytest -q tests/test_storage_db_schema.py tests/test_runtime_config.py tests/test_storage.py tests/test_app_bootstrap.py",
        "-m pytest -q --cov=. --cov-branch --cov-report=term-missing --cov-report=xml",
        "-m pip_audit -r requirements.lock.txt",
        "-B scripts/create_release_zip.py --output-dir release_ci --zip-name smart_organizer-release-validation.zip",
        "-B scripts/verify_release_zip.py release_ci/smart_organizer-release-validation.zip",
        "-B scripts/cleanup_workspace.py",
        "-B scripts/check_workspace_clean.py --project-root .",
    ]

    for content in docs:
        assert "python -B scripts/validate_release_source.py" in content
        assert "Source repository only, not included in runtime release zip." in content
        assert "source-only scripts stay in the source repository" in content
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
        "python -B scripts/validate_release_source.py --check-conflicts-only",
        "python -B scripts/validate_dependency_locks.py --mode static",
        "python -B scripts/safe_compileall.py -q .",
        "python -m ruff check --no-cache .",
        "python -m mypy --cache-dir=/dev/null",
        "python -W error::ResourceWarning -m pytest -q tests/test_storage_db_schema.py tests/test_runtime_config.py tests/test_storage.py tests/test_app_bootstrap.py",
        "python -m pytest -q --cov=. --cov-branch --cov-report=term-missing --cov-report=xml",
        "python -m pip_audit -r requirements.lock.txt",
        "python -B scripts/create_release_zip.py --output-dir release_ci --zip-name smart_organizer-release-validation.zip",
        "python -B scripts/verify_release_zip.py release_ci/smart_organizer-release-validation.zip",
        "python -B scripts/cleanup_workspace.py",
        "python -B scripts/check_workspace_clean.py --project-root .",
    ]

    for command in expected_commands:
        assert f"$ {command}" in output


def test_release_validation_commands_include_cache_safe_tool_options():
    from scripts.validate_release_source import build_validation_commands

    command_text = "\n".join(" ".join(command) for command in build_validation_commands())

    assert f"{sys.executable} -m ruff check --no-cache ." in command_text
    assert f"{sys.executable} -m mypy --cache-dir=/dev/null" in command_text


def test_release_validation_verifies_only_the_current_zip():
    from scripts.validate_release_source import VALIDATION_ZIP_NAME, build_validation_commands

    command_text = "\n".join(" ".join(command) for command in build_validation_commands())

    assert f"--zip-name {VALIDATION_ZIP_NAME}" in command_text
    assert f"release_ci/{VALIDATION_ZIP_NAME}" in command_text
    assert "release_ci/*.zip" not in command_text


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
        PROJECT_ROOT / "RUN_RELEASE.md",
        PROJECT_ROOT / "RELEASE_PACKAGING.md",
    ]

    for path in docs:
        content = path.read_text(encoding="utf-8")
        assert "python -B scripts/validate_release_source.py" in content
        assert "Source repository only, not included in runtime release zip." in content


def test_release_readme_references_only_files_in_runtime_zip(tmp_path: Path):
    from scripts.create_release_zip import build_zip

    zip_path = build_zip(tmp_path, "runtime-doc-check.zip")
    extract_dir = tmp_path / "extracted"

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        archive.extractall(extract_dir)

    readme = (extract_dir / "README.md").read_text(encoding="utf-8")
    referenced_files = set(
        re.findall(
            r"(?:requirements[-\w]*\.txt|scripts/[A-Za-z0-9_./-]+\.py|docs/[A-Za-z0-9_./-]+\.md|RUN_RELEASE\.md|RELEASE_PACKAGING\.md|app\.py)",
            readme,
        )
    )

    missing = sorted(path for path in referenced_files if path not in names)
    assert missing == []
    assert "requirements-dev.txt" not in readme
    assert "Source Repository Release Validation" in readme
    assert "scripts/create_release_zip.py" not in readme
    assert "scripts/verify_release_zip.py" not in readme
    assert "scripts/validate_release_source.py" not in readme

    for doc_name in ("RUN_RELEASE.md", "RELEASE_PACKAGING.md"):
        content = (extract_dir / doc_name).read_text(encoding="utf-8")
        assert "python -B scripts/validate_release_source.py" in content
        assert "Source repository only, not included in runtime release zip." in content
