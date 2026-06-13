from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

from scripts.create_release_zip import (
    RELEASE_ALLOWLIST,
    build_zip,
    get_version,
    zip_contains_forbidden_entries,
)
from scripts.release_policy import SOURCE_ONLY_RELEASE_FILES
from scripts.validate_release_source import (
    OutputTail,
    StepTimeoutResult,
    _build_timeout_result,
    _format_timeout_message,
    _tail_lines,
    run_step,
)
from scripts.verify_release_zip import default_zip_path_arg, resolve_zip_paths, verify_release_zip

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HANDSHAKE_WAIT_SECONDS = 5.0


def _wait_for_path(path: Path, *, timeout_seconds: float = HANDSHAKE_WAIT_SECONDS) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {path}")


def _write_timeout_probe_script(
    path: Path,
    *,
    ready_file: Path,
    stdout_text: str = "",
    stderr_text: str = "",
    extra_before_sleep: str = "",
) -> Path:
    lines = [
        "import pathlib",
        "import sys",
        "import time",
        "",
        f"ready = pathlib.Path({str(ready_file)!r})",
        "ready.write_text('ready', encoding='utf-8')",
    ]
    if stdout_text:
        lines.append(f"sys.stdout.write({stdout_text!r})")
        lines.append("sys.stdout.flush()")
    if stderr_text:
        lines.append(f"sys.stderr.write({stderr_text!r})")
        lines.append("sys.stderr.flush()")
    if extra_before_sleep:
        lines.append(extra_before_sleep)
    lines.append("time.sleep(30)")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run_step_in_thread(
    command: list[str],
    *,
    timeout_seconds: int,
    timeout_tail_lines: int,
) -> tuple[dict[str, int], threading.Thread]:
    result: dict[str, int] = {}

    def _target() -> None:
        result["returncode"] = run_step(
            command,
            timeout_seconds=timeout_seconds,
            timeout_tail_lines=timeout_tail_lines,
        )

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return result, thread


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_python_release_script_builds_clean_zip(tmp_path):
    zip_path = build_zip(tmp_path, "package.zip")
    assert zip_path.exists()
    assert not zip_contains_forbidden_entries(zip_path)
    assert zip_path.name == "package.zip"
    assert "README.md" in RELEASE_ALLOWLIST

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert not any(name.endswith(".zip") for name in names)
    assert not any(name.startswith("release/") for name in names)
    assert not any(name.startswith("release_ci") for name in names)
    assert not any(name.startswith(".git/") for name in names)
    assert not any(name.startswith("uploads/") for name in names)
    assert not any(name.startswith("repo/") for name in names)
    assert not any(name.endswith(".db") for name in names)
    assert "app_main.py" in names
    assert "core.py" in names
    assert "storage.py" in names
    assert "config.py" in names
    assert "supported_formats.py" in names
    assert "ui_common.py" in names
    assert "ui_home.py" in names
    assert "ui_labels.py" in names
    assert "folder_models.py" in names
    assert "folder_organizer.py" in names
    assert "folder_service.py" in names
    assert "folder_report.py" in names
    assert "report_exports.py" in names
    assert "docs/KNOWN_LIMITATIONS.md" in names
    assert "docs/PORTFOLIO_CASE_STUDY.md" in names
    for source_only_path in SOURCE_ONLY_RELEASE_FILES:
        assert source_only_path not in names


def test_build_release_zip_wrapper_script_creates_release_zip(tmp_path: Path):
    zip_path = tmp_path / "wrapper-package.zip"

    subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "build_release_zip.py"),
            "--output-dir",
            str(tmp_path),
            "--zip-name",
            zip_path.name,
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )

    assert zip_path.exists()


def test_get_version_uses_static_parsing(monkeypatch):
    import scripts.create_release_zip as release_script

    monkeypatch.setattr(
        release_script.Path,
        "read_text",
        lambda self, encoding="utf-8": "__version__ = '9.9.9'\nraise RuntimeError('should not execute')\n",
    )

    assert get_version() == "9.9.9"


def test_verify_release_zip_expands_glob_patterns(tmp_path):
    zip_path = build_zip(tmp_path, "package.zip")

    matches = resolve_zip_paths(str(tmp_path / "*.zip"))

    assert matches == [zip_path]


