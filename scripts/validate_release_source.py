from __future__ import annotations

import argparse
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True

from scripts.release_policy import DEFAULT_RELEASE_OUTPUT_DIR, VALIDATION_ZIP_NAME

DEFAULT_COMMAND_TIMEOUT_SECONDS = 90
LONG_COMMAND_TIMEOUT_SECONDS = 180
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
STREAM_ENCODING = "utf-8"
PROCESS_TERMINATE_GRACE_SECONDS = 1.0
PROCESS_KILL_GRACE_SECONDS = 1.0
READER_JOIN_GRACE_SECONDS = 1.0
DRAIN_AFTER_TERMINATE_GRACE_SECONDS = 0.25


class SupportsWriteFlush(Protocol):
    encoding: str | None
    buffer: Any

    def write(self, text: str) -> object: ...

    def flush(self) -> object: ...


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


@dataclass(slots=True)
class StepTimeoutResult:
    command: list[str]
    timeout_seconds: int
    duration: float
    returncode: int | None
    tail_lines: list[str]


def _tail_lines(lines: deque[str], *, limit: int) -> list[str]:
    if limit <= 0:
        return []
    return list(lines)[-limit:]


def build_validation_commands(output_dir: str = DEFAULT_RELEASE_OUTPUT_DIR) -> list[list[str]]:
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
        default=DEFAULT_RELEASE_OUTPUT_DIR,
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


def _wait_until(proc: subprocess.Popen[Any], deadline: float) -> bool:
    while proc.poll() is None:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return False
        try:
            proc.wait(timeout=min(0.1, remaining))
        except subprocess.TimeoutExpired:
            continue
    return True


def _start_process(command: list[str]) -> subprocess.Popen[Any]:
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        **_popen_kwargs(),
    )


