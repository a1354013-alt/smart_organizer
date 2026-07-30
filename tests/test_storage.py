from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import storage_base
from malware_scanner import MalwareScanResult, _file_identity, file_sha256
from path_utils import canonical_path_key
from sqlite_utils import open_sqlite
from storage import StorageManager


def _make_workspace_tmp_dir() -> Path:
    return Path("tests") / ("_unused_" + uuid.uuid4().hex)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _require_record(record: dict[str, object] | None) -> Mapping[str, object]:
    assert record is not None
    return record


def _page_items(page: dict[str, object]) -> list[Mapping[str, object]]:
    items = page.get("items")
    assert isinstance(items, list)
    return items


def _make_cache_storage(tmp_path: Path) -> tuple[StorageManager, Path]:
    db_path = tmp_path / "cache.db"
    storage = StorageManager(str(db_path), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    return storage, db_path


def _build_cache_result(
    file_path: Path,
    *,
    verdict: str = "clean",
    scan_health: str = "ok",
    backend: str = "clamd",
    engine_version: str = "1.4.3",
    database_version: str = "12345",
    database_date: str = "2026-07-28",
    message: str = "OK",
    elapsed_seconds: float = 0.25,
) -> tuple[MalwareScanResult, str, int, int, str]:
    sha256 = file_sha256(file_path)
    size_bytes, mtime_ns, file_identity = _file_identity(file_path)
    assert size_bytes is not None
    assert mtime_ns is not None
    assert file_identity is not None
    return (
        MalwareScanResult(
            verdict=verdict,  # type: ignore[arg-type]
            scan_health=scan_health,  # type: ignore[arg-type]
            scanner="ClamAV",
            file_path=str(file_path.resolve()),
            backend=backend,
            engine_version=engine_version,
            database_version=database_version,
            database_date=database_date,
            message=message,
            elapsed_seconds=elapsed_seconds,
            file_sha256=sha256,
            file_size=size_bytes,
            file_mtime_ns=mtime_ns,
            file_inode=file_identity,
        ),
        sha256,
        size_bytes,
        mtime_ns,
        file_identity,
    )


def _cache_counts(db_path: Path) -> tuple[int, int]:
    with open_sqlite(db_path) as conn:
        content_rows = int(conn.execute("SELECT COUNT(*) FROM malware_scan_cache").fetchone()[0])
        identity_rows = int(conn.execute("SELECT COUNT(*) FROM malware_scan_cache_identities").fetchone()[0])
    return content_rows, identity_rows


def test_malware_cache_clean_write_persists_content_and_identity_rows(tmp_path: Path):
    storage, db_path = _make_cache_storage(tmp_path)
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"cache me")
    result, sha256, size_bytes, mtime_ns, file_identity = _build_cache_result(file_path)

    saved = storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        result=result,
        scan_policy_version="standard-v1",
    )

    assert saved is True
    assert _cache_counts(db_path) == (1, 1)
    with open_sqlite(db_path) as conn:
        content_row = conn.execute(
            """
            SELECT sha256, scanner_backend, engine_version, database_version, database_date, scan_policy_version,
                   verdict, scan_health
            FROM malware_scan_cache
            """
        ).fetchone()
        identity_row = conn.execute(
            """
            SELECT canonical_path_key, size_bytes, mtime_ns, file_identity, cache_id
            FROM malware_scan_cache_identities
            """
        ).fetchone()
    assert content_row == (
        sha256,
        "clamd",
        "1.4.3",
        "12345",
        "2026-07-28",
        "standard-v1",
        "clean",
        "ok",
    )
    assert identity_row is not None
    assert identity_row[0] == canonical_path_key(str(file_path.resolve()))
    assert identity_row[1] == size_bytes
    assert identity_row[2] == mtime_ns
    assert identity_row[3] == file_identity
    assert int(identity_row[4]) > 0
    storage.close()


