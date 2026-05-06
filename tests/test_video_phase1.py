from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import core_processor
from core import FileProcessor, FileUtils, VIDEO_TAGS, VIDEO_TOOL_TIMEOUT_SECONDS
from services import UploadedFileData, analyze_one_upload
from storage import StorageManager


def test_video_extensions_defined():
    assert ".mp4" in FileUtils.VIDEO_EXTENSIONS
    assert ".mov" in FileUtils.VIDEO_EXTENSIONS
    assert ".mkv" in FileUtils.VIDEO_EXTENSIONS
    assert ".mp4" in FileUtils.ALLOWED_UPLOAD_EXTENSIONS


def test_video_tags_defined():
    assert isinstance(VIDEO_TAGS, list)
    assert VIDEO_TAGS


def test_extract_video_metadata_uses_timeout(monkeypatch, tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-video")
    processor = FileProcessor()
    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, timeout, text):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return SimpleNamespace(
            returncode=0,
            stdout='{"format":{"duration":"4.0"},"streams":[{"codec_type":"video","width":320,"height":240,"codec_name":"h264","r_frame_rate":"30/1"}]}',
            stderr="",
        )

    core_processor.is_ffmpeg_available.cache_clear()
    monkeypatch.setattr(core_processor, "is_ffmpeg_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", fake_run)

    metadata = processor._extract_video_metadata(str(video_path), timeout_seconds=VIDEO_TOOL_TIMEOUT_SECONDS)

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[0] == "ffprobe"
    assert captured["timeout"] == VIDEO_TOOL_TIMEOUT_SECONDS
    assert metadata["duration_seconds"] == 4.0
    assert metadata["width"] == 320
    assert metadata["height"] == 240
    assert metadata["video_codec"] == "h264"


def test_generate_video_thumbnail_timeout_returns_clean_error(monkeypatch, tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-video")
    processor = FileProcessor()
    preview_path = tmp_path / "preview.jpg"

    core_processor.is_ffmpeg_available.cache_clear()
    monkeypatch.setattr(core_processor, "is_ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        core_processor.FileUtils,
        "build_preview_path",
        staticmethod(lambda _path: str(preview_path)),
    )
    monkeypatch.setattr(
        processor,
        "_extract_video_metadata",
        lambda *_args, **_kwargs: {"duration_seconds": 4.0},
    )

    def fake_run(cmd, capture_output, timeout, text):
        assert cmd[0] == "ffmpeg"
        assert timeout == VIDEO_TOOL_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    preview, error = processor._generate_video_thumbnail(
        str(video_path),
        timeout_seconds=VIDEO_TOOL_TIMEOUT_SECONDS,
    )

    assert preview is None
    assert error is not None
    assert "timeout" in error.lower() or "逾時" in error


def test_extract_metadata_gracefully_falls_back_without_ffmpeg(monkeypatch, tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-video")
    processor = FileProcessor()
    core_processor.is_ffmpeg_available.cache_clear()
    monkeypatch.setattr(core_processor, "is_ffmpeg_available", lambda: False)

    metadata = processor.extract_metadata(str(video_path))

    assert metadata["file_type"] == "video"
    assert metadata["video"]["media_type"] == "video"
    assert metadata["preview_path"] is None
    assert metadata["video"]["ffprobe_error"] is not None


def test_core_processor_import_does_not_run_ffmpeg_detection(monkeypatch):
    import importlib
    import sys

    original_run = subprocess.run

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not execute during import")

    monkeypatch.setattr(subprocess, "run", fail_run)
    sys.modules.pop("core_processor", None)
    try:
        reloaded = importlib.import_module("core_processor")
        assert hasattr(reloaded, "is_ffmpeg_available")
    finally:
        monkeypatch.setattr(subprocess, "run", original_run)
        sys.modules.pop("core_processor", None)
        importlib.import_module("core_processor")


def test_video_duplicate_detection_still_works(tmp_path: Path):
    db_path = str(tmp_path / "test.db")
    repo_root = str(tmp_path / "repo")
    upload_dir = str(tmp_path / "uploads")
    storage = StorageManager(db_path, repo_root, upload_dir)
    processor = FileProcessor()
    content = b"video-bytes"
    source = tmp_path / "hash-source.mp4"
    source.write_bytes(content)
    file_hash = processor.get_file_hash(source)
    created = storage.create_temp_file("test_video.mp4", content, file_hash, "video")

    assert created["success"] is True


def test_analyze_one_upload_infers_video_from_extension_without_video_mime(tmp_path: Path):
    db_path = str(tmp_path / "test.db")
    repo_root = str(tmp_path / "repo")
    upload_dir = str(tmp_path / "uploads")
    storage = StorageManager(db_path, repo_root, upload_dir)
    processor = FileProcessor()
    uploaded = UploadedFileData(name="clip.webm", content=b"video-bytes", mime_type="application/octet-stream")

    analyzed, dup, err = analyze_one_upload(
        uploaded,
        processor=processor,
        storage=storage,
        processing_options={"enable_ocr": False, "enable_pdf_preview": False},
    )

    assert dup is None
    assert err is None
    assert analyzed is not None
    stored = storage.get_file_by_id(analyzed.file_id)
    assert stored is not None
    assert stored["file_type"] == "video"
