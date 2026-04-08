from pathlib import Path


def test_official_release_zip_does_not_include_tests_allowlist():
    """
    固定決策：正式 release 不附 tests。
    這裡做 smoke-level 自檢，避免之後不小心把 tests 又加回 allowlist。
    """
    ps1 = Path("create_release_zip.ps1").read_text(encoding="utf-8-sig")
    assert '"tests"' not in ps1
    assert '"pytest.ini"' not in ps1

