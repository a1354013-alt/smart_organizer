from __future__ import annotations

import os
import time
from pathlib import Path

from storage import StorageManager


def _make_old_file(path: Path, payload: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    old = time.time() - 10 * 24 * 3600
    os.utime(path, (old, old))


def test_cleanup_orphaned_uploads_only_touches_internal_temp_and_preview_files(tmp_path: Path):
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))

    orphan_temp = tmp_path / "uploads" / ("a" * 64 + "_" + "b" * 32 + "_orphan.pdf")
    orphan_preview = tmp_path / "uploads" / "previews" / "preview_deadbeef_orphan.png"
    referenced_preview = tmp_path / "uploads" / "previews" / "preview_cafebabe_kept.png"
    user_target = tmp_path / "repo" / "deadbeef_user_file.pdf"
    weird_name = tmp_path / "uploads" / "notes-final.pdf"

    for path in (orphan_temp, orphan_preview, referenced_preview, user_target, weird_name):
        _make_old_file(path)

    created = storage.create_temp_file("kept.pdf", b"%PDF-1.4\n%%EOF\n", "cafebabe" * 8, "document")
    assert created["success"] is True
    kept_file_id = int(created["file_id"])
    kept_temp_path = Path(str(storage.get_file_path(kept_file_id)))
    _make_old_file(kept_temp_path, b"%PDF-1.4\n%%EOF\n")

    conn = storage._get_connection()
    try:
        conn.execute(
            "UPDATE files SET preview_path = ? WHERE file_id = ?",
            (str(referenced_preview), kept_file_id),
        )
        conn.commit()
    finally:
        conn.close()

    actions = storage.cleanup_orphaned_uploads(preview_ttl_days=0, dry_run=False)
    touched_paths = {str(item["path"]): item for item in actions}

    assert str(orphan_temp) in touched_paths
    assert str(orphan_preview) in touched_paths
    assert str(referenced_preview) not in touched_paths
    assert str(user_target) not in touched_paths
    assert str(weird_name) not in touched_paths
    assert not orphan_temp.exists()
    assert not orphan_preview.exists()
    assert kept_temp_path.exists()
    assert referenced_preview.exists()
    assert user_target.exists()
    assert weird_name.exists()
    assert touched_paths[str(orphan_temp)]["status"] == "deleted"
    assert touched_paths[str(orphan_preview)]["status"] == "deleted"


def test_cleanup_orphaned_uploads_reports_permission_error_clearly(monkeypatch, tmp_path: Path):
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    blocked_temp = tmp_path / "uploads" / ("c" * 64 + "_" + "d" * 32 + "_blocked.pdf")
    _make_old_file(blocked_temp)

    original_unlink = Path.unlink

    def guarded_unlink(self: Path, *args, **kwargs) -> None:
        if self == blocked_temp:
            raise PermissionError("access denied")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", guarded_unlink)

    actions = storage.cleanup_orphaned_uploads(preview_ttl_days=0, dry_run=False)

    assert blocked_temp.exists()
    assert len(actions) == 1
    assert actions[0]["type"] == "temp"
    assert actions[0]["path"] == str(blocked_temp)
    assert actions[0]["status"] == "error"
    assert actions[0]["error"] == "PermissionError: access denied"
