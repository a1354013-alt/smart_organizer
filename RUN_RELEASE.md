# Run Release Package

This document is only for the official runtime/demo release package.
It is not a development guide.

## Included files

The official release zip contains only the runtime files:

- `app.py`
- `contracts.py`
- `core.py`
- `logging_config.py`
- `README.md`
- `requirements.txt`
- `services.py`
- `storage.py`
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

If `poppler` or `tesseract` is missing, those features degrade gracefully; the app still starts.

## Known limits

- The release package is for runtime/demo use, not source development.
- It does not include tests, `requirements-dev.txt`, `pyproject.toml`, or CI files.
- To run tests or static checks, use the source repository instead of the release zip.