def test_malware_cache_content_and_unchanged_lookups_succeed_after_valid_write(tmp_path: Path):
    storage, _db_path = _make_cache_storage(tmp_path)
    file_path = tmp_path / "lookup.bin"
    file_path.write_bytes(b"lookup payload")
    result, sha256, size_bytes, mtime_ns, file_identity = _build_cache_result(file_path)
    assert storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        result=result,
        scan_policy_version="standard-v1",
    ) is True

    content_hit = storage.get_malware_scan_cache_by_content(
        sha256=sha256,
        scanner_backend="clamd",
        engine_version="1.4.3",
        database_version="12345",
        database_date="2026-07-28",
        scan_policy_version="standard-v1",
    )
    unchanged_hit = storage.get_malware_scan_cache_for_unchanged_file(
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        scanner_backend="clamd",
        engine_version="1.4.3",
        database_version="12345",
        database_date="2026-07-28",
        scan_policy_version="standard-v1",
    )

    assert content_hit is not None
    assert content_hit["verdict"] == "clean"
    assert content_hit["scan_health"] == "ok"
    assert content_hit["sha256"] == sha256
    assert int(content_hit["cache_id"]) > 0
    assert unchanged_hit is not None
    assert unchanged_hit["verdict"] == "clean"
    assert unchanged_hit["scan_health"] == "ok"
    assert unchanged_hit["cache_id"] == content_hit["cache_id"]
    storage.close()


def test_malware_cache_none_compatibility_values_normalize_without_duplicates(tmp_path: Path):
    storage, db_path = _make_cache_storage(tmp_path)
    file_path = tmp_path / "nullable-compat.bin"
    file_path.write_bytes(b"nullable compatibility payload")
    result, sha256, size_bytes, mtime_ns, file_identity = _build_cache_result(
        file_path,
        engine_version="",
        database_version="",
        database_date="",
    )
    result = MalwareScanResult(
        verdict=result.verdict,
        scan_health=result.scan_health,
        scanner=result.scanner,
        file_path=result.file_path,
        backend=result.backend,
        threat_name=result.threat_name,
        message=result.message,
        elapsed_seconds=result.elapsed_seconds,
        return_code=result.return_code,
        engine_version=None,
        database_version=None,
        database_date=None,
        cache_hit=result.cache_hit,
        file_sha256=result.file_sha256,
        file_size=result.file_size,
        file_mtime_ns=result.file_mtime_ns,
        file_inode=result.file_inode,
        file_streamed_bytes=result.file_streamed_bytes,
    )

    assert storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        result=result,
        scan_policy_version="standard-v1",
    ) is True
    assert storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        result=result,
        scan_policy_version="standard-v1",
    ) is True

    assert _cache_counts(db_path) == (1, 1)
    with open_sqlite(db_path) as conn:
        content_row = conn.execute(
            """
            SELECT engine_version, database_version, database_date
            FROM malware_scan_cache
            """
        ).fetchone()
        identity_row = conn.execute(
            """
            SELECT engine_version, database_version, database_date
            FROM malware_scan_cache_identities
            """
        ).fetchone()
    assert content_row == ("", "", "")
    assert identity_row == ("", "", "")
    storage.close()


