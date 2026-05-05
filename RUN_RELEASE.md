# Run Release Package

This document applies to the official Smart Organizer runtime/demo release zip.

## Files included

Runtime files:

- `app.py`
- `app_main.py`
- `core.py`
- `core_utils.py`
- `core_classification.py`
- `core_processor.py`
- `services.py`
- `services_models.py`
- `services_analysis.py`
- `services_review.py`
- `services_finalize.py`
- `storage.py`
- `storage_base.py`
- `storage_schema.py`
- `storage_repository.py`
- `storage_recovery.py`
- `storage_search.py`
- `storage_cleanup.py`
- `storage_manager.py`
- `ui_common.py`
- `ui_state.py`
- `ui_home.py`
- `ui_upload.py`
- `ui_review.py`
- `ui_execute.py`
- `ui_search.py`
- `ui_records.py`
- `ui_renderers.py`
- `requirements.txt`
- `README.md`
- `RELEASE_PACKAGING.md`
- `RUN_RELEASE.md`

Supporting modules required by the runtime entrypoints:

- `async_processor.py`
- `contracts.py`
- `frontend_safety.py`
- `logging_config.py`
- `version.py`

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
pip install -r requirements.txt
```

## Start

```bash
streamlit run app.py
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
