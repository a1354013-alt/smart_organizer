"""
Project-local wrapper for `python -m compileall`.

Why this exists:
- The workspace may include local runtime directories that should not be compiled.
- Running `python -m compileall .` directly would recurse into folders like `.venv/` and release artifacts.
"""

from __future__ import annotations

import builtins
import importlib.util
import os
import sys
import sysconfig
from types import ModuleType
from typing import TypedDict


class CompileFlags(TypedDict):
    quiet: int
    force: bool
    legacy: bool
    recurse: bool


def _load_stdlib_compileall() -> ModuleType:
    stdlib_dir = sysconfig.get_path("stdlib")
    if not stdlib_dir:
        raise RuntimeError("stdlib path not found")
    stdlib_path = os.path.join(stdlib_dir, "compileall.py")
    spec = importlib.util.spec_from_file_location("_stdlib_compileall", stdlib_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load stdlib compileall from {stdlib_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract_existing_x(argv: list[str]) -> tuple[list[str], str | None]:
    cleaned: list[str] = []
    rx: str | None = None
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "-x" and i + 1 < len(argv):
            rx = argv[i + 1]
            i += 2
            continue
        if token.startswith("-x") and token != "-x":
            rx = token[2:]
            i += 1
            continue
        cleaned.append(token)
        i += 1
    return cleaned, rx


def _parse_flags(argv: list[str]) -> tuple[list[str], CompileFlags]:
    cleaned: list[str] = []
    quiet = 0
    force = False
    legacy = False
    recurse = True

    for token in argv:
        if token == "-q":
            quiet += 1
            continue
        if token == "-qq":
            quiet += 2
            continue
        if token == "-f":
            force = True
            continue
        if token == "-b":
            legacy = True
            continue
        if token == "-l":
            recurse = False
            continue
        cleaned.append(token)

    legacy = True if not legacy else legacy
    return cleaned, {"quiet": int(min(quiet, 2)), "force": force, "legacy": legacy, "recurse": recurse}


def _should_skip_dir(name: str) -> bool:
    lowered = name.lower()
    return lowered in {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "uploads",
        "repo",
        "release",
    } or lowered.startswith("release_ci") or lowered.startswith("_tmp_pytest") or lowered.startswith(".pytest_runtime_tmp")


def _compile_one(source_path: str, *, quiet: int) -> bool:
    try:
        with open(source_path, "rb") as handle:
            source_bytes = handle.read()
        source_text = source_bytes.decode("utf-8")
        builtins.compile(source_text, source_path, "exec", dont_inherit=True, optimize=0)
        return True
    except UnicodeDecodeError:
        with open(source_path, "r", encoding="utf-8", errors="replace") as handle:
            source_text = handle.read()
        try:
            builtins.compile(source_text, source_path, "exec", dont_inherit=True, optimize=0)
            return True
        except SyntaxError as exc:
            if quiet < 2:
                print(f"SyntaxError: {source_path}:{exc.lineno}:{exc.offset} {exc.msg}")
            return False
    except SyntaxError as exc:
        if quiet < 2:
            print(f"SyntaxError: {source_path}:{exc.lineno}:{exc.offset} {exc.msg}")
        return False
    except Exception as exc:
        if quiet < 2:
            print(f"Compile failed: {source_path} ({exc})")
        return False


def _compile_targets(std: ModuleType, targets: list[str], *, quiet: int, force: bool, legacy: bool, recurse: bool) -> bool:
    del std, force, legacy
    ok = True

    for target in targets:
        path = os.path.abspath(target)
        if os.path.isfile(path):
            if path.lower().endswith(".py"):
                ok = _compile_one(path, quiet=quiet) and ok
            continue

        if not os.path.isdir(path):
            continue

        def _onerror(err: OSError) -> None:
            nonlocal ok
            ok = False
            if quiet < 2:
                print(f"Can't list '{getattr(err, 'filename', path)}'")

        for dirpath, dirnames, filenames in os.walk(path, topdown=True, onerror=_onerror):
            dirnames[:] = [dirname for dirname in dirnames if not _should_skip_dir(dirname)]
            if not recurse:
                dirnames[:] = []

            for filename in filenames:
                if filename.lower().endswith(".py"):
                    ok = _compile_one(os.path.join(dirpath, filename), quiet=quiet) and ok

    return ok


def main() -> None:
    std = _load_stdlib_compileall()
    argv = sys.argv[1:]
    argv, _existing_rx = _extract_existing_x(argv)
    argv, flags = _parse_flags(argv)

    targets = [token for token in argv if not token.startswith("-")]
    if targets:
        ok = _compile_targets(
            std,
            targets,
            quiet=flags["quiet"],
            force=flags["force"],
            legacy=flags["legacy"],
            recurse=flags["recurse"],
        )
        raise SystemExit(0 if ok else 1)

    main_fn = getattr(std, "main", None)
    if not callable(main_fn):
        raise RuntimeError("stdlib compileall.main not found")
    ok = bool(main_fn())
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
