# Known Limitations

- Folder scan decisions rely on file metadata and filesystem timestamps, primarily metadata, `mtime`, `atime`, and file size. The homepage scan does not inspect full file contents.
- Candidate scoring is deterministic and rule-based. It explains confidence, risk level, and reasons, but it is still a review aid rather than a guarantee that a file should be moved.
- `atime` can be disabled or coarse on some systems, including some Windows configurations, so users should treat long-unused detection as a supporting signal.
- Quarantine and restore depend on `.smart_organizer_quarantine/manifest.json`. Tampered entries that point outside the scan root or quarantine root are rejected instead of restored.
- The manifest is written atomically, but if storage hardware or OS-level writes fail repeatedly, the app reports the failure instead of guessing.
- There is no background queue for homepage folder cleanup. Scans, previews, moves, restores, and report exports run in the active Streamlit request.
- Directories or files without read or move permission will be skipped or reported as permission-related errors.
- Video handling uses filename, container metadata, and optional thumbnails. It is not full video-content understanding.
- Video uploads are accepted into the analysis flow, but a fake `.mp4` or other invalid video container is reported as degraded or unsupported instead of being treated as a healthy video.
- Image classification is rule-based and metadata-oriented rather than a deep learning image understanding pipeline.
- PDF OCR is disabled by default to reduce latency and avoid large-document UI stalls.
- PDF preview, OCR, and video helpers use timeouts and best-effort fallbacks. A timeout may still leave a single worker thread or subprocess finishing in the background before cleanup completes.
- If `ffmpeg` or `ffprobe` is unavailable or times out, the app falls back to partial video metadata with no guaranteed thumbnail.
- Record timestamps are stored in UTC ISO 8601. The UI may render them in local time, while exported reports keep UTC labels.
- AI summary features require a valid OpenAI API key. Core review and organization flows should still work without one.
- The default cleanup flow does not permanently delete selected user files. Selected files are moved into quarantine unless the user restores them later.
