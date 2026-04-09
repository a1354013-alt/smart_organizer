from pathlib import Path


def test_official_release_zip_does_not_include_tests_allowlist():
    """
    固定決策：正式 release 不附 tests。
    這裡做 smoke-level 自檢，避免之後不小心把 tests 又加回 allowlist。
    """
    ps1 = Path("create_release_zip.ps1").read_text(encoding="utf-8-sig")
    assert '"tests"' not in ps1
    assert '"pytest.ini"' not in ps1
    # runtime/demo 必要檔案應在 allowlist（避免不小心漏包導致 zip 無法執行）
    for required in ['"app.py"', '"core.py"', '"services.py"', '"storage.py"', '"logging_config.py"', '"version.py"', '"contracts.py"', '"README.md"', '"requirements.txt"']:
        assert required in ps1
    # 不應把開發期文件當成正式交付內容
    assert "smart_file_organizer_plan.md" not in ps1
    assert "fastapi_celery_stability_report.md" not in ps1
