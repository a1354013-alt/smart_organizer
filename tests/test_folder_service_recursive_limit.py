from __future__ import annotations

from pathlib import Path

import folder_service
from tests.test_folder_service_malware_results import _FakeScanner, _summary


def test_recursive_malware_enumeration_exact_max_files_is_not_truncated(monkeypatch, tmp_path: Path):
    first = tmp_path / "a" / "first.exe"
    second = tmp_path / "b" / "second.exe"
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    monkeypatch.setattr(folder_service, "MalwareScanner", _FakeScanner)

    result = folder_service.scan_folder_malware(
        str(tmp_path),
        recursive=True,
        max_files=2,
        malware_scan_mode="full",
    )

    summary = _summary(result)
    assert summary["enumerated_files"] == 2
    assert summary["result_records"] == 2
    assert summary["files_sent_to_scanner"] == 2
    assert summary["limit_reached"] is False


def test_recursive_malware_enumeration_sets_truncated_only_when_extra_file_exists(monkeypatch, tmp_path: Path):
    first = tmp_path / "a" / "first.exe"
    second = tmp_path / "b" / "second.exe"
    third = tmp_path / "c" / "third.exe"
    for path in (first, second, third):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    monkeypatch.setattr(folder_service, "MalwareScanner", _FakeScanner)

    result = folder_service.scan_folder_malware(
        str(tmp_path),
        recursive=True,
        max_files=2,
        malware_scan_mode="full",
    )

    summary = _summary(result)
    assert summary["enumerated_files"] == 2
    assert summary["result_records"] == 2
    assert summary["files_sent_to_scanner"] == 2
    assert summary["limit_reached"] is True