def test_verify_release_zip_default_path_picks_latest_release_ci_zip(monkeypatch, tmp_path: Path):
    release_dir = tmp_path / "release_ci"
    dist_dir = tmp_path / "dist"
    release_dir.mkdir()
    dist_dir.mkdir()
    older = dist_dir / "older.zip"
    newer = release_dir / "newer.zip"
    older.write_bytes(b"old")
    newer.write_bytes(b"new")
    os.utime(older, (time.time() - 60, time.time() - 60))
    os.utime(newer, None)

    monkeypatch.setattr("scripts.verify_release_zip.PROJECT_ROOT", tmp_path)

    assert Path(default_zip_path_arg()) == newer


def test_verify_release_zip_rejects_forbidden_and_extra_entries(tmp_path: Path):
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("app.py", "print('ok')\n")
        archive.writestr("__pycache__/bad.pyc", b"cached")

    try:
        verify_release_zip(zip_path)
    except ValueError as exc:
        assert "forbidden paths" in str(exc)
    else:
        raise AssertionError("Expected forbidden zip entry to fail verification")


def test_verify_release_zip_rejects_missing_required_file(tmp_path: Path):
    zip_path = tmp_path / "missing.zip"
    required_entries = [entry for entry in RELEASE_ALLOWLIST if entry != "app_main.py"]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in required_entries:
            archive.writestr(entry, "placeholder\n")

    try:
        verify_release_zip(zip_path)
    except ValueError as exc:
        assert "missing allowlisted files" in str(exc)
        assert "app_main.py" in str(exc)
    else:
        raise AssertionError("Expected missing allowlisted file to fail verification")


def test_verify_release_zip_rejects_source_only_script(tmp_path: Path):
    zip_path = build_zip(tmp_path, "runtime-plus-source-only.zip")
    with zipfile.ZipFile(zip_path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("scripts/validate_release_source.py", "print('source only')\n")

    try:
        verify_release_zip(zip_path)
    except ValueError as exc:
        assert "source-only files" in str(exc) or "non-allowlisted files" in str(exc)
        assert "scripts/validate_release_source.py" in str(exc)
    else:
        raise AssertionError("Expected source-only script to fail verification")


def test_verify_release_zip_rejects_runtime_artifacts_in_zip(tmp_path: Path):
    zip_path = build_zip(tmp_path, "runtime-with-artifacts.zip")
    with zipfile.ZipFile(zip_path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dist/runtime.zip", b"zip-in-zip")
        archive.writestr("coverage/index.html", "<html></html>")

    try:
        verify_release_zip(zip_path)
    except ValueError as exc:
        assert "forbidden paths" in str(exc)
        assert "dist/runtime.zip" in str(exc) or "coverage/index.html" in str(exc)
    else:
        raise AssertionError("Expected runtime artifacts to fail verification")


def test_extracted_release_zip_smoke_imports_app_main(tmp_path: Path):
    output_dir = tmp_path / "release"
    extract_dir = tmp_path / "extracted"

    subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "create_release_zip.py"),
            "--output-dir",
            str(output_dir),
            "--zip-name",
            "smart-organizer-runtime-demo.zip",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )

    zip_path = output_dir / "smart-organizer-runtime-demo.zip"
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        archive.extractall(extract_dir)

    forbidden_roots = {
        ".github",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "logs",
        "node_modules",
        "previews",
        "repo",
        "release",
        "tests",
        "tmp",
        "uploads",
        "venv",
    }
    forbidden_suffixes = (".db", ".sqlite", ".sqlite3", ".pyc")
    required_files = {
        "app.py",
        "app_main.py",
        "requirements.txt",
        "RUN_RELEASE.md",
    }

    assert required_files.issubset(names)
    assert not any(Path(name).parts[0] in forbidden_roots for name in names)
    assert not any(name.endswith(forbidden_suffixes) for name in names)

    subprocess.run(
        [sys.executable, "-c", "import app_main"],
        cwd=extract_dir,
        check=True,
    )


