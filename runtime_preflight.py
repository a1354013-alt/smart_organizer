from __future__ import annotations

import sys
from collections.abc import Sequence

SUPPORTED_PYTHON_RANGE = ">=3.11,<3.13"
MIN_PYTHON = (3, 11)
MAX_EXCLUDED_PYTHON = (3, 13)


def format_python_version(version_info: Sequence[int] | None = None) -> str:
    version = tuple(version_info if version_info is not None else sys.version_info)
    major = version[0] if len(version) > 0 else 0
    minor = version[1] if len(version) > 1 else 0
    micro = version[2] if len(version) > 2 else 0
    return f"{major}.{minor}.{micro}"


def is_supported_python(version_info: Sequence[int] | None = None) -> bool:
    version = tuple(version_info if version_info is not None else sys.version_info)
    return tuple(version[:2]) >= MIN_PYTHON and tuple(version[:2]) < MAX_EXCLUDED_PYTHON


def build_python_version_error(version_info: Sequence[int] | None = None) -> str:
    detected = format_python_version(version_info)
    return (
        f"Unsupported Python version detected: {detected}. "
        f"Smart Organizer supports Python {SUPPORTED_PYTHON_RANGE}. "
        "Install Python 3.11 or 3.12, then recreate the virtual environment and rerun the command."
    )


def require_supported_python(version_info: Sequence[int] | None = None) -> None:
    if not is_supported_python(version_info):
        raise RuntimeError(build_python_version_error(version_info))
