# Release Packaging

Do not create the final delivery zip by compressing the whole working folder directly.

Use the PowerShell packaging script instead:

```powershell
.\create_release_zip.ps1
```

The release zip is created from an **allowlist** (not a blocklist). Only these paths are included:

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
- `async_processor.py`
- `storage.py`
- `storage_base.py`
- `storage_schema.py`
- `storage_repository.py`
- `storage_recovery.py`
- `storage_search.py`
- `storage_cleanup.py`
- `storage_manager.py`
- `logging_config.py`
- `version.py`
- `contracts.py`
- `README.md`
- `RUN_RELEASE.md`
- `requirements.txt`

This is an **official runtime/demo package** and intentionally **does not include tests**.
It also intentionally excludes workspace artifacts such as `.git/`, `.venv/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `*.pyc`, `*.db`, `release/`, `.pytest_cache/`, temp folders, etc.

This zip is a **runtime/demo package**, not a source-development package.

By default, the zip file name includes `runtime-demo` to reduce the chance that a workspace snapshot is mistaken for the official release.
It also includes the project version from `version.py` (single source of truth) to keep delivery artifacts traceable.

The script also refuses to package folders (directories) to avoid accidentally including `tests/` or other workspace trees.

After unpacking, install and run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

To run tests, use the source repo (not the release zip):

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check .
mypy version.py contracts.py services.py core.py storage.py async_processor.py
```

After unpacking the official zip, follow `RUN_RELEASE.md` for runtime/demo startup steps.
Do not treat the release zip as a replacement for the full source repository.
