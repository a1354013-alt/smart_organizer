# Smart Organizer (v2.8.4)

Smart Organizer is a Streamlit app for safe file organization demos. It supports upload-based review for PDFs, images, and videos, and it now centers the homepage around a safer folder-cleanup workflow: scan a folder, identify stale or large-file candidates, preview actions with dry-run, move selected files into quarantine, and restore them later if needed.

## App structure

- `app.py`: stable `streamlit run app.py` entrypoint.
- `app_main.py`: defines `main()` and wires Streamlit tabs without import side effects.
- `core.py`, `core_utils.py`, `core_classification.py`, `core_processor.py`: metadata extraction, classification, OCR/PDF/video helpers.
- `services.py`, `services_models.py`, `services_analysis.py`, `services_review.py`, `services_finalize.py`: upload analysis, review confirmation, and finalize flows.
- `storage.py`, `storage_base.py`, `storage_schema.py`, `storage_repository.py`, `storage_recovery.py`, `storage_search.py`, `storage_cleanup.py`, `storage_manager.py`: persistence, search, recovery, and storage safety helpers.
- `folder_models.py`, `folder_organizer.py`, `folder_service.py`, `folder_report.py`, `report_exports.py`: non-UI folder cleanup and report services.
- `ui_common.py`, `ui_state.py`, `ui_home.py`, `ui_upload.py`, `ui_review.py`, `ui_execute.py`, `ui_search.py`, `ui_records.py`, `ui_renderers.py`: UI helpers and Streamlit screens.

Supporting runtime modules also included in the official release zip:

- `async_processor.py`
- `contracts.py`
- `frontend_safety.py`
- `logging_config.py`
- `version.py`

## Main portfolio workflow

1. Scan a target folder from the homepage.
2. Review stale-file and large-file candidates.
3. Select files to handle.
4. Preview results with dry-run.
5. Move selected files to `.smart_organizer_quarantine/`.
6. Restore quarantined files later if needed.
7. Export Markdown or CSV cleanup reports.

Each cleanup action records:

- original path
- new quarantine path
- processed time
- file size
- last modified time
- success / failed / skipped status
- failure reason when available

## Run locally

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
streamlit run app.py
```

## Validate

```bash
python -m compileall -q .
python -m pytest -q
ruff check .
mypy version.py contracts.py services.py services_models.py services_analysis.py services_review.py services_finalize.py core.py core_utils.py core_classification.py core_processor.py storage.py storage_base.py storage_schema.py storage_repository.py storage_recovery.py storage_search.py storage_cleanup.py storage_manager.py async_processor.py folder_models.py folder_organizer.py folder_service.py folder_report.py report_exports.py ui_common.py ui_home.py ui_records.py
```

## Official release package

Create the runtime/demo zip with:

```bash
python scripts/create_release_zip.py
```

or on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_release_zip.ps1
```

The official release zip is built from a strict allowlist. Runtime files included:

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
- `folder_models.py`
- `folder_organizer.py`
- `folder_service.py`
- `folder_report.py`
- `report_exports.py`
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
- `docs/KNOWN_LIMITATIONS.md`
- `async_processor.py`
- `contracts.py`
- `frontend_safety.py`
- `logging_config.py`
- `version.py`

The release zip must not include workspace-only content such as:

- `.git/`
- `__pycache__/`
- `.pytest_cache/`
- `.mypy_cache/`
- `.ruff_cache/`
- `.venv/`
- `venv/`
- `uploads/`
- `repo/`
- `previews/`
- `tmp/` and `tmp_*`
- `logs/`
- `dist/`
- `build/`
- `node_modules/`
- `*.pyc`
- `*.db`
- `*.sqlite`
- `*.sqlite3`
- large model files such as `*.onnx`, `*.pt`, `*.pth`, `*.bin`
- test temp artifacts such as `tests/_tmp*/`

## Known limitations

Detailed limitations are documented in [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).
