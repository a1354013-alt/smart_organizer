# Run Release Package

This document applies to the official Smart Organizer runtime/demo release zip. It is for running the packaged app, not for source-repo development work.

## 1. Build the release zip from the source repository

Run this only in the source repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_release_zip.ps1
```

Or:

```bash
python scripts/create_release_zip.py
```

What this does:

- Creates the official runtime/demo zip from the source repo allowlist.
- Excludes tests, CI files, development tooling, and packaging-only assets.
- Verifies that the generated zip does not contain forbidden entries.

What this does not do:

- It does not prepare the extracted runtime zip to be repackaged again.
- It only copies runtime/demo helper scripts from the allowlist, not tests or source-only tooling.

## 2. Files included

The release zip is built from the allowlist in `scripts/create_release_zip.py`.

Key runtime groups:

- app entry: `app.py`, `app_main.py`
- core/storage/config: `core*.py`, `storage*.py`, `config.py`
- UI modules: `ui_*.py`
- folder organizer/report modules: `folder_*.py`, `report_exports.py`
- docs/runtime files: `docs/KNOWN_LIMITATIONS.md`, `requirements.txt`, `README.md`, `RELEASE_PACKAGING.md`, `RUN_RELEASE.md`
- demo helper: `scripts/create_demo_folder.py`, `scripts/check_workspace_clean.py`
- runtime helpers: `services*.py`, `async_processor.py`, `contracts.py`, `frontend_safety.py`, `logging_config.py`, `version.py`

Not included:

- `tests/`
- `.github/workflows/`
- `.git/`
- `.venv/`
- `uploads/`
- `repo/`
- `previews/`
- cache, build, temp, database, and generated zip artifacts

## 3. Run the extracted release zip

After extracting the official release zip, use it only as a runtime/demo package:

```bash
python -m pip install -r requirements.txt
python scripts/create_demo_folder.py
streamlit run app.py
```

The release zip is intended for:

- installing runtime dependencies
- starting the Streamlit app
- running a quick smoke test of the packaged app

## 4. Commands that must not be run inside the extracted release zip

These commands belong to the source repository, not the runtime package:

- `python scripts/create_release_zip.py`
- `powershell -ExecutionPolicy Bypass -File .\create_release_zip.ps1`
- `python -m pytest`
- `python -m mypy`
- `python -m ruff check --no-cache .`

Why:

- the official release zip does not include tests or dev dependencies
- the official release zip is a runtime/demo package, not a packaging toolchain

## 5. Required system dependencies

- `streamlit` is required to start the app.
- `poppler` is needed for PDF preview generation.
- `tesseract` is needed for OCR.
- `ffmpeg` and `ffprobe` are needed for video metadata and thumbnails.

If these tools are missing, the app still starts and falls back where possible.

## 6. Safety expectations

- Folder cleanup uses quarantine by default.
- The homepage does not permanently delete selected user files automatically.
- Restore writes a safe non-overwriting filename if the original path is already occupied.

## 7. Verify that the release zip is usable

Recommended smoke test after extraction:

1. Install runtime dependencies.
2. Start the app with `streamlit run app.py`.
3. Confirm the app opens successfully.
4. Confirm a basic upload flow or folder-cleanup UI flow works.

## 8. Source repository release validation

Run these commands from the source repository root before publishing a release. Use
`scripts/safe_compileall.py` instead of `python -m compileall` so validation does not
create `__pycache__` directories that would fail the final workspace-cleanliness check.
Use the release validation script as the single source of truth for the full command
sequence.

```bash
python scripts/validate_release_source.py
```

This command is only available in the source repository and is not included in the extracted runtime/demo zip.

The validation script runs cache-safe checks, including `ruff check --no-cache`
and `mypy --cache-dir=/dev/null`, then verifies the release zip and workspace
cleanliness.
