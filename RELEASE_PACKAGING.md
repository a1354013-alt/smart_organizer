# Release Packaging

Do not zip the whole workspace directly.

Use one of these official packaging commands instead:

```bash
python scripts/build_release_zip.py
```

Compatibility alias:

```bash
python scripts/create_release_zip.py
```

```powershell
.\create_release_zip.ps1
```

## Runtime/demo allowlist

The official runtime release zip is built from the allowlist in `scripts/release_policy.py`
and packaged by `scripts/create_release_zip.py`.

It includes these runtime categories:

- app entry: `app.py`, `app_main.py`
- core/storage/config: `core*.py`, `storage*.py`, `config.py`
- UI modules: `ui_common.py`, `ui_state.py`, `ui_home.py`, `ui_labels.py`, `ui_upload.py`, `ui_review.py`, `ui_execute.py`, `ui_search.py`, `ui_records.py`, `ui_renderers.py`
- folder organizer modules: `folder_models.py`, `folder_organizer.py`, `folder_service.py`, `folder_report.py`
- report export modules: `report_exports.py`
- malware scanning and folder safety helpers: `malware_scanner.py`
- upload validation, supported-format, and topic-classification helpers: `supported_formats.py`, `core_classification.py`, `ui_upload.py`
- i18n runtime files: `i18n.py`, `i18n_core.py`, `locales/zh-TW.json`, `locales/en.json`
- docs/runtime notes: `docs/KNOWN_LIMITATIONS.md`, `docs/PORTFOLIO_CASE_STUDY.md`
- requirements / README / run scripts: `requirements.txt`, `README.md`, `RELEASE_PACKAGING.md`, `RUN_RELEASE.md`
- demo helper scripts: `scripts/create_demo_folder.py`
- supporting runtime helpers: `services*.py`, `async_processor.py`, `contracts.py`, `frontend_safety.py`, `logging_config.py`, `version.py`

This is an official runtime/demo package. It intentionally does not include tests, CI files, development configs, or workspace snapshots.

Source-only scripts stay in the source repository and are never included in the runtime zip:

- `scripts/build_release_zip.py`
- `scripts/check_workspace_clean.py`
- `scripts/create_release_zip.py`
- `scripts/release_policy.py`
- `scripts/safe_compileall.py`
- `scripts/validate_release_source.py`
- `scripts/verify_release_zip.py`

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

- `scripts/release_policy.py`
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

This command is only available in the source repository and is not included in the extracted runtime/demo zip because source-only scripts stay in the source repository.

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

Runtime expectations for demos and reviews:

- The primary supported workflow is `scan -> dry-run -> execute -> quarantine -> restore`.
- Async batch upload processing is included as an internal or future-use implementation detail, not as the main demo path.
- Optional dependencies degrade gracefully: PDF preview, OCR, and video helpers may be unavailable without preventing the app from starting.
- Invalid video containers are reported as degraded analysis results instead of crashing upload review.
