# Release Packaging

Do not create the final delivery zip by compressing the whole working folder directly.

Use the PowerShell packaging script instead:

```powershell
.\create_release_zip.ps1
```

The release zip is created from an **allowlist** (not a blocklist). Only these paths are included:

- `app.py`
- `core.py`
- `services.py`
- `storage.py`
- `logging_config.py`
- `version.py`
- `contracts.py`
- `README.md`
- `requirements.txt`

This is an **official runtime/demo package** and intentionally **does not include tests**.
It also intentionally excludes workspace artifacts such as `.git/`, `__pycache__/`, `*.pyc`, `*.db`, `release/`, `.pytest_cache/`, temp folders, etc.

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
mypy version.py contracts.py services.py
```