def test_malware_cache_none_and_empty_compatibility_lookups_are_equivalent(tmp_path: Path):
    storage, _db_path = _make_cache_storage(tmp_path)
    file_path = tmp_path / "compat-equivalent.bin"
    file_path.write_bytes(b"compatibility lookup payload")
    result, sha256, size_bytes, mtime_ns, file_identity = _build_cache_result(
        file_path,
        engine_version="",
        database_version="",
        database_date="",
    )
    result = MalwareScanResult(
        verdict=result.verdict,
        scan_health=result.scan_health,
        scanner=result.scanner,
        file_path=result.file_path,
        backend=result.backend,
        threat_name=result.threat_name,
        message=result.message,
        elapsed_seconds=result.elapsed_seconds,
        return_code=result.return_code,
        engine_version=None,
        database_version=None,
        database_date=None,
        cache_hit=result.cache_hit,
        file_sha256=result.file_sha256,
        file_size=result.file_size,
        file_mtime_ns=result.file_mtime_ns,
        file_inode=result.file_inode,
        file_streamed_bytes=result.file_streamed_bytes,
    )
    assert storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        result=result,
        scan_policy_version="standard-v1",
    ) is True

    content_none = storage.get_malware_scan_cache_by_content(
        sha256=sha256,
        scanner_backend="clamd",
        engine_version=None,
        database_version=None,
        database_date=None,
        scan_policy_version="standard-v1",
    )
    content_empty = storage.get_malware_scan_cache_by_content(
        sha256=sha256,
        scanner_backend="clamd",
        engine_version="",
        database_version="",
        database_date="",
        scan_policy_version="standard-v1",
    )
    unchanged_none = storage.get_malware_scan_cache_for_unchanged_file(
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        scanner_backend="clamd",
        engine_version=None,
        database_version=None,
        database_date=None,
        scan_policy_version="standard-v1",
    )
    unchanged_empty = storage.get_malware_scan_cache_for_unchanged_file(
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        scanner_backend="clamd",
        engine_version="",
        database_version="",
        database_date="",
        scan_policy_version="standard-v1",
    )

    assert content_none is not None
    assert content_empty is not None
    assert content_none["cache_id"] == content_empty["cache_id"]
    assert unchanged_none is not None
    assert unchanged_empty is not None
    assert unchanged_none["cache_id"] == unchanged_empty["cache_id"]
    storage.close()


def test_malware_cache_identical_files_share_content_row_but_keep_separate_identities(tmp_path: Path):
    storage, db_path = _make_cache_storage(tmp_path)
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    shared_bytes = b"same bytes"
    first.write_bytes(shared_bytes)
    second.write_bytes(shared_bytes)
    first_result, sha256, first_size, first_mtime_ns, first_identity = _build_cache_result(first)
    second_result, _, second_size, second_mtime_ns, second_identity = _build_cache_result(second)

    assert storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(first.resolve()),
        size_bytes=first_size,
        mtime_ns=first_mtime_ns,
        file_identity=first_identity,
        result=first_result,
        scan_policy_version="standard-v1",
    ) is True
    assert storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(second.resolve()),
        size_bytes=second_size,
        mtime_ns=second_mtime_ns,
        file_identity=second_identity,
        result=second_result,
        scan_policy_version="standard-v1",
    ) is True

    assert _cache_counts(db_path) == (1, 2)
    assert storage.get_malware_scan_cache_for_unchanged_file(
        canonical_path=str(first.resolve()),
        size_bytes=first_size,
        mtime_ns=first_mtime_ns,
        file_identity=first_identity,
        scanner_backend="clamd",
        engine_version="1.4.3",
        database_version="12345",
        database_date="2026-07-28",
        scan_policy_version="standard-v1",
    ) is not None
    assert storage.get_malware_scan_cache_for_unchanged_file(
        canonical_path=str(second.resolve()),
        size_bytes=second_size,
        mtime_ns=second_mtime_ns,
        file_identity=second_identity,
        scanner_backend="clamd",
        engine_version="1.4.3",
        database_version="12345",
        database_date="2026-07-28",
        scan_policy_version="standard-v1",
    ) is not None
    storage.close()


def test_malware_cache_same_path_upsert_updates_identity_without_duplicate(tmp_path: Path):
    storage, db_path = _make_cache_storage(tmp_path)
    file_path = tmp_path / "update.bin"
    file_path.write_bytes(b"stable content")
    first_result, sha256, size_bytes, first_mtime_ns, file_identity = _build_cache_result(file_path, elapsed_seconds=0.25)
    assert storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=first_mtime_ns,
        file_identity=file_identity,
        result=first_result,
        scan_policy_version="standard-v1",
    ) is True

    os.utime(file_path, ns=(first_mtime_ns + 5_000_000, first_mtime_ns + 5_000_000))
    second_result, _, _size_bytes, second_mtime_ns, second_identity = _build_cache_result(file_path, elapsed_seconds=0.5)
    assert storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=second_mtime_ns,
        file_identity=second_identity,
        result=second_result,
        scan_policy_version="standard-v1",
    ) is True

    assert _cache_counts(db_path) == (1, 1)
    with open_sqlite(db_path) as conn:
        identity_row = conn.execute(
            "SELECT mtime_ns, file_identity FROM malware_scan_cache_identities"
        ).fetchone()
    assert identity_row == (second_mtime_ns, second_identity)
    storage.close()


