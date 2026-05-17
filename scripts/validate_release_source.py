from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    commands = build_validation_commands(str(args.output_dir))

    for command in commands:
        print(f"$ {_display_command(command)}", flush=True)
        if args.dry_run:
            continue
        timeout_seconds = _timeout_for_command(command)
        try:
            subprocess.run(command, cwd=PROJECT_ROOT, check=True, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            print(
                f"ERROR: command timed out after {timeout_seconds}s: {_display_command(command)}",
                file=sys.stderr,
                flush=True,
            )
            return 124
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
