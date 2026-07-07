from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RELEASE_OUTPUT_DIR = "release_ci"
VALIDATION_ZIP_NAME = "smart_organizer-release-validation.zip"

RUNTIME_RELEASE_ALLOWLIST_GROUPS: dict[str, tuple[str, ...]] = {
    "app_entry": (
        "app.py",
        "app_main.py",
    ),
    "core_modules": (
        "core.py",
        "core_metadata.py",
        "core_utils.py",
        "core_classification.py",
        "core_processor.py",
        "processors/__init__.py",
        "processors/dependency_status.py",
        "processors/image_processor.py",
        "processors/llm_summary.py",
        "processors/metadata_contract.py",
        "processors/optional_deps.py",
        "processors/pdf_processor.py",
        "processors/video_processor.py",
        "supported_formats.py",
    ),
    "service_modules": (
        "services.py",
        "services_models.py",
        "services_analysis.py",
        "services_review.py",
        "services_finalize.py",
        "async_processor.py",
        "contracts.py",
        "frontend_safety.py",
        "logging_config.py",
        "topic_taxonomy.py",
        "upload_validation.py",
        "version.py",
        "i18n.py",
        "i18n_core.py",
    ),
    "storage_modules": (
        "storage.py",
        "storage_base.py",
        "storage_schema.py",
        "storage_repository.py",
        "storage_recovery.py",
        "storage_search.py",
        "storage_cleanup.py",
        "storage_manager.py",
        "config.py",
    ),
    "ui_modules": (
        "ui_common.py",
        "ui_state.py",
        "ui_home.py",
        "ui_labels.py",
        "ui_upload.py",
        "ui_review.py",
        "ui_execute.py",
        "ui_search.py",
        "ui_records.py",
        "ui_renderers.py",
    ),
    "folder_modules": (
        "folder_models.py",
        "folder_organizer.py",
        "folder_service.py",
        "folder_report.py",
        "report_exports.py",
        "malware_scanner.py",
    ),
    "runtime_docs_and_helpers": (
        "requirements.txt",
        "README.md",
        "README.zh-TW.md",
        "RELEASE_PACKAGING.md",
        "RUN_RELEASE.md",
        "scripts/create_demo_folder.py",
        "docs/KNOWN_LIMITATIONS.md",
        "docs/PORTFOLIO_CASE_STUDY.md",
        "locales/zh-TW.json",
        "locales/en.json",
    ),
}

SOURCE_ONLY_RELEASE_FILES: tuple[str, ...] = (
    "scripts/__init__.py",
    "scripts/build_release_zip.py",
    "scripts/check_workspace_clean.py",
    "scripts/conflict_markers.py",
    "scripts/create_release_zip.py",
    "scripts/release_policy.py",
    "scripts/safe_compileall.py",
    "scripts/validate_release_source.py",
    "scripts/verify_release_zip.py",
)

RUNTIME_RELEASE_ALLOWLIST: tuple[str, ...] = tuple(
    path
    for group in RUNTIME_RELEASE_ALLOWLIST_GROUPS.values()
    for path in group
)

FORBIDDEN_RELEASE_PATTERNS: tuple[str, ...] = (
    ".git/",
    "release/",
    "release_ci*/",
    "*.zip",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".venv/",
    "venv/",
    "*.pyc",
    "*.db",
    "*.db-*",
    "*.sqlite",
    "*.sqlite-*",
    "*.sqlite3",
    "*.sqlite3-*",
    "*-journal",
    "*-wal",
    "*-shm",
    "uploads/",
    "demo_files/",
    "repo/",
    "previews/",
    "tmp/",
    "tmp_*",
    "logs/",
    "coverage/",
    "dist/",
    "build/",
    "node_modules/",
    "*.onnx",
    "*.pt",
    "*.pth",
    "*.bin",
    "tests/_tmp*/",
    ".coverage",
    "htmlcov/",
)

WORKSPACE_FORBIDDEN_DIR_PATTERNS: tuple[str, ...] = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".compileall_cache",
    "uploads",
    "repo",
    "release",
    "dist",
    "build",
    "demo_files",
    "logs",
    "coverage",
    "htmlcov",
    ".pytest_runtime_tmp*",
    "tmp",
    "tmp_*",
)

WORKSPACE_FORBIDDEN_FILE_PATTERNS: tuple[str, ...] = (
    "*.pyc",
    "*.pyc.*",
    "*.pyo",
    "*.pyd",
    "*.db",
    "*.db-*",
    "*.sqlite",
    "*.sqlite-*",
    "*.sqlite3",
    "*.sqlite3-*",
    "*-journal",
    "*-wal",
    "*-shm",
    "*.zip",
    ".coverage",
)

CONTROLLED_RELEASE_OUTPUT_ROOT_PATTERNS: tuple[str, ...] = ("release_ci*",)
ALLOWED_CONTROLLED_RELEASE_FILE_PATTERNS: tuple[str, ...] = ("*.zip", ".gitkeep")
SKIP_ROOT_DIRS = {".git", ".github", ".venv", "venv", "node_modules"}


def normalize_relative_path(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def is_runtime_release_file(path: str | Path) -> bool:
    return normalize_relative_path(path) in RUNTIME_RELEASE_ALLOWLIST


def is_source_only_release_file(path: str | Path) -> bool:
    return normalize_relative_path(path) in SOURCE_ONLY_RELEASE_FILES


def _matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(value, pattern) for pattern in patterns)


def is_allowed_controlled_release_output(path: Path, *, project_root: Path = PROJECT_ROOT) -> bool:
    relative = path.relative_to(project_root)
    parts = relative.parts
    if not parts:
        return False
    root_name = parts[0]
    if not _matches_any(root_name, CONTROLLED_RELEASE_OUTPUT_ROOT_PATTERNS):
        return False
    if len(parts) == 1:
        return path.is_dir()
    if path.is_dir():
        return False
    return _matches_any(path.name, ALLOWED_CONTROLLED_RELEASE_FILE_PATTERNS)


def release_forbidden_entries(entries: Iterable[str]) -> list[str]:
    hits: list[str] = []
    for name in entries:
        normalized = normalize_relative_path(name)
        parts = [part for part in normalized.split("/") if part]
        for pattern in FORBIDDEN_RELEASE_PATTERNS:
            stripped = pattern.rstrip("/")
            if fnmatch.fnmatch(normalized, pattern):
                hits.append(normalized)
                break
            if "/" not in stripped and "*" not in stripped and stripped in parts:
                hits.append(normalized)
                break
            if pattern.endswith("/") and stripped in parts:
                hits.append(normalized)
                break
    return hits
