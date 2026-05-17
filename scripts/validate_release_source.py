from __future__ import annotations

import argparse
import locale
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMMAND_TIMEOUT_SECONDS = 90
LONG_COMMAND_TIMEOUT_SECONDS = 180
VALIDATION_ZIP_NAME = "smart_organizer-release-validation.zip"
COMMAND_TIMEOUTS_SECONDS = {
    "scripts/safe_compileall.py": 60,
    "ruff": 60,
    "mypy": LONG_COMMAND_TIMEOUT_SECONDS,
    "pytest": LONG_COMMAND_TIMEOUT_SECONDS,
    "scripts/create_release_zip.py": 120,
    "scripts/verify_release_zip.py": 60,
    "scripts/check_workspace_clean.py": 60,
}
DEFAULT_TIMEOUT_TAIL_LINES = 40
STREAM_ENCODING = locale.getpreferredencoding(False) or "utf-8"


class OutputTail:
    def __init__(self, max_lines: int) -> None:
        self._lines: deque[str] = deque(maxlen=max(1, int(max_lines)))
        self._partials: dict[str, str] = {"stdout": "", "stderr": ""}

    def append(self, stream_name: str, text: str) -> None:
        if not text:
            return
        current = self._partials.get(stream_name, "") + text
        parts = current.splitlines(keepends=True)
        self._partials[stream_name] = ""
        for part in parts:
            if part.endswith(("\n", "\r")):
                self._lines.append(f"[{stream_name}] {part.rstrip()}")
            else:
                self._partials[stream_name] = part

    def snapshot(self) -> deque[str]:
        lines = deque(self._lines, maxlen=self._lines.maxlen)
        for stream_name in ("stdout", "stderr"):
            partial = self._partials.get(stream_name, "")
            if partial:
                lines.append(f"[{stream_name}] {partial}")
        return lines


def build_validation_commands(output_dir: str = "release_ci") -> list[list[str]]:
    validation_zip_path = f"{output_dir}/{VALIDATION_ZIP_NAME}"
    return [
        [sys.executable, "scripts/safe_compileall.py", "-q", "."],
        [sys.executable, "-m", "ruff", "check", "--no-cache", "."],
        [sys.executable, "-m", "mypy", "--cache-dir=/dev/null"],
        [sys.executable, "-m", "pytest", "-q"],
        [
            sys.executable,
            "scripts/create_release_zip.py",
            "--output-dir",
            output_dir,
            "--zip-name",
            VALIDATION_ZIP_NAME,
        ],
        [sys.executable, "scripts/verify_release_zip.py", validation_zip_path],
        [sys.executable, "scripts/check_workspace_clean.py", "--project-root", "."],
    ]


def _display_command(command: list[str]) -> str:
    return "python " + " ".join(command[1:]) if command and command[0] == sys.executable else " ".join(command)


def _timeout_for_command(command: list[str]) -> int:
    for part in command:
        normalized = part.replace("\\", "/")
        if normalized in COMMAND_TIMEOUTS_SECONDS:
            return COMMAND_TIMEOUTS_SECONDS[normalized]
    return DEFAULT_COMMAND_TIMEOUT_SECONDS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run source repository release validation.")
    parser.add_argument(
        "--output-dir",
        default="release_ci",
        help="Release output directory used by create_release_zip.py.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the validation commands without running them.",
    )
    parser.add_argument(
        "--timeout-tail-lines",
        type=int,
        default=DEFAULT_TIMEOUT_TAIL_LINES,
        help="Number of recent output lines to print when a step times out.",
    )
    return parser.parse_args(argv)


def _terminate_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _print_timeout_tail(tail: OutputTail, *, tail_lines: int) -> None:
    lines = tail.snapshot()
    if not lines:
        print("No output captured before timeout.", file=sys.stderr, flush=True)
        return
    print(f"Last {min(len(lines), tail_lines)} output line(s) before timeout:", file=sys.stderr, flush=True)
    for line in lines:
        _write_text(sys.stderr, line + "\n")


