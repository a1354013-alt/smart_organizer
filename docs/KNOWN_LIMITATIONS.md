# Known Limitations

- Folder scan decisions rely on file metadata and filesystem timestamps, primarily metadata, `mtime`, `atime`, and file size. The homepage scan does not inspect full file contents.
- Quarantine and restore depend on `.smart_organizer_quarantine/manifest.json`. If the manifest is edited or lost, restore accuracy is reduced.
- There is no background queue for homepage folder cleanup. Scans, previews, moves, restores, and report exports run in the active Streamlit request.
- Directories or files without read or move permission will be skipped or reported as permission-related errors.
- Video handling uses filename, container metadata, and optional thumbnails. It is not full video-content understanding.
- Image classification is rule-based and metadata-oriented rather than a deep learning image understanding pipeline.
- PDF OCR is disabled by default to reduce latency and avoid large-document UI stalls.
- If `ffmpeg` or `ffprobe` is unavailable or times out, the app falls back to partial video metadata with no guaranteed thumbnail.
- AI summary features require a valid OpenAI API key. Core review and organization flows should still work without one.
- The default cleanup flow does not permanently delete files. Selected files are moved into quarantine unless the user restores them later.