@pytest.mark.parametrize(
    ("engine_version", "database_version", "database_date", "scan_policy_version"),
    [
        ("1.4.4", "12345", "2026-07-28", "standard-v1"),
        ("1.4.3", "99999", "2026-07-28", "standard-v1"),
        ("1.4.3", "12345", "2026-07-27", "standard-v1"),
        ("1.4.3", "12345", "2026-07-28", "strict-v1"),
    ],
)
def test_malware_cache_compatibility_dimensions_must_match(
    tmp_path: Path,
    engine_version: str,
    database_version: str,
    database_date: str,
    scan_policy_version: str,
):
    storage, _db_path = _make_cache_storage(tmp_path)
    file_path = tmp_path / "compat.bin"
    file_path.write_bytes(b"compat payload")
    result, sha256, size_bytes, mtime_ns, file_identity = _build_cache_result(file_path)
    assert storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        result=result,
        scan_policy_version="standard-v1",
    ) is True

    assert storage.get_malware_scan_cache_by_content(
        sha256=sha256,
        scanner_backend="clamd",
        engine_version=engine_version,
        database_version=database_version,
        database_date=database_date,
        scan_policy_version=scan_policy_version,
    ) is None
    assert storage.get_malware_scan_cache_for_unchanged_file(
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        scanner_backend="clamd",
        engine_version=engine_version,
        database_version=database_version,
        database_date=database_date,
        scan_policy_version=scan_policy_version,
    ) is None
    storage.close()


@pytest.mark.parametrize("scan_health", ["timeout", "error", "incomplete", "database_outdated", "mode_excluded"])
def test_malware_cache_rejects_non_reusable_healths(tmp_path: Path, scan_health: str):
    storage, db_path = _make_cache_storage(tmp_path)
    file_path = tmp_path / f"{scan_health}.bin"
    file_path.write_bytes(scan_health.encode("utf-8"))
    result, sha256, size_bytes, mtime_ns, file_identity = _build_cache_result(
        file_path,
        verdict="not_scanned",
        scan_health=scan_health,
        message=scan_health,
    )

    saved = storage.upsert_malware_scan_cache(
        sha256=sha256,
        canonical_path=str(file_path.resolve()),
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        file_identity=file_identity,
        result=result,
        scan_policy_version="standard-v1",
    )

    assert saved is False
    assert _cache_counts(db_path) == (0, 0)
    storage.close()


def test_create_temp_file_and_duplicate_detection():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)

    res1 = storage.create_temp_file('inv<>:"/\\\\|?*..a.pdf', payload, file_hash, "document")
    assert res1["success"] is True

    info = _require_record(storage.get_file_by_id(res1["file_id"]))
    assert str(info["original_name"]).endswith(".pdf")
    assert str(info["safe_name"]).endswith(".pdf")
    assert isinstance(info["temp_path"], str)

    res2 = storage.create_temp_file("anything.pdf", payload, file_hash, "document")
    assert res2["success"] is False
    assert res2["reason"] == "DUPLICATE"


def test_create_temp_file_uses_unique_temp_paths_for_different_hashes(tmp_path: Path):
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    first_payload = _minimal_pdf_bytes() + b"first"
    second_payload = _minimal_pdf_bytes() + b"second"

    first = storage.create_temp_file("shared.pdf", first_payload, _sha256(first_payload), "document")
    second = storage.create_temp_file("shared.pdf", second_payload, _sha256(second_payload), "document")

    first_info = _require_record(storage.get_file_by_id(first["file_id"]))
    second_info = _require_record(storage.get_file_by_id(second["file_id"]))
    assert first_info["temp_path"] != second_info["temp_path"]


