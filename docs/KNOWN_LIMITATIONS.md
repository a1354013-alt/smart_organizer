# Known Limitations

- Video analysis Phase 1 relies on filename, metadata, and thumbnail heuristics. It does not perform full video-content understanding.
- Image classification is metadata/rule-based rather than a deep learning model.
- PDF OCR is off by default to avoid large-PDF UI stalls.
- If `ffmpeg` or `ffprobe` is unavailable, video analysis falls back gracefully with partial metadata.
- Cleanup defaults to quarantine for safety. Permanent delete is intentionally not part of the homepage workflow.
- AI summaries require an OpenAI API key. If no key is configured, the main workflow should still continue without blocking.
