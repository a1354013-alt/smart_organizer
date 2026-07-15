from __future__ import annotations

from pathlib import Path

from runtime_config import build_runtime_config

PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_CONFIG = build_runtime_config(PROJECT_ROOT)
UPLOAD_DIR = RUNTIME_CONFIG.upload_dir
REPO_ROOT = RUNTIME_CONFIG.repo_root
DB_PATH = RUNTIME_CONFIG.db_path
PREVIEW_DIR = RUNTIME_CONFIG.preview_dir
QUARANTINE_DIR = RUNTIME_CONFIG.quarantine_dir
LOG_DIR = RUNTIME_CONFIG.log_dir
MANIFEST_DIR = RUNTIME_CONFIG.manifest_dir

UPLOAD_MAX_FILE_MB = 25
UPLOAD_MAX_BATCH_MB = 50
UPLOAD_MAX_FILE_BYTES = UPLOAD_MAX_FILE_MB * 1024 * 1024
UPLOAD_MAX_BATCH_BYTES = UPLOAD_MAX_BATCH_MB * 1024 * 1024
