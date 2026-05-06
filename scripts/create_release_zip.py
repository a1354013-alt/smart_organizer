from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile


INCLUDE_PATHS = [
    "app.py",
    "app_main.py",
    "core.py",
    "core_utils.py",
    "core_classification.py",
    "core_processor.py",
    "services.py",
    "services_models.py",
    "services_analysis.py",
    "services_review.py",
    "services_finalize.py",
    "async_processor.py",
    "storage.py",
    "storage_base.py",
    "storage_schema.py",
    "storage_repository.py",
    "storage_recovery.py",
    "storage_search.py",
    "storage_cleanup.py",
    "storage_manager.py",
    "logging_config.py",
    "frontend_safety.py",
    "ui_common.py",
    "ui_state.py",
    "ui_home.py",
    "ui_upload.py",
    "ui_review.py",
    "ui_execute.py",
    "ui_search.py",
    "ui_records.py",
    "ui_renderers.py",
    "version.py",
    "contracts.py",
    "README.md",
    "RUN_RELEASE.md",
    "requirements.txt",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_release_zip(project_root: Path, output_dir: Path, zip_name: str | None = None) -> Path:
    from version import __version__

    project_name = project_root.name
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = zip_name or f"{project_name}-v{__version__}-runtime-demo.zip"
    zip_path = output_dir / archive_name

    with tempfile.TemporaryDirectory(prefix="smart_organizer_release_") as tmp_dir:
        staging_root = Path(tmp_dir)
        for relative_path in INCLUDE_PATHS:
            source = project_root / relative_path
            if not source.exists():
                continue
            if source.is_dir():
                raise RuntimeError(
                    f"Official runtime/demo release must not include directories: {relative_path}"
                )

            destination = staging_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        with ZipFile(zip_path, mode="w", compression=ZIP_DEFLATED) as archive:
            for file_path in sorted(staging_root.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(staging_root))

    return zip_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the official runtime/demo release zip.")
    parser.add_argument(
        "--output-dir",
        default="release",
        help="Directory where the release zip will be written.",
    )
    parser.add_argument(
        "--zip-name",
        default=None,
        help="Optional explicit zip file name.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = PROJECT_ROOT
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir

    zip_path = build_release_zip(project_root, output_dir, zip_name=args.zip_name)
    print(f"Release zip created: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
