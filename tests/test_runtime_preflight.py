from __future__ import annotations

import pytest

from runtime_preflight import (
    build_python_version_error,
    is_supported_python,
    require_supported_python,
)


def test_python_311_and_312_are_supported():
    assert is_supported_python((3, 11, 9))
    assert is_supported_python((3, 12, 4))


def test_python_310_and_313_are_rejected():
    assert not is_supported_python((3, 10, 14))
    assert not is_supported_python((3, 13, 0))


def test_python_version_error_contains_detected_supported_and_remediation():
    message = build_python_version_error((3, 13, 1))

    assert "3.13.1" in message
    assert ">=3.11,<3.13" in message
    assert "Install Python 3.11 or 3.12" in message


def test_require_supported_python_raises_for_unsupported_version():
    with pytest.raises(RuntimeError, match="Unsupported Python version"):
        require_supported_python((3, 10, 12))
