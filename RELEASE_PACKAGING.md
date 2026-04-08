# Release Packaging

Do not create the final delivery zip by compressing the whole working folder directly.

Use the PowerShell packaging script instead:

```powershell
.\create_release_zip.ps1
```

The release zip is created from an **allowlist** (not a blocklist). Only these paths are included:

- `app.py`
- `core.py`
- `storage.py`
- `logging_config.py`
- `README.md`
- `requirements.txt`

This is an **official runtime/demo package** and intentionally **does not include tests**.

After unpacking, install and run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

To run tests, use the source repo (not the release zip):

```bash
pip install -r requirements-dev.txt
pytest -q
```
