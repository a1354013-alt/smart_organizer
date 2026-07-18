from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True

from runtime_preflight import SUPPORTED_PYTHON_RANGE, require_supported_python

CANONICAL_LOCK_OS = "Windows"
CANONICAL_LOCK_PYTHON = "3.11"
CANONICAL_LOCK_NEWLINE = "crlf"
LOCK_DIFF_LINE_LIMIT = 200
RUNTIME_INPUT = PROJECT_ROOT / "requirements.in"
DEV_INPUT = PROJECT_ROOT / "requirements-dev.in"
RUNTIME_LOCK = PROJECT_ROOT / "requirements.lock.txt"
DEV_LOCK = PROJECT_ROOT / "requirements-dev.lock.txt"
RUNTIME_TEXT = PROJECT_ROOT / "requirements.txt"
DEV_TEXT = PROJECT_ROOT / "requirements-dev.txt"
TEST_ONLY_PACKAGES = {"pytest", "pytest-cov", "ruff", "mypy", "pip-audit", "pip-tools"}
COMMENT_PREFIXES = ("#",)


@dataclass(frozen=True, slots=True)
class LockSpec:
    input_path: Path
    lock_path: Path
    text_path: Path

    @property
    def input_name(self) -> str:
        return self.input_path.name

    @property
    def lock_name(self) -> str:
        return self.lock_path.name

    @property
    def text_name(self) -> str:
        return self.text_path.name


LOCK_SPECS: tuple[LockSpec, ...] = (
    LockSpec(RUNTIME_INPUT, RUNTIME_LOCK, RUNTIME_TEXT),
    LockSpec(DEV_INPUT, DEV_LOCK, DEV_TEXT),
)


def get_pip_version() -> str:
    return importlib.metadata.version("pip")


def get_piptools_version() -> str:
    return importlib.metadata.version("pip-tools")


def canonical_environment_lines() -> list[str]:
    return [
        "Canonical lock environment:",
        f"- OS: {CANONICAL_LOCK_OS}",
        f"- Python: {CANONICAL_LOCK_PYTHON}",
        f"- pip: {get_pip_version()}",
        f"- pip-tools: {get_piptools_version()}",
        "- resolver: backtracking",
        f"- newline: {CANONICAL_LOCK_NEWLINE.upper()}",
    ]


def _print_canonical_environment() -> None:
    for line in canonical_environment_lines():
        print(line)


def _is_canonical_lock_environment() -> bool:
    return platform.system() == CANONICAL_LOCK_OS and tuple(sys.version_info[:2]) == (3, 11)


