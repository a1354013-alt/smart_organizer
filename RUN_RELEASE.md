# Run Release Package

This document is only for the official runtime/demo release package.
It is not a source-repo development guide.

## 1. Build the release zip from the source repository

Run this only in the source repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_release_zip.ps1
```

Or:

```bash
python scripts/create_release_zip.py
```

What this does:

- Creates an official runtime/demo zip from the source repo allowlist.
- Excludes tests, CI files, development tooling, and packaging-only assets.

What this does not do:

- It does not prepare the extracted runtime zip to be repackaged again.
- It does not copy `scripts/` or other source-only tooling into the runtime package.

## 2. Run the extracted release zip

After extracting the official release zip, use it only as a runtime/demo package:

```bash
pip install -r requirements.txt
streamlit run app.py
```

The release zip is intended for:

- installing runtime dependencies
- starting the Streamlit app
- running a quick smoke test of the packaged app

## 3. Commands that must not be run inside the extracted release zip

These commands belong to the source repository, not the runtime package:

- `python scripts/create_release_zip.py`
- `powershell -ExecutionPolicy Bypass -File .\create_release_zip.ps1`
- `python -m pytest`
- `python -m mypy`
- `python -m ruff check .`

Why:

- the official release zip does not include `scripts/`
- the official release zip does not include tests or dev dependencies
- the official release zip is a runtime/demo package, not a packaging toolchain

## 4. Verify that the release zip is usable

Recommended smoke test after extraction:

1. Install runtime dependencies.
2. Start the app with `streamlit run app.py`.
3. Confirm the app opens successfully.
4. Confirm a basic upload or UI navigation flow works.

## Included runtime files

The official release zip contains only runtime files required to launch the app.
It does not include tests, CI config, `requirements-dev.txt`, `pyproject.toml`, or source-only packaging tooling.

## Required system dependencies

- `streamlit` is required to start the app.
- `poppler` is required for PDF preview.
- `tesseract` is required for OCR.
- `ffmpeg` and `ffprobe` are required for video metadata and video thumbnails.

If `poppler`, `tesseract`, `ffmpeg`, or `ffprobe` is missing, the app still starts and the affected feature degrades gracefully.
