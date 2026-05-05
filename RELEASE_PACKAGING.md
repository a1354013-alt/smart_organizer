# Release Packaging

Do not zip the whole workspace directly.

Use one of these official packaging commands instead:

```bash
python scripts/create_release_zip.py
```

```powershell
.\create_release_zip.ps1
```

## Runtime/demo allowlist

The official release zip is built from the allowlist in `scripts/create_release_zip.py`.

It includes these runtime categories:

- app entry: `app.py`, `app_main.py`
- core/storage/config: `core*.py`, `storage*.py`, `config.py`
- UI modules: `ui_common.py`, `ui_state.py`, `ui_home.py`, `ui_upload.py`, `ui_review.py`, `ui_execute.py`, `ui_search.py`, `ui_records.py`, `ui_renderers.py`
- folder organizer modules: `folder_models.py`, `folder_organizer.py`, `folder_service.py`, `folder_report.py`
- report export modules: `report_exports.py`
- docs/runtime notes: `docs/KNOWN_LIMITATIONS.md`
- requirements / README / run scripts: `requirements.txt`, `README.md`, `RELEASE_PACKAGING.md`, `RUN_RELEASE.md`
- supporting runtime helpers: `services*.py`, `async_processor.py`, `contracts.py`, `frontend_safety.py`, `logging_config.py`, `version.py`

This is an official runtime/demo package. It intentionally does not include tests, CI files, development configs, or workspace snapshots.

## Forbidden paths

These must stay out of the release zip:

- `.git/`
- `release/`
- `release_ci*/`
- `*.zip`
- `__pycache__/`
- `.pytest_cache/`
- `.mypy_cache/`
- `.ruff_cache/`
- `.venv/`
- `venv/`
- `uploads/`
- `repo/`
- `previews/`
- `tmp/`
- `tmp_*`
- `logs/`
- `dist/`
- `build/`
- `node_modules/`
- `*.pyc`
- `*.db`
- `*.sqlite`
- `*.sqlite3`
- `.coverage`
- `htmlcov/`
- large model files such as `*.onnx`, `*.pt`, `*.pth`, `*.bin`
- test temporary directories such as `tests/_tmp*/`

## Verification

The packaging policy is enforced by:

- `scripts/create_release_zip.py`
- `create_release_zip.ps1` (delegates to the Python script only)
- `tests/test_delivery_cleanliness.py`
- `tests/test_release_packaging_policy.py`
- `tests/test_release_hygiene.py`

After unpacking the release zip:

```bash
pip install -r requirements.txt
streamlit run app.py
```