def test_validate_release_run_step_streams_success(capsys):
    returncode = run_step(
        [sys.executable, "-c", "print('release validation alive')"],
        timeout_seconds=5,
        timeout_tail_lines=5,
    )

    captured = capsys.readouterr()
    assert returncode == 0
    assert "START" in captured.out
    assert "release validation alive" in captured.out
    assert "END" in captured.out


def test_validate_release_run_step_times_out_with_tail(capsys):
    returncode = run_step(
        [sys.executable, "-c", "import time; print('last visible line', flush=True); time.sleep(10)"],
        timeout_seconds=3,
        timeout_tail_lines=5,
    )

    captured = capsys.readouterr()
    assert returncode == 124
    assert "TIMEOUT" in captured.err
    assert "last visible line" in captured.err


def test_validate_release_run_step_times_out_with_partial_line(capsys, tmp_path: Path):
    ready_path = tmp_path / "timeout-partial.ready"
    script_path = tmp_path / "timeout-partial.py"
    _write_timeout_probe_script(
        script_path,
        ready_file=ready_path,
        stdout_text="partial stdout",
        stderr_text="partial stderr",
    )
    command = [sys.executable, str(script_path)]

    started = time.perf_counter()
    result, thread = _run_step_in_thread(command, timeout_seconds=3, timeout_tail_lines=5)
    _wait_for_path(ready_path)
    thread.join(timeout=10)
    assert not thread.is_alive()
    duration = time.perf_counter() - started

    captured = capsys.readouterr()
    assert result["returncode"] == 124
    assert duration < 8
    assert "partial stdout" in captured.out
    assert "partial stderr" in captured.err
    assert "TIMEOUT" in captured.err
    assert "[stdout] partial stdout" in captured.err
    assert "[stderr] partial stderr" in captured.err


def test_validate_release_run_step_timeout_tail_keeps_flushed_partial_stdout_and_stderr(
    capsys,
    tmp_path: Path,
):
    ready_path = tmp_path / "partial-tail.ready"
    script_path = tmp_path / "partial-tail.py"
    _write_timeout_probe_script(
        script_path,
        ready_file=ready_path,
        stdout_text="partial stdout flushed",
        stderr_text="partial stderr flushed",
    )
    result, thread = _run_step_in_thread(
        [sys.executable, str(script_path)],
        timeout_seconds=3,
        timeout_tail_lines=5,
    )
    _wait_for_path(ready_path)
    thread.join(timeout=10)
    assert not thread.is_alive()

    captured = capsys.readouterr()
    assert result["returncode"] == 124
    assert "partial stdout flushed" in captured.out
    assert "partial stderr flushed" in captured.err
    assert "[stdout] partial stdout flushed" in captured.err
    assert "[stderr] partial stderr flushed" in captured.err


def test_validate_release_run_step_timeout_with_no_output_reports_empty_tail(capsys, tmp_path: Path):
    ready_path = tmp_path / "silent.ready"
    script_path = tmp_path / "silent.py"
    _write_timeout_probe_script(script_path, ready_file=ready_path)

    result, thread = _run_step_in_thread(
        [sys.executable, str(script_path)],
        timeout_seconds=3,
        timeout_tail_lines=5,
    )
    _wait_for_path(ready_path)
    thread.join(timeout=10)
    assert not thread.is_alive()

    captured = capsys.readouterr()
    assert result["returncode"] == 124
    assert "TIMEOUT" in captured.err
    assert "No output captured before timeout." in captured.err


