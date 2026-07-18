from __future__ import annotations

from pathlib import Path

from scripts.validate_dependency_locks import _package_names

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_ci_matrix_includes_windows_ubuntu_and_supported_python_versions():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "dependency-lock-determinism:" in workflow
    assert "Dependency Lock Determinism" in workflow
    assert 'PYTHONDONTWRITEBYTECODE: "1"' in workflow
    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert '"3.11"' in workflow
    assert '"3.12"' in workflow
    assert "fail-fast: false" in workflow
    assert "continue-on-error" not in workflow
    assert "requirements-dev.lock.txt" in workflow
    assert "python -B scripts/validate_dependency_locks.py --mode regenerate" in workflow
    assert "python -B scripts/validate_dependency_locks.py --mode static" in workflow
    assert "Repository unchanged check" in workflow
    assert "Cleanup generated workspace artifacts" in workflow
    assert "python -B scripts/check_workspace_clean.py --project-root ." in workflow
    assert "error::ResourceWarning" in workflow
    assert "pip_audit" in workflow
    assert "--cov-branch" in workflow


def test_dependabot_and_codeql_configs_are_present_and_minimal():
    dependabot = (PROJECT_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    codeql = (PROJECT_ROOT / ".github" / "workflows" / "codeql.yml").read_text(encoding="utf-8")

    assert 'package-ecosystem: "pip"' in dependabot
    assert 'package-ecosystem: "github-actions"' in dependabot
    assert "security-events: write" in codeql
    assert "contents: read" in codeql
    assert "github/codeql-action/init@v4" in codeql


def test_lock_files_exist_and_runtime_lock_excludes_dev_tools():
    runtime_lock = PROJECT_ROOT / "requirements.lock.txt"
    dev_lock = PROJECT_ROOT / "requirements-dev.lock.txt"

    assert runtime_lock.exists()
    assert dev_lock.exists()
    runtime_names = _package_names(runtime_lock)
    dev_names = _package_names(dev_lock)

    assert "streamlit" in runtime_names
    assert "platformdirs" in runtime_names
    assert "pytest" not in runtime_names
    assert "ruff" not in runtime_names
    assert {"pytest", "pytest-cov", "ruff", "mypy", "pip-audit", "pip-tools"}.issubset(dev_names)


def test_coverage_configuration_enforces_branch_threshold():
    coverage = (PROJECT_ROOT / ".coveragerc").read_text(encoding="utf-8")

    assert "branch = True" in coverage
    assert "fail_under = 75" in coverage
    assert "tests/*" in coverage
    assert "runtime_config.py" not in coverage


def test_pytest_configuration_does_not_use_unknown_asyncio_setting():
    pytest_ini = (PROJECT_ROOT / "pytest.ini").read_text(encoding="utf-8")

    assert "asyncio_default_fixture_loop_scope" not in pytest_ini