def _write_text(target: Any, text: str) -> None:
    try:
        target.write(text)
        target.flush()
    except UnicodeEncodeError:
        encoding = getattr(target, "encoding", None) or STREAM_ENCODING
        buffer = getattr(target, "buffer", None)
        if buffer is None:
            target.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))
            target.flush()
            return
        buffer.write(text.encode(encoding, errors="replace"))
        buffer.flush()


def _reader_thread(stream_name: str, stream: Any, output_queue: queue.Queue[tuple[str, bytes | None]]) -> None:
    fd = stream.fileno()
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            output_queue.put((stream_name, chunk))
    except OSError:
        # The process may close a pipe while we are timing out and terminating it.
        # The sentinel below still lets the runner finish deterministically.
        pass
    finally:
        output_queue.put((stream_name, None))


def _drain_output_queue(
    output_queue: queue.Queue[tuple[str, bytes | None]],
    tail: OutputTail,
    *,
    closed: int,
) -> int:
    while True:
        try:
            stream_name, chunk = output_queue.get_nowait()
        except queue.Empty:
            return closed
        if chunk is None:
            closed += 1
            continue
        _handle_output_chunk(stream_name, chunk, tail)


def _handle_output_chunk(stream_name: str, chunk: bytes, tail: OutputTail) -> None:
    text = chunk.decode(STREAM_ENCODING, errors="replace")
    tail.append(stream_name, text)
    target = sys.stderr if stream_name == "stderr" else sys.stdout
    _write_text(target, text)


def run_step(command: list[str], *, timeout_seconds: int, timeout_tail_lines: int = DEFAULT_TIMEOUT_TAIL_LINES) -> int:
    display = _display_command(command)
    started = time.perf_counter()
    print(f"==> START {display}", flush=True)
    print(f"    timeout={timeout_seconds}s", flush=True)
    proc = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    tail = OutputTail(max(1, int(timeout_tail_lines)))
    output_queue: queue.Queue[tuple[str, bytes | None]] = queue.Queue()
    threads = [
        threading.Thread(target=_reader_thread, args=("stdout", proc.stdout, output_queue), daemon=True),
        threading.Thread(target=_reader_thread, args=("stderr", proc.stderr, output_queue), daemon=True),
    ]
    for thread in threads:
        thread.start()

    closed = 0
    deadline = started + max(0.1, float(timeout_seconds))
    while closed < 2:
        now = time.perf_counter()
        if now >= deadline:
            closed = _drain_output_queue(output_queue, tail, closed=closed)
            _terminate_process(proc)
            for thread in threads:
                thread.join(timeout=1)
            closed = _drain_output_queue(output_queue, tail, closed=closed)
            duration = time.perf_counter() - started
            print(f"<== TIMEOUT {display} after {duration:.2f}s", file=sys.stderr, flush=True)
            _print_timeout_tail(tail, tail_lines=max(1, int(timeout_tail_lines)))
            return 124
        try:
            stream_name, chunk = output_queue.get(timeout=min(0.05, max(0.0, deadline - now)))
        except queue.Empty:
            if proc.poll() is not None and not any(thread.is_alive() for thread in threads):
                closed = _drain_output_queue(output_queue, tail, closed=closed)
                break
            continue
        if chunk is None:
            closed += 1
            continue
        _handle_output_chunk(stream_name, chunk, tail)

    returncode = int(proc.wait())
    duration = time.perf_counter() - started
    if returncode == 0:
        print(f"<== END {display} ({duration:.2f}s)", flush=True)
    else:
        print(f"<== FAILED {display} exit={returncode} ({duration:.2f}s)", file=sys.stderr, flush=True)
    return returncode


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    commands = build_validation_commands(str(args.output_dir))

    for command in commands:
        print(f"$ {_display_command(command)}", flush=True)
        if args.dry_run:
            continue
        timeout_seconds = _timeout_for_command(command)
        returncode = run_step(command, timeout_seconds=timeout_seconds, timeout_tail_lines=args.timeout_tail_lines)
        if returncode != 0:
            return returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