def test_validate_release_run_step_timeout_does_not_leave_process(capsys, tmp_path: Path):
    parent_pid_file = tmp_path / "parent.pid"
    child_pid_file = tmp_path / "child.pid"
    parent_ready_file = tmp_path / "parent.ready"
    child_ready_file = tmp_path / "child.ready"
    child_script = tmp_path / "child_sleep.py"
    child_script.write_text(
        "import os\n"
        "import pathlib\n"
        "import sys\n"
        "import time\n"
        "\n"
        "pid_path = pathlib.Path(sys.argv[1])\n"
        "ready_path = pathlib.Path(sys.argv[2])\n"
        "pid_path.write_text(str(os.getpid()), encoding='utf-8')\n"
        "ready_path.write_text('child-ready', encoding='utf-8')\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    parent_script = tmp_path / "parent_spawn.py"
    parent_script.write_text(
        "import os\n"
        "import pathlib\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "\n"
        "parent_path = pathlib.Path(sys.argv[1])\n"
        "child_path = pathlib.Path(sys.argv[2])\n"
        "child_ready = pathlib.Path(sys.argv[3])\n"
        "parent_ready = pathlib.Path(sys.argv[4])\n"
        "child_script = pathlib.Path(sys.argv[5])\n"
        "subprocess.Popen([sys.executable, str(child_script), str(child_path), str(child_ready)])\n"
        "deadline = time.monotonic() + 5\n"
        "while (not child_path.exists() or not child_ready.exists()) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "if not child_path.exists() or not child_ready.exists():\n"
        "    raise RuntimeError('child ready handshake was not completed')\n"
        "parent_path.write_text(str(os.getpid()), encoding='utf-8')\n"
        "parent_ready.write_text('parent-ready', encoding='utf-8')\n"
        "sys.stdout.write('parent partial stdout'); sys.stdout.flush()\n"
        "sys.stderr.write('parent partial stderr'); sys.stderr.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(parent_script),
        str(parent_pid_file),
        str(child_pid_file),
        str(child_ready_file),
        str(parent_ready_file),
        str(child_script),
    ]

    result, thread = _run_step_in_thread(command, timeout_seconds=4, timeout_tail_lines=5)
    _wait_for_path(parent_ready_file)
    _wait_for_path(child_ready_file)
    thread.join(timeout=12)
    assert not thread.is_alive()

    captured = capsys.readouterr()
    assert result["returncode"] == 124
    assert "TIMEOUT" in captured.err
    assert parent_pid_file.exists()
    assert child_pid_file.exists()
    assert parent_ready_file.exists()
    assert child_ready_file.exists()
    assert "parent partial stdout" in captured.out
    assert "parent partial stderr" in captured.err
    assert not _pid_exists(int(parent_pid_file.read_text(encoding="utf-8")))
    assert not _pid_exists(int(child_pid_file.read_text(encoding="utf-8")))


def test_validate_release_run_step_collects_success_stdout_and_stderr(capsys):
    returncode = run_step(
        [
            sys.executable,
            "-c",
            "import sys; print('success stdout'); print('success stderr', file=sys.stderr)",
        ],
        timeout_seconds=5,
        timeout_tail_lines=5,
    )

    captured = capsys.readouterr()
    assert returncode == 0
    assert "success stdout" in captured.out
    assert "success stderr" in captured.err
    assert "END" in captured.out


def test_validate_release_run_step_failure_message_is_clear(capsys):
    returncode = run_step(
        [sys.executable, "-c", "import sys; print('clear failure', file=sys.stderr); sys.exit(7)"],
        timeout_seconds=5,
        timeout_tail_lines=5,
    )

    captured = capsys.readouterr()
    assert returncode == 7
    assert "clear failure" in captured.err
    assert "FAILED" in captured.err
    assert "exit=7" in captured.err


def test_timeout_tail_lines_limit_keeps_latest_entries():
    tail = OutputTail(8)
    for index in range(6):
        tail.append("stdout", f"stdout-{index}\n")
        tail.append("stderr", f"stderr-{index}\n")

    lines = _tail_lines(tail.snapshot(), limit=3)

    assert lines == [
        "[stderr] stderr-4",
        "[stdout] stdout-5",
        "[stderr] stderr-5",
    ]


def test_format_timeout_message_includes_command_timeout_and_returncode():
    message = _format_timeout_message(
        StepTimeoutResult(
            command=[sys.executable, "-m", "pytest", "-q"],
            timeout_seconds=20,
            returncode=-9,
            duration=20.5,
            tail_lines=[],
        )
    )

    assert "python -m pytest -q" in message
    assert "timeout=20s" in message
    assert "returncode=-9" in message


def test_build_timeout_result_captures_limited_tail():
    tail = OutputTail(10)
    tail.append("stdout", "alpha\n")
    tail.append("stderr", "beta")

    result = _build_timeout_result(
        [sys.executable, "-m", "pytest", "-q"],
        timeout_seconds=20,
        duration=20.5,
        returncode=-9,
        tail=tail,
        tail_lines=2,
    )

    assert result.tail_lines == ["[stdout] alpha", "[stderr] beta"]
