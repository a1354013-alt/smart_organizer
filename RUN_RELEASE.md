# Run Release Package

This document applies to the official Smart Organizer runtime/demo release zip.

## Files included

The release zip is built from the allowlist in `scripts/create_release_zip.py`.

Key runtime groups:

- app entry: `app.py`, `app_main.py`
- core/storage/config: `core*.py`, `storage*.py`, `config.py`
- UI modules: `ui_*.py`
- folder organizer/report modules: `folder_*.py`, `report_exports.py`
- docs/runtime files: `docs/KNOWN_LIMITATIONS.md`, `requirements.txt`, `README.md`, `RELEASE_PACKAGING.md`, `RUN_RELEASE.md`
- runtime helpers: `services*.py`, `async_processor.py`, `contracts.py`, `frontend_safety.py`, `logging_config.py`, `version.py`

Not included:

- `tests/`
- `.github/workflows/`
- `.git/`
- `.venv/`
- `uploads/`
- `repo/`
- `previews/`
- any cache/build/temp/database artifacts

## Install

```bash
python -m pip install -r requirements.txt
```

## Start

```bash
streamlit run app.py
```

## Packaging command

```bash
python scripts/create_release_zip.py
```

Windows entrypoint:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_release_zip.ps1
```

## System dependencies

- `streamlit` is required to start the app.
- `poppler` is needed for PDF preview generation.
- `tesseract` is needed for OCR.
- `ffmpeg` and `ffprobe` are needed for video metadata and thumbnails.

If these tools are missing, the app still starts and falls back where possible.

## Safety expectations

- Folder cleanup uses quarantine by default.
- The homepage never permanently deletes files automatically.
- Restore writes a safe non-overwriting filename if the original path is already occupied.
