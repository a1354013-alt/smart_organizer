from __future__ import annotations

import argparse
import os
import selectors
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import TextIO, cast

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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


def build_validation_commands(output_dir: str = "release_ci") -> list[list[str]]:
    return [
        [sys.executable, "scripts/safe_compileall.py", "-q", "."],
        [sys.executable, "-m", "ruff", "check", "--no-cache", "."],
        [sys.executable, "-m", "mypy", "--cache-dir=/dev/null"],
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "scripts/create_release_zip.py", "--output-dir", output_dir],
        [sys.executable, "scripts/verify_release_zip.py", f"{output_dir}/*.zip"],
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


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _print_timeout_tail(tail: deque[str], *, tail_lines: int) -> None:
    if not tail:
        print("No output captured before timeout.", file=sys.stderr, flush=True)
        return
    print(f"Last {min(len(tail), tail_lines)} output line(s) before timeout:", file=sys.stderr, flush=True)
    for line in tail:
        print(line.rstrip("\n"), file=sys.stderr, flush=True)


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
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    tail: deque[str] = deque(maxlen=max(1, int(timeout_tail_lines)))

    if os.name == "nt":
        # `selectors` cannot wait on Windows pipe handles. Reader threads keep
        # stdout/stderr flowing so CI logs do not look stuck.
        import queue
        import threading

        output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()

        def reader(stream_name: str, stream: TextIO) -> None:
            try:
                for line in stream:
                    output_queue.put((stream_name, line))
            finally:
                output_queue.put((stream_name, None))

        threads = [
            threading.Thread(target=reader, args=("stdout", proc.stdout), daemon=True),
            threading.Thread(target=reader, args=("stderr", proc.stderr), daemon=True),
        ]
        for thread in threads:
            thread.start()

        closed = 0
        while closed < 2:
            if time.perf_counter() - started > timeout_seconds:
                _terminate_process(proc)
                duration = time.perf_counter() - started
                print(f"<== TIMEOUT {display} after {duration:.2f}s", file=sys.stderr, flush=True)
                _print_timeout_tail(tail, tail_lines=max(1, int(timeout_tail_lines)))
                return 124
            try:
                stream_name, line = output_queue.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None and not any(thread.is_alive() for thread in threads):
                    break
                continue
            if line is None:
                closed += 1
                continue
            tail.append(f"[{stream_name}] {line}")
            target = sys.stderr if stream_name == "stderr" else sys.stdout
            print(line, end="", file=target, flush=True)
    else:
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
        selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            if time.perf_counter() - started > timeout_seconds:
                _terminate_process(proc)
                duration = time.perf_counter() - started
                print(f"<== TIMEOUT {display} after {duration:.2f}s", file=sys.stderr, flush=True)
                _print_timeout_tail(tail, tail_lines=max(1, int(timeout_tail_lines)))
                return 124
            for key, _events in selector.select(timeout=0.2):
                stream_name = str(key.data)
                stream = cast(TextIO, key.fileobj)
                line = stream.readline()
                if line:
                    tail.append(f"[{stream_name}] {line}")
                    target = sys.stderr if stream_name == "stderr" else sys.stdout
                    print(line, end="", file=target, flush=True)
                else:
                    selector.unregister(key.fileobj)

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
