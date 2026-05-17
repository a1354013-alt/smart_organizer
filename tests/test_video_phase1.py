from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import core_processor
from core import VIDEO_TAGS, VIDEO_TOOL_TIMEOUT_SECONDS, FileProcessor, FileUtils
from services import UploadedFileData, analyze_one_upload
from storage import StorageManager


def _assert_core_processor_import_snippet_succeeds(snippet: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


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


def test_generate_video_thumbnail_ffmpeg_command_uses_input_and_output_once(monkeypatch, tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-video")
    preview_base_path = tmp_path / "preview.png"
    expected_preview_path = tmp_path / "preview.jpg"
    processor = FileProcessor()
    captured: dict[str, object] = {}

    core_processor.is_ffmpeg_available.cache_clear()
    monkeypatch.setattr(core_processor, "is_ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        core_processor.FileUtils,
        "build_preview_path",
        staticmethod(lambda _path: str(preview_base_path)),
    )

    def fake_run(cmd, capture_output, timeout, text):
        captured["cmd"] = cmd
        expected_preview_path.write_bytes(b"jpg")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    preview, error = processor._generate_video_thumbnail(str(video_path), timeout_seconds=7)

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert preview == str(expected_preview_path)
    assert error is None
    assert cmd == [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        "thumbnail,scale=320:-1",
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(expected_preview_path),
    ]
    assert cmd.count(str(video_path)) == 1
    assert cmd[cmd.index("-i") + 1] == str(video_path)
    assert cmd[-1] == str(expected_preview_path)
    assert str(video_path) not in cmd[cmd.index("-vf") + 1 :]


def test_generate_video_thumbnail_falls_back_when_ffmpeg_unavailable(monkeypatch, tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-video")

    monkeypatch.setattr(core_processor, "is_ffmpeg_available", lambda: False)

    preview, error = FileProcessor()._generate_video_thumbnail(str(video_path), timeout_seconds=7)

    assert preview is None
    assert error == "ffmpeg is unavailable; thumbnail generation was skipped."


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


def test_core_processor_import_does_not_run_ffmpeg_detection():
    _assert_core_processor_import_snippet_succeeds(
        """
import subprocess

def fail_run(*args, **kwargs):
    raise AssertionError("subprocess.run should not execute during import")

subprocess.run = fail_run
import core_processor
assert hasattr(core_processor, "is_ffmpeg_available")
"""
    )


def test_core_processor_invalid_video_timeout_env_does_not_crash_on_import():
    _assert_core_processor_import_snippet_succeeds(
        """
import os

os.environ["VIDEO_TOOL_TIMEOUT_SECONDS"] = "not-a-number"
import core_processor
assert core_processor.VIDEO_TOOL_TIMEOUT_SECONDS == 10
"""
    )


def test_core_processor_non_positive_video_timeout_env_falls_back_to_minimum():
    _assert_core_processor_import_snippet_succeeds(
        """
import os

os.environ["VIDEO_TOOL_TIMEOUT_SECONDS"] = ""
import core_processor
assert core_processor.VIDEO_TOOL_TIMEOUT_SECONDS == 10
"""
    )

    for raw in ("0", "-5"):
        _assert_core_processor_import_snippet_succeeds(
            f"""
import os

os.environ["VIDEO_TOOL_TIMEOUT_SECONDS"] = {raw!r}
import core_processor
assert core_processor.VIDEO_TOOL_TIMEOUT_SECONDS == 1
"""
        )


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


def test_extract_metadata_rejects_fake_video_container_without_crashing(tmp_path: Path):
    video_path = tmp_path / "fake.mp4"
    video_path.write_bytes(b"this is not a video container")

    metadata = FileProcessor().extract_metadata(str(video_path))

    assert metadata["file_type"] == "video"
    assert metadata["video"]["ffprobe_error"]
    assert any("video container validation failed" in note for note in metadata["notes"])


def test_analyze_one_upload_allows_fake_video_but_marks_it_partial(tmp_path: Path):
    storage = StorageManager(str(tmp_path / "test.db"), str(tmp_path / "repo"), str(tmp_path / "uploads"))
    uploaded = UploadedFileData(name="fake.mp4", content=b"not-a-real-video", mime_type="video/mp4")

    analyzed, duplicate, err = analyze_one_upload(
        uploaded,
        processor=FileProcessor(),
        storage=storage,
        processing_options={"enable_ocr": False, "enable_pdf_preview": False},
    )

    assert duplicate is None
    assert err is None
    assert analyzed is not None
    assert analyzed.analysis_status == "WARNING"
    assert analyzed.metadata["file_type"] == "video"
    assert any("video container validation failed" in note for note in analyzed.metadata["notes"])


def test_extract_metadata_valid_video_container_falls_back_when_tools_unavailable(monkeypatch, tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    monkeypatch.setattr("core_processor.is_ffmpeg_available", lambda: False)

    metadata = FileProcessor().extract_metadata(str(video_path))

    assert metadata["file_type"] == "video"
    assert metadata["video"]["ffprobe_error"] == "ffprobe is unavailable; video metadata could not be collected."
    assert any("ffprobe is unavailable" in note for note in metadata["notes"])