def test_create_temp_file_does_not_collide_when_hash_prefix_matches(tmp_path: Path):
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    payload = _minimal_pdf_bytes()
    first_hash = "deadbeef" + ("1" * 56)
    second_hash = "deadbeef" + ("2" * 56)

    first = storage.create_temp_file("shared.pdf", payload + b"1", first_hash, "document")
    second = storage.create_temp_file("shared.pdf", payload + b"2", second_hash, "document")

    first_info = _require_record(storage.get_file_by_id(first["file_id"]))
    second_info = _require_record(storage.get_file_by_id(second["file_id"]))
    assert first_info["temp_path"] != second_info["temp_path"]


def test_update_metadata_allows_preview_under_explicit_safe_roots(tmp_path: Path):
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    payload = _minimal_pdf_bytes()
    created = storage.create_temp_file("safe-preview.pdf", payload, _sha256(payload), "document")
    file_id = int(created["file_id"])

    upload_preview = tmp_path / "uploads" / "previews" / "preview.png"
    upload_preview.parent.mkdir(parents=True, exist_ok=True)
    upload_preview.write_bytes(b"preview")

    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-01-01",
            "main_topic": "Docs",
            "summary": "",
            "is_scanned": False,
            "preview_path": str(upload_preview),
        },
    )

    stored_preview = _require_record(storage.get_file_by_id(file_id))["preview_path"]
    assert stored_preview is not None
    assert Path(str(stored_preview)).samefile(upload_preview)

    repo_preview = tmp_path / "repo" / "previews" / "preview.png"
    repo_preview.parent.mkdir(parents=True, exist_ok=True)
    repo_preview.write_bytes(b"preview")

    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-01-01",
            "main_topic": "Docs",
            "summary": "",
            "is_scanned": False,
            "preview_path": str(repo_preview),
        },
    )

    stored_preview = _require_record(storage.get_file_by_id(file_id))["preview_path"]
    assert stored_preview is not None
    assert Path(str(stored_preview)).samefile(repo_preview)


def test_update_metadata_rejects_preview_under_project_sibling_and_traversal(tmp_path: Path):
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    payload = _minimal_pdf_bytes()
    created = storage.create_temp_file("unsafe-preview.pdf", payload, _sha256(payload), "document")
    file_id = int(created["file_id"])

    sibling_preview = tmp_path / "logs" / "preview.png"
    sibling_preview.parent.mkdir(parents=True, exist_ok=True)
    sibling_preview.write_bytes(b"preview")

    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-01-01",
            "main_topic": "Docs",
            "summary": "",
            "is_scanned": False,
            "preview_path": str(sibling_preview),
        },
    )

    assert _require_record(storage.get_file_by_id(file_id))["preview_path"] in (None, "")

    traversal_preview = tmp_path / "uploads" / ".." / "logs" / "preview.png"
    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-01-01",
            "main_topic": "Docs",
            "summary": "",
            "is_scanned": False,
            "preview_path": str(traversal_preview),
        },
    )

    assert _require_record(storage.get_file_by_id(file_id))["preview_path"] in (None, "")


def test_mem_storage_file_map_operations_are_thread_safe():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    assert storage._mem_files is not None
    storage._mem_files["mem://uploads/source.bin"] = b"payload"

    def worker(index: int) -> None:
        dst = f"mem://repo/copy-{index}.bin"
        storage._copy_path("mem://uploads/source.bin", dst)
        assert storage._path_exists(dst)
        storage._remove_path(dst)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker, range(32)))

    assert storage._path_exists("mem://uploads/source.bin")


def test_create_temp_file_keeps_temp_path_inside_upload_dir(tmp_path: Path):
    upload_dir = tmp_path / "uploads"
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(upload_dir))
    payload = _minimal_pdf_bytes()
    created = storage.create_temp_file("../unsafe/../name.pdf", payload, _sha256(payload + b"path"), "document")

    info = _require_record(storage.get_file_by_id(created["file_id"]))
    temp_path = Path(str(info["temp_path"])).resolve()
    assert temp_path.parent == upload_dir.resolve()


