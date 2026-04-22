from pathlib import Path


def test_official_release_zip_does_not_include_tests_allowlist():
    """The official runtime/demo zip must stay on a strict allowlist."""
    ps1 = Path("create_release_zip.ps1").read_text(encoding="utf-8-sig")

    assert '"tests"' not in ps1
    assert '"pytest.ini"' not in ps1

    for required in [
        '"app.py"',
        '"app_main.py"',
        '"core.py"',
        '"core_utils.py"',
        '"core_classification.py"',
        '"core_processor.py"',
        '"services.py"',
        '"services_models.py"',
        '"services_analysis.py"',
        '"services_review.py"',
        '"services_finalize.py"',
        '"async_processor.py"',
        '"storage.py"',
        '"storage_base.py"',
        '"storage_schema.py"',
        '"storage_repository.py"',
        '"storage_recovery.py"',
        '"storage_search.py"',
        '"storage_cleanup.py"',
        '"storage_manager.py"',
        '"logging_config.py"',
        '"version.py"',
        '"contracts.py"',
        '"README.md"',
        '"RUN_RELEASE.md"',
        '"requirements.txt"',
    ]:
        assert required in ps1

    assert '"docs"' not in ps1
    assert "smart_file_organizer_plan.md" not in ps1
    assert "fastapi_celery_stability_report.md" not in ps1