def require_canonical_lock_environment(action: str) -> None:
    if _is_canonical_lock_environment():
        return
    raise RuntimeError(
        f"{action} must run in the canonical lock environment "
        f"({CANONICAL_LOCK_OS} + Python {CANONICAL_LOCK_PYTHON}); "
        f"detected {platform.system()} + Python {sys.version_info[0]}.{sys.version_info[1]}."
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_hashes(paths: tuple[Path, ...]) -> dict[Path, str]:
    return {path: _file_sha256(path) for path in paths}


def _ensure_required_files_exist() -> None:
    for path in (RUNTIME_INPUT, DEV_INPUT, RUNTIME_LOCK, DEV_LOCK, RUNTIME_TEXT, DEV_TEXT):
        if not path.exists():
            raise FileNotFoundError(f"Missing dependency file: {path.relative_to(PROJECT_ROOT)}")


def _iter_declared_requirement_lines(path: Path, seen: set[Path] | None = None) -> list[str]:
    normalized_seen = seen if seen is not None else set()
    resolved = path.resolve()
    if resolved in normalized_seen:
        return []
    normalized_seen.add(resolved)
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(COMMENT_PREFIXES):
            continue
        if stripped.startswith(("-r ", "--requirement ")):
            _, include_value = stripped.split(maxsplit=1)
            include_path = (path.parent / include_value).resolve()
            lines.extend(_iter_declared_requirement_lines(include_path, normalized_seen))
            continue
        lines.append(stripped)
    return lines


def _declared_dependency_names(path: Path) -> set[str]:
    names: set[str] = set()
    for requirement_line in _iter_declared_requirement_lines(path):
        requirement = Requirement(requirement_line)
        names.add(requirement.name.lower().replace("_", "-"))
    return names


def _lock_header_lines(path: Path) -> list[str]:
    header: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(COMMENT_PREFIXES) or not line.strip():
            header.append(line)
            if not line.strip() and header:
                break
            continue
        break
    return header


def _validate_lock_header(spec: LockSpec) -> None:
    header = _lock_header_lines(spec.lock_path)
    header_text = "\n".join(header)
    if "autogenerated by pip-compile with Python 3.11" not in header_text:
        raise RuntimeError(f"{spec.lock_name} header must record canonical Python 3.11 generation")
    if "pip-compile" not in header_text:
        raise RuntimeError(f"{spec.lock_name} header is missing pip-compile provenance")
    if f"--output-file={spec.lock_name}" not in header_text:
        raise RuntimeError(f"{spec.lock_name} header must record its output file")
    if spec.input_name not in header_text:
        raise RuntimeError(f"{spec.lock_name} header must record {spec.input_name}")


def _normalize_requirement_name(name: str) -> str:
    return name.lower().replace("_", "-")


def _iter_lock_package_requirements(lock_path: Path) -> list[Requirement]:
    requirements: list[Requirement] = []
    for raw_line in lock_path.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("    "):
            continue
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(("#", "-", "--")):
            continue
        if "==" not in stripped:
            raise RuntimeError(f"{lock_path.name} contains a non-pinned requirement line: {stripped}")
        requirement = Requirement(stripped)
        if "==" not in str(requirement.specifier):
            raise RuntimeError(f"{lock_path.name} contains a non-exact pin: {stripped}")
        requirements.append(requirement)
    return requirements


def _package_versions(lock_path: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for requirement in _iter_lock_package_requirements(lock_path):
        name = _normalize_requirement_name(requirement.name)
        if name in versions:
            raise RuntimeError(f"{lock_path.name} contains duplicate pinned package entries: {name}")
        versions[name] = str(requirement.specifier)
    return versions


def _package_names(lock_path: Path) -> set[str]:
    return set(_package_versions(lock_path))


def _validate_direct_dependencies_present(spec: LockSpec) -> None:
    declared = _declared_dependency_names(spec.input_path)
    locked = _package_names(spec.lock_path)
    missing = sorted(declared - locked)
    if missing:
        raise RuntimeError(f"{spec.lock_name} is missing direct dependencies from {spec.input_name}: {missing}")


def _validate_runtime_and_dev_relationships() -> None:
    runtime_names = _package_names(RUNTIME_LOCK)
    dev_names = _package_names(DEV_LOCK)
    leaked = sorted(TEST_ONLY_PACKAGES & runtime_names)
    if leaked:
        raise RuntimeError(f"Runtime lock contains development-only dependencies: {leaked}")
    if "pip-tools" not in dev_names:
        raise RuntimeError("requirements-dev.lock.txt must pin pip-tools for canonical lock generation")
    missing_runtime = sorted(runtime_names - dev_names)
    if missing_runtime:
        raise RuntimeError(
            "requirements-dev.lock.txt must include runtime lock dependencies; "
            f"missing {missing_runtime}"
        )


def _validate_python_range() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if f'requires-python = "{SUPPORTED_PYTHON_RANGE}"' not in pyproject:
        raise RuntimeError("pyproject.toml Python range does not match runtime preflight")


def _validate_static_lock_files() -> None:
    _ensure_required_files_exist()
    _validate_python_range()
    for spec in LOCK_SPECS:
        _validate_lock_header(spec)
        _package_versions(spec.lock_path)
        _validate_direct_dependencies_present(spec)
    _validate_runtime_and_dev_relationships()


def _copy_dependency_inputs(destination_dir: Path) -> None:
    for spec in LOCK_SPECS:
        shutil.copy2(spec.input_path, destination_dir / spec.input_name)


def _subprocess_env(temp_cache_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_TOOLS_CACHE_DIR"] = str(temp_cache_dir)
    return env


def _compile_lock(
    input_name: str,
    output_name: str,
    *,
    cwd: Path,
    upgrade: bool,
    quiet: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix="smart-pip-tools-cache-") as cache_tmp:
        cache_dir = Path(cache_tmp)
        command = [
            sys.executable,
            "-m",
            "piptools",
            "compile",
            "--resolver=backtracking",
            "--strip-extras",
            "--no-config",
            "--newline",
            CANONICAL_LOCK_NEWLINE,
            "--output-file",
            output_name,
        ]
        if quiet:
            command.append("--quiet")
        if upgrade:
            command.append("--upgrade")
        else:
            command.append("--no-upgrade")
        command.append(input_name)
        subprocess.run(
            command,
            cwd=cwd,
            check=True,
            env=_subprocess_env(cache_dir),
        )


def _normalized_lock_text(path: Path) -> str:
    normalized_lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()]
    return "\n".join(normalized_lines).strip() + "\n"


def _redact_sensitive_diff_line(line: str) -> str:
    return re.sub(r"(https?://)([^/\s:@]+):([^/@\s]+)@", r"\1***:***@", line)


def _bounded_unified_diff(committed: Path, generated: Path) -> str:
    diff_lines = list(
        difflib.unified_diff(
            _normalized_lock_text(committed).splitlines(),
            _normalized_lock_text(generated).splitlines(),
            fromfile=f"committed/{committed.name}",
            tofile=f"generated/{generated.name}",
            lineterm="",
        )
    )
    redacted = [_redact_sensitive_diff_line(line) for line in diff_lines]
    if len(redacted) <= LOCK_DIFF_LINE_LIMIT:
        return "\n".join(redacted)
    truncated = redacted[:LOCK_DIFF_LINE_LIMIT]
    truncated.append(f"... diff truncated after {LOCK_DIFF_LINE_LIMIT} lines ...")
    return "\n".join(truncated)


def _assert_committed_hashes_unchanged(before_hashes: dict[Path, str]) -> None:
    after_hashes = _snapshot_hashes(tuple(before_hashes))
    changed = [path.name for path, old_hash in before_hashes.items() if after_hashes[path] != old_hash]
    if changed:
        raise RuntimeError(f"Validation modified committed lock files unexpectedly: {changed}")


def _regenerate_temp_lock(spec: LockSpec, temp_dir: Path) -> Path:
    temp_lock = temp_dir / spec.lock_name
    shutil.copy2(spec.lock_path, temp_lock)
    _compile_lock(spec.input_name, spec.lock_name, cwd=temp_dir, upgrade=False, quiet=True)
    return temp_lock


def validate_locks(*, mode: str = "regenerate") -> None:
    require_supported_python()
    _validate_static_lock_files()
    if mode == "static":
        return
    if mode != "regenerate":
        raise ValueError(f"Unsupported validation mode: {mode}")
    require_canonical_lock_environment("Seeded lock regeneration validation")
    before_hashes = _snapshot_hashes((RUNTIME_LOCK, DEV_LOCK))
    try:
        with tempfile.TemporaryDirectory(prefix="smart-lock-check-") as tmp:
            temp_dir = Path(tmp)
            _copy_dependency_inputs(temp_dir)
            for spec in LOCK_SPECS:
                temp_lock = _regenerate_temp_lock(spec, temp_dir)
                if _normalized_lock_text(temp_lock) != _normalized_lock_text(spec.lock_path):
                    diff = _bounded_unified_diff(spec.lock_path, temp_lock)
                    raise RuntimeError(
                        f"{spec.lock_name} is inconsistent with {spec.input_name}.\n"
                        "Validation preserved existing pins and detected a genuine input/lock mismatch.\n"
                        "Mode: seeded no-upgrade regeneration.\n"
                        f"{diff}\n"
                        "Run the documented lock regeneration command after reviewing the diff."
                    )
    finally:
        _assert_committed_hashes_unchanged(before_hashes)


def rewrite_committed_locks(*, upgrade: bool) -> list[str]:
    require_supported_python()
    require_canonical_lock_environment("Committed lock regeneration")
    _ensure_required_files_exist()
    _validate_python_range()

    changed_packages: list[str] = []
    previous_versions = {spec.lock_name: _package_versions(spec.lock_path) for spec in LOCK_SPECS}
    target_root = LOCK_SPECS[0].lock_path.parent

    for spec in LOCK_SPECS:
        _compile_lock(spec.input_name, spec.lock_name, cwd=target_root, upgrade=upgrade, quiet=False)
        new_versions = _package_versions(spec.lock_path)
        old_versions = previous_versions[spec.lock_name]
        package_names = sorted(set(old_versions) | set(new_versions))
        for package_name in package_names:
            before = old_versions.get(package_name)
            after = new_versions.get(package_name)
            if before == after:
                continue
            if before is None:
                changed_packages.append(f"{spec.lock_name}: added {package_name}{after}")
            elif after is None:
                changed_packages.append(f"{spec.lock_name}: removed {package_name}{before}")
            else:
                changed_packages.append(f"{spec.lock_name}: {package_name} {before} -> {after}")

    _validate_static_lock_files()
    return changed_packages


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate checked-in dependency lock files.")
    parser.add_argument(
        "--mode",
        choices=("static", "regenerate"),
        default="regenerate",
        help="Validation mode: static checks only, or canonical seeded no-upgrade regeneration comparison.",
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
    _print_canonical_environment()
    validate_locks(mode=mode)
    if mode == "static":
        print("Dependency locks are current (static mode).")
    else:
        print("Dependency locks are current (seeded no-upgrade regeneration mode).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
