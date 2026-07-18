from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True

from runtime_preflight import SUPPORTED_PYTHON_RANGE, require_supported_python

CANONICAL_LOCK_OS = "Windows"
CANONICAL_LOCK_PYTHON = "3.11"
RUNTIME_INPUT = PROJECT_ROOT / "requirements.in"
DEV_INPUT = PROJECT_ROOT / "requirements-dev.in"
RUNTIME_LOCK = PROJECT_ROOT / "requirements.lock.txt"
DEV_LOCK = PROJECT_ROOT / "requirements-dev.lock.txt"
TEST_ONLY_PACKAGES = {"pytest", "pytest-cov", "ruff", "mypy", "pip-audit", "pip-tools"}


def _normalized_lock_text(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    root_posix = PROJECT_ROOT.as_posix()
    root_native = str(PROJECT_ROOT)
    normalized: list[str] = []
    for line in lines:
        if "pip-compile" in line:
            continue
        cleaned = line.rstrip().replace(root_posix + "/", "").replace(root_native + "\\", "").replace(root_native + "/", "")
        normalized.append(cleaned)
    return "\n".join(normalized).strip()


def _compile_lock(input_path: Path, output_path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "piptools",
            "compile",
            "--resolver=backtracking",
            "--strip-extras",
            "--quiet",
            "--output-file",
            str(output_path),
            str(input_path),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def _package_names(lock_path: Path) -> set[str]:
    names: set[str] = set()
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-", "--")) or "==" not in stripped:
            continue
        names.add(stripped.split("==", 1)[0].lower().replace("_", "-"))
    return names


def validate_locks(*, mode: str = "regenerate") -> None:
    require_supported_python()
    for path in (RUNTIME_INPUT, DEV_INPUT, RUNTIME_LOCK, DEV_LOCK):
        if not path.exists():
            raise FileNotFoundError(f"Missing dependency file: {path.relative_to(PROJECT_ROOT)}")

    runtime_names = _package_names(RUNTIME_LOCK)
    leaked = sorted(TEST_ONLY_PACKAGES & runtime_names)
    if leaked:
        raise RuntimeError(f"Runtime lock contains development-only dependencies: {leaked}")

    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if f'requires-python = "{SUPPORTED_PYTHON_RANGE}"' not in pyproject:
        raise RuntimeError("pyproject.toml Python range does not match runtime preflight")

    if mode == "static":
        return
    if mode != "regenerate":
        raise ValueError(f"Unsupported validation mode: {mode}")

    with tempfile.TemporaryDirectory(prefix="smart-lock-check-") as tmp:
        tmp_path = Path(tmp)
        runtime_tmp = tmp_path / "requirements.lock.txt"
        dev_tmp = tmp_path / "requirements-dev.lock.txt"
        _compile_lock(RUNTIME_INPUT, runtime_tmp)
        _compile_lock(DEV_INPUT, dev_tmp)
        if _normalized_lock_text(runtime_tmp) != _normalized_lock_text(RUNTIME_LOCK):
            raise RuntimeError("requirements.lock.txt is stale; regenerate it from requirements.in")
        if _normalized_lock_text(dev_tmp) != _normalized_lock_text(DEV_LOCK):
            raise RuntimeError("requirements-dev.lock.txt is stale; regenerate it from requirements-dev.in")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate checked-in dependency lock files.")
    parser.add_argument(
        "--mode",
        choices=("static", "regenerate"),
        default="regenerate",
        help="Validation mode: static checks only, or canonical pip-compile regeneration comparison.",
    )
    parser.add_argument(
        "--no-regenerate-check",
        action="store_true",
        help="Deprecated alias for --mode static.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "static" if args.no_regenerate_check else args.mode
    validate_locks(mode=mode)
    print(f"Dependency locks are current ({mode} mode).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
