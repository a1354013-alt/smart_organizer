from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

RELEASE_ALLOWLIST_GROUPS: dict[str, list[str]] = {
    "app_entry": [
        "app.py",
        "app_main.py",
    ],
    "core_modules": [
        "core.py",
        "core_utils.py",
        "core_classification.py",
        "core_processor.py",
    ],
    "service_modules": [
        "services.py",
        "services_models.py",
        "services_analysis.py",
        "services_review.py",
        "services_finalize.py",
        "async_processor.py",
        "contracts.py",
        "frontend_safety.py",
        "logging_config.py",
        "version.py",
    ],
    "storage_modules": [
        "storage.py",
        "storage_base.py",
        "storage_schema.py",
        "storage_repository.py",
        "storage_recovery.py",
        "storage_search.py",
        "storage_cleanup.py",
        "storage_manager.py",
        "config.py",
    ],
    "ui_modules": [
        "ui_common.py",
        "ui_state.py",
        "ui_home.py",
        "ui_upload.py",
        "ui_review.py",
        "ui_execute.py",
        "ui_search.py",
        "ui_records.py",
        "ui_renderers.py",
    ],
    "folder_modules": [
        "folder_models.py",
        "folder_organizer.py",
        "folder_service.py",
        "folder_report.py",
        "report_exports.py",
    ],
    "docs_and_runtime_files": [
        "requirements.txt",
        "README.md",
        "RELEASE_PACKAGING.md",
        "RUN_RELEASE.md",
        "docs/KNOWN_LIMITATIONS.md",
    ],
}

RELEASE_ALLOWLIST = [
    path
    for group in RELEASE_ALLOWLIST_GROUPS.values()
    for path in group
]

FORBIDDEN_PATTERNS = [
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
    "*.sqlite",
    "*.sqlite3",
    "uploads/",
    "repo/",
    "previews/",
    "tmp/",
    "tmp_*",
    "logs/",
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
]


def get_version() -> str:
    namespace: dict[str, object] = {}
    version_path = PROJECT_ROOT / "version.py"
    exec(version_path.read_text(encoding="utf-8"), namespace)
    return str(namespace.get("__version__", "unknown"))


def build_zip(output_dir: Path, zip_name: str | None = None) -> Path:
    version = get_version()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    output_dir.mkdir(parents=True, exist_ok=True)

    if not zip_name:
        zip_name = f"{PROJECT_ROOT.name}-v{version}-runtime-demo-{timestamp}.zip"

    zip_path = output_dir / zip_name
    staging_dir = output_dir / f"_staging_{timestamp}"

    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    staging_dir.mkdir(parents=True)

    try:
        for relative in RELEASE_ALLOWLIST:
            source = PROJECT_ROOT / relative

            if not source.exists():
                raise FileNotFoundError(f"Release allowlist item is missing: {relative}")

            if source.is_dir():
                raise IsADirectoryError(
                    f"Release allowlist must not include directories: {relative}"
                )

            destination = staging_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        if zip_path.exists():
            zip_path.unlink()

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in RELEASE_ALLOWLIST:
                archive.write(
                    staging_dir / relative,
                    arcname=relative.replace(os.sep, "/"),
                )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    return zip_path


def zip_contains_forbidden_entries(zip_path: Path) -> list[str]:
    hits: list[str] = []

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()

    for name in names:
        normalized = name.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]

        for pattern in FORBIDDEN_PATTERNS:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the official Smart Organizer runtime/demo release zip."
    )

    parser.add_argument(
        "--output-dir",
        default="release",
        help="Directory where the release zip will be written.",
    )
    parser.add_argument(
        "--zip-name",
        default="",
        help="Optional explicit zip file name.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    zip_path = build_zip(output_dir, args.zip_name or None)
    forbidden = zip_contains_forbidden_entries(zip_path)

    if forbidden:
        raise SystemExit(f"Release zip contains forbidden paths: {forbidden}")

    print(f"Release zip created: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