def test_finalize_organization_uses_safe_name():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    original_name = 'inv<>:"/\\\\|?*..a.pdf'

    res = storage.create_temp_file(original_name, payload, file_hash, "document")
    file_id = res["file_id"]

    final_path = storage.finalize_organization(file_id, "2026-04-08", "?潛巨", original_name)
    assert isinstance(final_path, str)
    assert "<" not in os.path.basename(final_path)
    assert ">" not in os.path.basename(final_path)

    info = _require_record(storage.get_file_by_id(file_id))
    assert info["status"] == "COMPLETED"
    assert info["final_path"] == final_path
    assert info["final_name"] == os.path.basename(final_path)


def test_search_content_fts_and_fallback():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    res = storage.create_temp_file("invoice.pdf", payload, file_hash, "document")
    file_id = res["file_id"]

    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-04-08",
            "main_topic": "?潛巨",
            "summary": "皜祈岫??",
            "content": "hello world invoice 123",
            "is_scanned": False,
            "preview_path": None,
            "classification_reason": "test",
            "tag_scores": {"?潛巨": 1.0},
        },
    )

    r1 = storage.search_content("hello")
    assert any(r["file_id"] == file_id for r in r1)

    r2 = storage.search_content("?潛巨")
    assert any(r["file_id"] == file_id for r in r2)

    r3 = storage.search_content('(" )')
    assert r3 == []


def test_migration_failure_aborts_startup(tmp_path: Path):
    db_path = os.path.join(str(tmp_path), "bad.db")
    with open_sqlite(db_path) as conn, conn:
        conn.execute("CREATE TABLE sys_config (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute('INSERT INTO sys_config(key, value) VALUES ("schema_version", "not-an-int")')

    with pytest.raises(RuntimeError):
        StorageManager(db_path, ":memory:", ":memory:")


def test_close_is_idempotent():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    storage.close()
    storage.close()


def test_storage_manager_context_manager_closes_keepalive_connection():
    with StorageManager(":memory:", ":memory:", ":memory:") as storage:
        record = storage.create_temp_file("invoice.pdf", _minimal_pdf_bytes(), "hash-context", "document")
        assert record["success"] is True

    with pytest.raises(RuntimeError, match="closed"):
        storage.get_file_by_id(1)


def test_two_storage_managers_can_share_a_memory_uri(tmp_path: Path):
    shared_db = f"file:smart_organizer_shared_{uuid.uuid4().hex}?mode=memory&cache=shared"
    repo_root = str(tmp_path / "repo")
    upload_dir = str(tmp_path / "uploads")
    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload + b"shared")

    first = StorageManager(shared_db, repo_root, upload_dir)
    second = StorageManager(shared_db, repo_root, upload_dir)

    created = first.create_temp_file("shared.pdf", payload, file_hash, "document")
    record = second.get_file_by_id(int(created["file_id"]))

    assert created["success"] is True
    assert record is not None
    assert record["original_name"] == "shared.pdf"


