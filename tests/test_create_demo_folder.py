from __future__ import annotations

from datetime import datetime
from pathlib import Path

from scripts.create_demo_folder import DEMO_FILES, create_demo_folder


def test_create_demo_folder_dry_run_does_not_write(tmp_path: Path):
    target = tmp_path / "demo_files"

    result = create_demo_folder(target, dry_run=True, now=datetime(2026, 5, 18, 9, 0, 0))

    assert result.dry_run is True
    assert target.exists() is False
    assert {path.name for path in result.created} == {name for name, _, _ in DEMO_FILES}
    assert result.preserved_existing == ()


def test_create_demo_folder_is_idempotent_and_preserves_existing_user_data(tmp_path: Path):
    target = tmp_path / "demo_files"
    first = create_demo_folder(target, now=datetime(2026, 5, 18, 9, 0, 0))
    assert len(first.created) == len(DEMO_FILES)

    protected = target / "recent_notes.txt"
    protected.write_text("user edited content\n", encoding="utf-8")
    original_mtime = protected.stat().st_mtime

    second = create_demo_folder(target, now=datetime(2026, 5, 19, 9, 0, 0))

    assert second.created == ()
    assert protected in second.preserved_existing
    assert protected.read_text(encoding="utf-8") == "user edited content\n"
    assert protected.stat().st_mtime == original_mtime


def test_create_demo_folder_creates_documented_demo_mix(tmp_path: Path):
    target = tmp_path / "demo_files"
    now = datetime(2026, 5, 18, 9, 0, 0)

    create_demo_folder(target, now=now)

    names = {path.name for path in target.iterdir()}
    assert names == {name for name, _, _ in DEMO_FILES}
    assert (target / "duplicate_a.txt").read_bytes() == (target / "duplicate_b.txt").read_bytes()
    assert "Keep this file" in (target / "readme_keep.txt").read_text(encoding="utf-8")
    age_days = {
        path.name: int(round((now.timestamp() - path.stat().st_mtime) / 86400))
        for path in target.iterdir()
    }
    assert age_days["recent_notes.txt"] <= 7
    assert age_days["old_invoice_2022.txt"] >= 700
    assert age_days["old_large_video.mp4.fake"] >= 800
