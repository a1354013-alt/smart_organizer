from __future__ import annotations

import os
import time
from pathlib import Path

from folder_organizer import scan_local_folder


def _age_file(path: Path, days: int) -> None:
    timestamp = time.time() - days * 24 * 60 * 60
    os.utime(path, (timestamp, timestamp))


def test_explainable_scores_are_deterministic(tmp_path: Path):
    target = tmp_path / "old_large_video.mp4.fake"
    target.write_bytes(b"x" * 2048)
    _age_file(target, 800)

    first = scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=365, large_file_bytes=1024)
    second = scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=365, large_file_bytes=1024)

    first_record = first["records"][0]
    second_record = second["records"][0]
    for key in ("confidence", "risk_level", "reason_codes", "file_age_score", "size_score", "extension_risk_score"):
        assert first_record[key] == second_record[key]
    assert first_record["candidate_reasons"]
    assert first_record["confidence"] > 0


def test_low_confidence_items_are_manual_or_do_not_touch(tmp_path: Path):
    target = tmp_path / "readme_keep.txt"
    target.write_text("important keep file", encoding="utf-8")
    _age_file(target, 10)

    scan = scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=365, large_file_bytes=1024 * 1024)
    record = scan["records"][0]

    assert record["confidence"] < 0.72
    assert record["risk_level"] in {"needs_manual_check", "do_not_touch"}
    assert record["recommendation"] != "Safe to review"