def test_shared_memory_keepalive_preserves_data_until_close(tmp_path: Path):
    shared_db = f"file:smart_organizer_keepalive_{uuid.uuid4().hex}?mode=memory&cache=shared"
    storage = StorageManager(shared_db, str(tmp_path / "repo"), str(tmp_path / "uploads"))
    payload = _minimal_pdf_bytes()
    created = storage.create_temp_file("persist.pdf", payload, _sha256(payload + b"keepalive"), "document")

    with open_sqlite(shared_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM files WHERE file_id = ?", (int(created["file_id"]),)).fetchone()[0]

    assert count == 1
    storage.close()


def test_shared_memory_data_does_not_survive_after_keepalive_close(tmp_path: Path):
    shared_db = f"file:smart_organizer_lifecycle_{uuid.uuid4().hex}?mode=memory&cache=shared"
    storage = StorageManager(shared_db, str(tmp_path / "repo"), str(tmp_path / "uploads"))
    created = storage.create_temp_file("gone.pdf", _minimal_pdf_bytes(), _sha256(b"gone"), "document")
    assert created["success"] is True

    storage.close()

    with pytest.raises(sqlite3.OperationalError, match="no such table"), open_sqlite(shared_db) as conn:
        conn.execute("SELECT COUNT(*) FROM files").fetchone()


def test_initialization_failure_closes_keepalive_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    shared_db = f"file:smart_organizer_init_fail_{uuid.uuid4().hex}?mode=memory&cache=shared"
    closed = {"count": 0}
    real_connect = storage_base.connect_sqlite

    class TrackingConnection:
        def __init__(self, real_conn: sqlite3.Connection) -> None:
            self._real = real_conn

        def close(self) -> None:
            closed["count"] += 1
            self._real.close()

    def tracking_connect(target: str | os.PathLike[str], **kwargs: object) -> TrackingConnection | sqlite3.Connection:
        conn = real_connect(target, **kwargs)
        if str(target) == shared_db:
            return TrackingConnection(conn)
        return conn

    monkeypatch.setattr(storage_base, "connect_sqlite", tracking_connect)
    monkeypatch.setattr(StorageManager, "_init_db", lambda self: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        StorageManager(shared_db, str(tmp_path / "repo"), str(tmp_path / "uploads"))

    assert closed["count"] == 1


def test_get_records_page_escapes_like_wildcards():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    payload = _minimal_pdf_bytes()

    names = ["100%complete.pdf", "under_score.pdf", "ordinary.pdf"]
    summaries = ["literal percent", "literal underscore", "plain text"]

    for name, summary in zip(names, summaries, strict=True):
        result = storage.create_temp_file(name, payload, _sha256(name.encode("utf-8")), "document")
        file_id = result["file_id"]
        storage.update_file_metadata(
            file_id,
            {
                "standard_date": "2026-05-07",
                "main_topic": "Docs",
                "summary": summary,
                "content": summary,
                "is_scanned": False,
                "preview_path": None,
                "classification_reason": "test",
                "tag_scores": {"Docs": 1.0},
            },
        )

    percent_hits = storage.get_records_page(search="%")
    underscore_hits = storage.get_records_page(search="_")
    keyword_hits = storage.get_records_page(search="ordinary")

    assert [item["original_name"] for item in _page_items(percent_hits)] == ["100%complete.pdf"]
    assert [item["original_name"] for item in _page_items(underscore_hits)] == ["under_score.pdf"]
    assert [item["original_name"] for item in _page_items(keyword_hits)] == ["ordinary.pdf"]


def test_get_records_page_searches_by_tag_and_preserves_all_tags():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    payload = _minimal_pdf_bytes()

    result = storage.create_temp_file("bill.pdf", payload, _sha256(payload + b"bill"), "document")
    file_id = result["file_id"]
    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-05-07",
            "main_topic": "Finance",
            "summary": "monthly payment",
            "content": "statement",
            "is_scanned": False,
            "preview_path": None,
            "classification_reason": "test",
            "tag_scores": {"Bills": 0.9, "Utilities": 0.8},
        },
    )

    hits = storage.get_records_page(search="Bills")

    total = hits.get("total")
    assert isinstance(total, int)
    assert total >= 1
    items = _page_items(hits)
    assert [item["original_name"] for item in items] == ["bill.pdf"]
    assert "Bills" in str(items[0]["all_tags"])
    assert "Utilities" in str(items[0]["all_tags"])


def test_search_content_returns_plain_text_snippets_without_html_tags():
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    res = storage.create_temp_file("invoice.pdf", payload, _sha256(payload + b"plain"), "document")
    file_id = res["file_id"]

    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-04-08",
            "main_topic": "Invoices",
            "summary": "invoice summary",
            "content": "alpha invoice beta",
            "is_scanned": False,
            "preview_path": None,
            "classification_reason": "test",
            "tag_scores": {"Invoices": 1.0},
        },
    )

    hits = storage.search_content("invoice")
    assert hits
    snippet = str(hits[0].get("snippet") or "")
    assert "<b>" not in snippet
    assert "</b>" not in snippet
    assert "<mark>" not in snippet


class _FailingInsertCursor:
    def __init__(self, real_cursor: sqlite3.Cursor) -> None:
        self._real = real_cursor

    def execute(self, sql: str, params: Iterable[object] = ()) -> sqlite3.Cursor:
        if "INSERT INTO files" in sql:
            raise sqlite3.OperationalError("forced insert failure")
        return self._real.execute(sql, tuple(params))

    def fetchone(self) -> object:
        return self._real.fetchone()

    @property
    def lastrowid(self) -> int:
        return int(self._real.lastrowid or 0)


