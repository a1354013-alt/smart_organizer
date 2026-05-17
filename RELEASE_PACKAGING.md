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
- UI modules: `ui_common.py`, `ui_state.py`, `ui_home.py`, `ui_labels.py`, `ui_upload.py`, `ui_review.py`, `ui_execute.py`, `ui_search.py`, `ui_records.py`, `ui_renderers.py`
- folder organizer modules: `folder_models.py`, `folder_organizer.py`, `folder_service.py`, `folder_report.py`
- report export modules: `report_exports.py`
- docs/runtime notes: `docs/KNOWN_LIMITATIONS.md`
- requirements / README / run scripts: `requirements.txt`, `README.md`, `RELEASE_PACKAGING.md`, `RUN_RELEASE.md`
- demo helper scripts: `scripts/create_demo_folder.py`, `scripts/check_workspace_clean.py`
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
- generated demo data folders such as `demo_files/`

## Verification

The packaging policy is enforced by:

- `scripts/create_release_zip.py`
- `scripts/verify_release_zip.py`
- `scripts/check_workspace_clean.py`
- `create_release_zip.ps1` (delegates to the Python script only)
- `tests/test_delivery_cleanliness.py`
- `tests/test_release_packaging_policy.py`
- `tests/test_release_hygiene.py`

Run the full source-repository validation sequence before publishing:

Source repository only, not included in runtime release zip.

```bash
python scripts/validate_release_source.py
```

This command is only available in the source repository and is not included in the extracted runtime/demo zip.

Do not use the standard-library compileall module directly for release validation because
it can leave `__pycache__` directories in the workspace.
The validation script also runs cache-safe `ruff check --no-cache` and
`mypy --cache-dir=/dev/null` so the final workspace-cleanliness check remains valid.
During validation, the script writes and verifies the deterministic
`release_ci/smart_organizer-release-validation.zip` artifact so older local zips
cannot affect the result.

After unpacking the release zip:

```bash
python -m pip install -r requirements.txt
python scripts/create_demo_folder.py
streamlit run app.py
```
