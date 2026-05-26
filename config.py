from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"
REPO_ROOT = PROJECT_ROOT / "repo"
DB_PATH = PROJECT_ROOT / "smart_organizer.db"

UPLOAD_MAX_FILE_MB = 25
UPLOAD_MAX_BATCH_MB = 50
UPLOAD_MAX_FILE_BYTES = UPLOAD_MAX_FILE_MB * 1024 * 1024
UPLOAD_MAX_BATCH_BYTES = UPLOAD_MAX_BATCH_MB * 1024 * 1024