class _FailingInsertConnection:
    def __init__(self, real_conn: sqlite3.Connection) -> None:
        self._real = real_conn

    def cursor(self) -> _FailingInsertCursor:
        return _FailingInsertCursor(self._real.cursor())

    def rollback(self) -> None:
        self._real.rollback()

    def commit(self) -> None:
        self._real.commit()

    def close(self) -> None:
        self._real.close()


class _IntegrityInsertNoDuplicateCursor:
    def __init__(self, real_cursor: sqlite3.Cursor) -> None:
        self._real = real_cursor

    def execute(self, sql: str, params: Iterable[object] = ()) -> sqlite3.Cursor:
        if "INSERT INTO files" in sql:
            raise sqlite3.IntegrityError("forced integrity failure")
        return self._real.execute(sql, tuple(params))

    def fetchone(self) -> object:
        return self._real.fetchone()

    @property
    def lastrowid(self) -> int:
        return int(self._real.lastrowid or 0)


class _IntegrityInsertNoDuplicateConnection:
    def __init__(self, real_conn: sqlite3.Connection) -> None:
        self._real = real_conn

    def cursor(self) -> _IntegrityInsertNoDuplicateCursor:
        return _IntegrityInsertNoDuplicateCursor(self._real.cursor())

    def rollback(self) -> None:
        self._real.rollback()

    def commit(self) -> None:
        self._real.commit()

    def close(self) -> None:
        self._real.close()


def test_create_temp_file_cleans_orphan_temp_file_when_db_insert_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = str(tmp_path / "test.db")
    repo_root = str(tmp_path / "repo")
    upload_dir = str(tmp_path / "uploads")
    storage = StorageManager(db_path, repo_root, upload_dir)
    real_get_connection = storage._get_connection

    def failing_get_connection() -> _FailingInsertConnection:
        return _FailingInsertConnection(real_get_connection())

    monkeypatch.setattr(storage, "_get_connection", failing_get_connection)

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload + b"dbfail")
    result = storage.create_temp_file("broken.pdf", payload, file_hash, "document")

    assert result["success"] is False
    assert list(Path(upload_dir).glob("*broken.pdf")) == []


def test_create_temp_file_integrity_error_without_duplicate_returns_error_and_cleans_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = str(tmp_path / "test.db")
    repo_root = str(tmp_path / "repo")
    upload_dir = str(tmp_path / "uploads")
    storage = StorageManager(db_path, repo_root, upload_dir)
    real_get_connection = storage._get_connection

    def failing_get_connection() -> _IntegrityInsertNoDuplicateConnection:
        return _IntegrityInsertNoDuplicateConnection(real_get_connection())

    monkeypatch.setattr(storage, "_get_connection", failing_get_connection)

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload + b"integrity")
    result = storage.create_temp_file("missing-duplicate.pdf", payload, file_hash, "document")

    assert result == {
        "success": False,
        "reason": "ERROR",
        "message": "Database integrity error occurred, but no duplicate file record was found.",
    }
    assert list(Path(upload_dir).glob("*missing-duplicate.pdf")) == []


def test_update_file_metadata_normalizes_topic_and_rejects_preview_escape(tmp_path: Path):
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    payload = _minimal_pdf_bytes()
    result = storage.create_temp_file("invoice.pdf", payload, _sha256(payload + b"topic"), "document")

    storage.update_file_metadata(
        result["file_id"],
        {
            "standard_date": "2026-05-07",
            "main_topic": "發票",
            "summary": "summary",
            "summary_status": "failed",
            "summary_error": "boom",
            "content": "content",
            "is_scanned": False,
            "preview_path": "../evil.png",
            "classification_reason": "test",
            "tag_scores": {"發票": 1.0},
        },
    )

    stored = _require_record(storage.get_file_by_id(result["file_id"]))
    assert stored["main_topic"] == "document.invoice"
    assert stored["preview_path"] is None
    assert stored["summary_status"] == "failed"
    assert stored["summary_error"] == "boom"