def _kill_process_tree(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        _taskkill_process_tree(proc.pid, force=True)
        with suppress(ProcessLookupError, OSError):
            proc.kill()
        return

    killpg = getattr(os, "killpg", None)
    sigkill = getattr(signal, "SIGKILL", None)
    if killpg is not None and sigkill is not None:
        with suppress(ProcessLookupError):
            killpg(proc.pid, sigkill)
    with suppress(ProcessLookupError, OSError):
        proc.kill()


def _taskkill_process_tree(pid: int, *, force: bool) -> None:
    command = ["taskkill", "/T", "/PID", str(pid)]
    if force:
        command.insert(1, "/F")
    subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _windows_ctrl_break_event() -> int | None:
    if os.name != "nt":
        return None
    value = getattr(signal, "CTRL_BREAK_EVENT", None)
    return int(value) if isinstance(value, int) else None


def _terminate_process_tree_windows(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    ctrl_break_event = _windows_ctrl_break_event()
    if ctrl_break_event is not None:
        with suppress(OSError, ValueError):
            proc.send_signal(ctrl_break_event)
    with suppress(ProcessLookupError, OSError):
        proc.terminate()
    _taskkill_process_tree(proc.pid, force=False)


def _terminate_process(proc: subprocess.Popen[Any], *, deadline: float) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        _terminate_process_tree_windows(proc)
    else:
        killpg = getattr(os, "killpg", None)
        if killpg is not None:
            with suppress(ProcessLookupError):
                killpg(proc.pid, signal.SIGTERM)
        with suppress(ProcessLookupError, OSError):
            proc.terminate()
    terminate_deadline = min(deadline, time.perf_counter() + PROCESS_TERMINATE_GRACE_SECONDS)
    if _wait_until(proc, terminate_deadline):
        return
    _kill_process_tree(proc)
    kill_deadline = min(deadline, time.perf_counter() + PROCESS_KILL_GRACE_SECONDS)
    _wait_until(proc, kill_deadline)


def _join_reader_threads(threads: list[threading.Thread], *, deadline: float) -> None:
    for thread in threads:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return
        thread.join(timeout=min(READER_JOIN_GRACE_SECONDS, remaining))


def _drain_output_queue_once(
    output_queue: queue.Queue[tuple[str, bytes | None]],
) -> list[tuple[str, bytes | None]]:
    items: list[tuple[str, bytes | None]] = []
    while True:
        try:
            items.append(output_queue.get_nowait())
        except queue.Empty:
            return items


def _drain_until_closed(
    output_queue: queue.Queue[tuple[str, bytes | None]],
    tail: OutputTail,
    threads: list[threading.Thread],
    *,
    closed: int,
    deadline: float,
) -> int:
    while closed < 2 and time.perf_counter() < deadline:
        closed = _drain_output_queue(output_queue, tail, closed=closed)
        if closed >= 2:
            break
        if not any(thread.is_alive() for thread in threads):
            closed = _drain_output_queue(output_queue, tail, closed=closed)
            break
        try:
            stream_name, chunk = output_queue.get(timeout=min(0.05, max(0.0, deadline - time.perf_counter())))
        except queue.Empty:
            continue
        if chunk is None:
            closed += 1
            continue
        _handle_output_chunk(stream_name, chunk, tail)
    time.sleep(DRAIN_AFTER_TERMINATE_GRACE_SECONDS)
    return _drain_output_queue(output_queue, tail, closed=closed)


def _popen_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _format_timeout_tail(tail: OutputTail, *, tail_lines: int) -> list[str]:
    return _tail_lines(tail.snapshot(), limit=tail_lines)


def _build_timeout_result(
    command: list[str],
    *,
    timeout_seconds: int,
    duration: float,
    returncode: int | None,
    tail: OutputTail,
    tail_lines: int,
) -> StepTimeoutResult:
    return StepTimeoutResult(
        command=list(command),
        timeout_seconds=timeout_seconds,
        duration=duration,
        returncode=returncode,
        tail_lines=_format_timeout_tail(tail, tail_lines=tail_lines),
    )


def _print_timeout_tail(result: StepTimeoutResult) -> None:
    lines = result.tail_lines
    if not lines:
        print("No output captured before timeout.", file=sys.stderr, flush=True)
        return
    print(f"Last {len(lines)} output line(s) before timeout:", file=sys.stderr, flush=True)
    for line in lines:
        _write_text(cast(SupportsWriteFlush, sys.stderr), line + "\n")


def _write_text(target: SupportsWriteFlush, text: str) -> None:
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


def _format_timeout_message(result: StepTimeoutResult) -> str:
    display = _display_command(result.command)
    message = f"<== TIMEOUT {display} after {result.duration:.2f}s (timeout={result.timeout_seconds}s"
    if result.returncode is not None:
        message += f", returncode={result.returncode}"
    message += ")"
    return message


def _handle_output_chunk(stream_name: str, chunk: bytes, tail: OutputTail) -> None:
    text = chunk.decode(STREAM_ENCODING, errors="replace")
    tail.append(stream_name, text)
    target = cast(SupportsWriteFlush, sys.stderr if stream_name == "stderr" else sys.stdout)
    _write_text(target, text)


def run_step(command: list[str], *, timeout_seconds: int, timeout_tail_lines: int = DEFAULT_TIMEOUT_TAIL_LINES) -> int:
    display = _display_command(command)
    started = time.perf_counter()
    print(f"==> START {display}", flush=True)
    print(f"    timeout={timeout_seconds}s", flush=True)
    proc = _start_process(command)
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
            cleanup_deadline = time.perf_counter() + PROCESS_TERMINATE_GRACE_SECONDS + PROCESS_KILL_GRACE_SECONDS
            _terminate_process(proc, deadline=cleanup_deadline)
            _join_reader_threads(threads, deadline=cleanup_deadline + READER_JOIN_GRACE_SECONDS)
            closed = _drain_until_closed(
                output_queue,
                tail,
                threads,
                closed=closed,
                deadline=cleanup_deadline + READER_JOIN_GRACE_SECONDS,
            )
            for stream_name, chunk in _drain_output_queue_once(output_queue):
                if chunk is None:
                    continue
                _handle_output_chunk(stream_name, chunk, tail)
            duration = time.perf_counter() - started
            timeout_result = _build_timeout_result(
                command,
                timeout_seconds=timeout_seconds,
                duration=duration,
                returncode=proc.poll(),
                tail=tail,
                tail_lines=max(1, int(timeout_tail_lines)),
            )
            print(
                _format_timeout_message(timeout_result),
                file=sys.stderr,
                flush=True,
            )
            _print_timeout_tail(timeout_result)
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
