# Run Release Package

This document is only for the official runtime/demo release package.
It is not a development guide.

## Included files

The official release zip contains only the runtime files:

- `app.py`
- `app_main.py`
- `contracts.py`
- `core.py`
- `core_utils.py`
- `core_classification.py`
- `core_processor.py`
- `logging_config.py`
- `ui_renderers.py`
- `README.md`
- `requirements.txt`
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
- `version.py`

It does **not** include tests, CI config, or development-only tooling.

## Install

```bash
pip install -r requirements.txt
```

## Start

```bash
streamlit run app.py
```

## Required system dependencies

- `streamlit` is required to start the app.
- `poppler` is required for PDF preview.
- `tesseract` is required for OCR.
- `ffmpeg` (including `ffprobe`) is required for video thumbnails and video metadata (Phase 1).

If `poppler` or `tesseract` is missing, those features degrade gracefully; the app still starts.
If `ffmpeg/ffprobe` is missing, video thumbnail/metadata is skipped; video upload and rule-based classification still works.

## Known limits

- The release package is for runtime/demo use, not source development.
- It does not include tests, `requirements-dev.txt`, `pyproject.toml`, or CI files.
- To run tests or static checks, use the source repository instead of the release zip.
