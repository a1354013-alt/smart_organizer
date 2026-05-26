from __future__ import annotations

import datetime
import logging
import os
import shutil
import sqlite3
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Self

from config import UPLOAD_MAX_BATCH_BYTES, UPLOAD_MAX_FILE_BYTES

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 14
MAX_UPLOAD_BYTES = UPLOAD_MAX_FILE_BYTES
MAX_UPLOAD_BATCH_BYTES = UPLOAD_MAX_BATCH_BYTES


class SearchContentError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def _log_context(**fields: object) -> str:
    parts = [f"{key}={value}" for key, value in fields.items() if value not in (None, "", [])]
    return f" [{', '.join(parts)}]" if parts else ""


class StorageBase:
    def __init__(self, db_path: str, repo_root: str, upload_dir: str):
        self.db_path = db_path
        self._db_uri = False
        self._keepalive_conn: sqlite3.Connection | None = None
        self._closed = False

        if str(self.db_path) == ":memory:":
            self.db_path = f"file:smart_organizer_memdb_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._db_uri = True
        elif str(self.db_path).startswith("file:"):
            self._db_uri = True

        self.repo_root = Path(repo_root)
        self.upload_dir = Path(upload_dir)

        self._mem_files: dict[str, bytes] | None = None
        if str(repo_root) == ":memory:" or str(upload_dir) == ":memory:":
            self._mem_files = {}
            self.repo_root = Path("mem://repo")
            self.upload_dir = Path("mem://uploads")

        if self._mem_files is None:
            self.repo_root.mkdir(parents=True, exist_ok=True)
            self.upload_dir.mkdir(parents=True, exist_ok=True)

        if self._db_uri and "mode=memory" in str(self.db_path):
            try:
                self._keepalive_conn = sqlite3.connect(self.db_path, uri=True)
            except sqlite3.Error as e:
                logger.warning("in-memory keepalive connection failed: %s", e)
                self._keepalive_conn = None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        keepalive = self._keepalive_conn
        self._keepalive_conn = None
        if keepalive is None:
            return
        try:
            keepalive.close()
        except sqlite3.Error:
            logger.debug("keepalive close failed", exc_info=True)

    def __enter__(self) -> Self:
        if self._closed:
            raise RuntimeError("StorageManager is closed. Create a new instance before continuing.")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()

    def _get_connection(self, timeout: int = 30000) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("StorageManager is closed. Create a new instance before continuing.")
        try:
            conn = sqlite3.connect(self.db_path, timeout=timeout / 1000, uri=self._db_uri)
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except sqlite3.OperationalError as e:
                logger.warning("WAL not available; falling back to DELETE journal_mode: %s", e)
                with suppress(sqlite3.Error):
                    conn.execute("PRAGMA journal_mode=DELETE;")

            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(f"PRAGMA busy_timeout={timeout};")
            return conn
        except sqlite3.Error as e:
            logger.error("DB connection failed: %s", e)
            raise

    def _is_mem_path(self, path_value: object) -> bool:
        return isinstance(path_value, str) and path_value.startswith("mem://")

    def _path_exists(self, path_value: object) -> bool:
        if not path_value:
            return False
        if self._mem_files is not None and self._is_mem_path(path_value):
            return str(path_value) in self._mem_files
        return os.path.exists(str(path_value))

    def _move_path(self, src: str, dst: str) -> None:
        if self._mem_files is not None and self._is_mem_path(src) and self._is_mem_path(dst):
            self._mem_files[dst] = self._mem_files.pop(src)
            return
        shutil.move(src, dst)

    def _copy_path(self, src: str, dst: str) -> None:
        if self._mem_files is not None and self._is_mem_path(src) and self._is_mem_path(dst):
            self._mem_files[dst] = bytes(self._mem_files.get(src, b""))
            return
        shutil.copy2(src, dst)

    def _remove_path(self, path_value: str) -> None:
        if self._mem_files is not None and self._is_mem_path(path_value):
            self._mem_files.pop(path_value, None)
            return
        try:
            os.remove(path_value)
        except FileNotFoundError:
            return

    def _merge_last_error(self, existing: str | None, addition: str | None, max_len: int = 400) -> str | None:
        """Legacy-compatible merge for user-facing `last_error`."""
        addition = (addition or "").strip()
        if not addition:
            return (existing or "").strip()[:max_len] or None

        existing_str = (existing or "").strip()
        if not existing_str:
            merged = addition
        else:
            merged = existing_str if addition in existing_str else f"{existing_str} | {addition}"

        if len(merged) > max_len:
            merged = merged[:max_len] + "..."
        return merged

    def _recovery_diag(self, summary: str) -> str | None:
        """Legacy-compatible recovery diagnostic for user-facing `last_error`."""
        summary = (summary or "").strip()
        if not summary:
            return None
        return f"Recovery: {summary}"

