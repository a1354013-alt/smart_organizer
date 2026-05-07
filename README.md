# Smart Organizer (v2.8.4)

Smart Organizer is a local-first safety file cleanup assistant built with Streamlit. It combines an upload-review workflow for portfolio demos with a safer folder organizer that always follows `scan -> preview -> quarantine -> restore -> export report`.

Supported upload formats: `pdf, jpg, jpeg, png, mp4, mov, mkv, avi, webm, m4v`.
The backend validation and Streamlit uploader both use the single source of truth in `supported_formats.py`.

## Project positioning

- Local-first: scanning, quarantine, restore, and release packaging all run on the local machine.
- Safety-first: the app quarantines files instead of deleting them, records a manifest, and now validates path containment before move or restore.
- Portfolio-ready: the homepage demonstrates the end-to-end cleanup workflow, and the docs explain design tradeoffs without claiming unsupported features.

## Main workflow

1. Scan a folder and collect metadata-only candidates.
2. Preview stale or large-file actions with dry-run.
3. Move selected files into `.smart_organizer_quarantine/`.
4. Restore quarantined items when needed.
5. Export Markdown or CSV reports for review.

Upload/review flow remains available for supported PDFs, images, and videos.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
streamlit run app.py
```

## Validation and tests

Run the full acceptance suite:

```bash
python -m compileall .
python -m ruff check .
python -m mypy .
python -m pytest -q
python scripts/create_release_zip.py
```

## System dependencies

Optional processing features degrade safely when dependencies are missing or time out.

- `poppler` + `pdf2image`: used for PDF preview rendering and PDF OCR image conversion.
- `tesseract`: used for OCR on PDFs and images.
- `ffmpeg` + `ffprobe`: used for video metadata extraction and thumbnail generation.

If these tools are unavailable, the app should keep running and mark the result with `timeout`, `degraded`, or `partial` notes instead of crashing the whole batch.

## Release packaging

Create the official runtime/demo zip with:

```bash
python scripts/create_release_zip.py
```

The release bundle is allowlist-based and intentionally excludes workspace-only content such as `.git/`, caches, temp folders, local databases, uploads, and generated artifacts.

## Portfolio docs

- Architecture and tradeoffs: `docs/PORTFOLIO_CASE_STUDY.md`
- Known limitations: `docs/KNOWN_LIMITATIONS.md`
- Release packaging notes: `RELEASE_PACKAGING.md`
- Release runbook: `RUN_RELEASE.md`

## Known limitations

- Folder scan targets metadata only; it does not understand file semantics deeply.
- OCR and preview quality depend on optional external tools.
- Timeout cancellation is best-effort for already-running worker threads and subprocesses.
- AI summary generation is optional and requires OpenAI credentials and SDK support.
