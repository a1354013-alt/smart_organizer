# Smart Organizer (v2.8.4)

Smart Organizer is a local-first safe file organization assistant. It is not an automatic delete tool, knowledge base, RAG system, chatbot, or document QA app.

The core product promise is simple: scan a folder, explain why files may need review, move selected files into quarantine, restore them if needed, and export a report.

Supported upload formats: `pdf, jpg, jpeg, png, mp4, mov, mkv, avi, webm, m4v`.

## Core Workflow

```mermaid
flowchart LR
    Scan["Scan"] --> Analyze["Analyze"]
    Analyze --> Review["Review"]
    Review --> Quarantine["Quarantine"]
    Quarantine --> Restore["Restore"]
    Restore --> Report["Report"]
```

Folder organizer flow:

1. Scan a local folder with metadata-only inspection.
2. Analyze candidates using explainable rule-based scoring.
3. Review reasons, confidence, risk level, and recommended action.
4. Move selected files into `.smart_organizer_quarantine/`.
5. Restore quarantined files without overwriting existing files.
6. Export Markdown or CSV reports.

## Safety Design

- No direct delete of selected user files: cleanup actions move selected files to quarantine first.
- Path containment: scan, quarantine, and restore paths are validated against the selected root.
- Restore protection: restore uses a safe destination and does not overwrite a new user file.
- Atomic manifest: `manifest.json` is saved through `manifest.json.tmp`, flush, `fsync`, and `os.replace`.
- Interrupted move recovery: `MOVING` manifest entries are repaired on the next quarantine/restore/list operation.
- Release allowlist: the runtime zip is built from explicit files and rejects caches, DBs, uploads, temp folders, and `.git`.

## Quick Demo

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python scripts/create_demo_folder.py
streamlit run app.py
```

Then scan the generated `demo_files` folder. It contains old, suspected duplicate-name, recent, and keep-focused sample files so reviewers can experience the full flow in about one minute.

## Validation

Run the same commands used by `.github/workflows/ci.yml`:

```bash
python -m compileall -q .
python scripts/safe_compileall.py -q .
ruff check .
python -m mypy core_processor.py core_metadata.py services_analysis.py services_finalize.py storage_repository.py storage_recovery.py storage_search.py folder_organizer.py folder_models.py ui_common.py ui_home.py ui_upload.py ui_review.py ui_execute.py ui_search.py ui_renderers.py ui_records.py
python -m pytest
python scripts/create_release_zip.py --output-dir release_ci
python scripts/verify_release_zip.py release_ci/*.zip
```

If quarantine metadata access is blocked by a leftover `manifest.json.lock`, Smart Organizer raises a clear manifest-lock error. It does not silently hang, and it does not auto-delete the lock file because that could conflict with another active process.

## Explainable Scoring

The organizer is intentionally rule-based and reproducible. Each scan record includes:

- `confidence`
- `risk_level`
- `candidate_reasons`
- `reason_codes`
- `file_age_score`
- `size_score`
- `duplicate_score`
- `extension_risk_score`

Low-confidence items are marked for manual review or do-not-touch handling. The app does not use opaque AI decisions for quarantine recommendations.

## Known Limitations

- Access time (`atime`) can be unreliable on some filesystems and OS settings.
- Modified time (`mtime`) and file size are supporting signals, not proof that a file is safe to archive.
- Users must manually confirm before moving files.
- OCR, PDF preview, and video metadata depend on optional system tools.
- The app does not automatically delete selected user files.
- Internal temp files, previews, and caches may be cleaned up by maintenance routines.

## Portfolio Highlights

- Safe folder organization workflow
- Quarantine and restore manifest
- Atomic manifest write and recovery tests
- Streamlit UI flow tests with `tmp_path` demo files
- Explainable rule scoring
- Release packaging with allowlist verification
- One-command demo dataset generator

## Additional Docs

- Architecture and tradeoffs: `docs/PORTFOLIO_CASE_STUDY.md`
- Known limitations: `docs/KNOWN_LIMITATIONS.md`
- Release packaging notes: `RELEASE_PACKAGING.md`
- Release runbook: `RUN_RELEASE.md`
