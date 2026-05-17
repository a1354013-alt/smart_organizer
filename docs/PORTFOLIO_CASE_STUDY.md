# Smart Organizer Portfolio Case Study

## Problem

People often want to clean local folders without risking accidental deletion or silent data loss. Demo projects in this space frequently optimize for flashy automation first, while safety, previewability, and reversibility stay under-specified.

## Solution

Smart Organizer is a local-first safety file cleanup assistant. It scans a chosen folder, identifies stale or large-file candidates, previews the proposed actions, moves selected files into quarantine instead of deleting them, allows later restore, and exports a report of what happened.

The project also includes a separate upload-review workflow for supported PDFs, images, and videos so the app can demonstrate metadata extraction, OCR-aware analysis, and classification without requiring destructive filesystem operations.

## Architecture

- `ui_*` modules: Streamlit screens, session state, and rendering helpers.
- `folder_*` modules: folder scan, quarantine, restore, manifest handling, and report export.
- `services_*` modules: upload batch orchestration, review flow, and finalize operations.
- `core_*` modules: metadata extraction, OCR/PDF/video helpers, and rule-based classification.
- `storage_*` modules: SQLite persistence, FTS search, recovery, and file record management.

## Safety-first Design

- Scan before move: folder cleanup starts with a metadata-only scan.
- Preview before execute: dry-run results show where files would go before any move happens.
- Quarantine instead of delete: the default action is reversible.
- Path containment checks: move and restore now validate that source and destination paths stay inside the expected scan root and quarantine root.
- Manifest hardening: restore rejects tampered manifest entries that point outside the allowed roots.
- Graceful degradation: missing `poppler`, `tesseract`, `ffmpeg`, or `ffprobe`, and timeout conditions, produce warning notes instead of crashing the whole batch.

## Testing Strategy

- Unit tests cover folder containment, restore safety, async cancellation, metadata extraction fallbacks, records search, release packaging policy, and UI smoke imports.
- `scripts/validate_release_source.py` centralizes `safe_compileall`, `ruff --no-cache`, `mypy --cache-dir=/dev/null`, `pytest`, release zip creation, release zip verification, and the workspace-cleanliness check.
- Release packaging is allowlist-based so runtime bundles stay explicit and reproducible.

## Known Limitations

- Folder scan decisions use filesystem metadata, not deep semantic understanding of every file.
- OCR and preview quality depend on optional external tooling.
- Async cancellation is best-effort for already-running work.
- Video analysis is limited to container metadata and thumbnails, not content understanding.
- AI summaries are optional and require external credentials.

## Future Improvements

- Add richer non-destructive review signals, such as duplicate clustering or folder-level heuristics.
- Improve structured warning surfacing in the UI so degraded and partial outcomes are easier to filter.
- Expand recovery tooling for bulk manifest inspection and export.
- Add more integration-style tests around Streamlit session flows and long-running processing.
