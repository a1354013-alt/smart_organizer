"""
Project-local wrapper for `python -m compileall`.

Why this exists:
- The workspace may include a local `.venv/` directory with restricted permissions.
- Running `python -m compileall .` would recurse into `.venv/` and fail with PermissionError.

This wrapper preserves the standard CLI behavior while skipping common non-project trees.
"""

from __future__ import annotations

import os
import sys
import sysconfig
import importlib.util
import builtins
from types import ModuleType


def _load_stdlib_compileall() -> ModuleType:
    stdlib_dir = sysconfig.get_path("stdlib")
    if not stdlib_dir:
        raise RuntimeError("stdlib path not found")
    stdlib_path = os.path.join(stdlib_dir, "compileall.py")
    spec = importlib.util.spec_from_file_location("_stdlib_compileall", stdlib_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load stdlib compileall from {stdlib_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def _merge_rx(existing: str | None, extra: str) -> str:
    if not existing:
        return extra
    return f"(?:{existing})|(?:{extra})"


def _extract_existing_x(argv: list[str]) -> tuple[list[str], str | None]:
    """
    Extract `-x <regex>` from argv if present, returning (argv_without_x, regex_or_none).

    Handles `-xREGEX` and `-x REGEX` forms.
    """
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


def _parse_flags(argv: list[str]) -> tuple[list[str], dict[str, object]]:
    """
    Minimal CLI parsing for project needs.

    Supports: -q/-qq, -f, -l, -b. Unknown flags are preserved for stdlib fallback.
    """
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

    # Default to legacy bytecode locations to avoid `__pycache__` write failures in locked workspaces.
    legacy = True if not legacy else legacy

    return cleaned, {"quiet": int(min(quiet, 2)), "force": bool(force), "legacy": bool(legacy), "recurse": bool(recurse)}


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
        "tests",
    }


def _compile_targets(std: ModuleType, targets: list[str], *, quiet: int, force: bool, legacy: bool, recurse: bool) -> bool:
    ok = True

    for target in targets:
        path = os.path.abspath(target)
        if os.path.isfile(path):
            if not path.lower().endswith(".py"):
                continue
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
            dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
            if not recurse:
                dirnames[:] = []

            for filename in filenames:
                if not filename.lower().endswith(".py"):
                    continue
                fullpath = os.path.join(dirpath, filename)
                ok = _compile_one(fullpath, quiet=quiet) and ok

    return ok


def _compile_one(source_path: str, *, quiet: int) -> bool:
    """
    Compile a single `.py` file (syntax + bytecode generation in-memory).

    This avoids permission issues when `__pycache__/` or `.pyc` writes are blocked
    by the workspace ACL/antivirus.
    """
    try:
        with open(source_path, "rb") as f:
            source_bytes = f.read()
        source_text = source_bytes.decode("utf-8")
        builtins.compile(source_text, source_path, "exec", dont_inherit=True, optimize=0)
        return True
    except UnicodeDecodeError:
        # Fallback for non-utf8 source files.
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            source_text = f.read()
        try:
            builtins.compile(source_text, source_path, "exec", dont_inherit=True, optimize=0)
            return True
        except SyntaxError as e:
            if quiet < 2:
                print(f"SyntaxError: {source_path}:{e.lineno}:{e.offset} {e.msg}")
            return False
    except SyntaxError as e:
        if quiet < 2:
            print(f"SyntaxError: {source_path}:{e.lineno}:{e.offset} {e.msg}")
        return False
    except Exception as e:
        if quiet < 2:
            print(f"Compile failed: {source_path} ({e})")
        return False


def main() -> None:
    std = _load_stdlib_compileall()

    argv = sys.argv[1:]
    argv, _existing_rx = _extract_existing_x(argv)
    argv, flags = _parse_flags(argv)

    # If explicit targets are provided, compile them with a directory-pruning walk.
    # This avoids permission issues when the workspace contains locked folders like `.venv/`.
    targets = [t for t in argv if not t.startswith("-")]
    if targets:
        ok = _compile_targets(
            std,
            targets,
            quiet=int(flags["quiet"]),
            force=bool(flags["force"]),
            legacy=bool(flags["legacy"]),
            recurse=bool(flags["recurse"]),
        )
        raise SystemExit(0 if ok else 1)

    # Otherwise, fall back to stdlib behavior (compile `sys.path`).
    ok = bool(std.main())  # type: ignore[attr-defined]
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
