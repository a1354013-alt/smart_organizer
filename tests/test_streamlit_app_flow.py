from __future__ import annotations

import json
import os
import time
from pathlib import Path

from streamlit.testing.v1 import AppTest

import app_main
from folder_models import QUARANTINE_DIRNAME
from i18n import t


def _make_old_file(path: Path) -> None:
    path.write_text("demo cleanup candidate", encoding="utf-8")
    timestamp = time.time() - (500 * 24 * 60 * 60)
    os.utime(path, (timestamp, timestamp))


def _find_button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_streamlit_folder_quarantine_restore_report_flow(tmp_path: Path):
    app_main._bootstrap_services.clear()
    demo_dir = tmp_path / "demo_files"
    demo_dir.mkdir()
    candidate = demo_dir / "old_invoice_2022.txt"
    _make_old_file(candidate)

    app = AppTest.from_file("app.py", default_timeout=15)
    app.run()

    assert not app.exception
    assert len(app.tabs) == 5
    assert app.text_input[0].label == t("home.scan.input_label")
    assert any(checkbox.label == t("malware.enable_scan") for checkbox in app.checkbox)
    assert any(button.label == t("malware.check_status") for button in app.button)
    assert any(button.label == t("malware.update_database") for button in app.button)

    app.text_input[0].set_value(str(demo_dir))
    _find_button(app, t("home.scan.button")).click().run()

    scan = app.session_state["folder_scan_current"]
    assert scan["stats"]["scanned_files"] == 1
    assert scan["records"][0]["name"] == "old_invoice_2022.txt"
    assert scan["records"][0]["candidate_reasons"]

    _find_button(app, t("home.candidates.select_all_preview")).click().run()
    assert app.session_state["folder_selected_paths"] == [str(candidate)]

    _find_button(app, t("home.candidates.preview_button")).click().run()
    preview = app.session_state["folder_last_operation_result"]
    assert preview["summary"]["preview"] == 1
    assert candidate.exists()

    app.checkbox[0].set_value(True)
    _find_button(app, t("home.candidates.quarantine_button")).click().run()

    moved = app.session_state["folder_last_operation_result"]
    quarantine_path = Path(moved["results"][0]["new_path"])
    assert moved["summary"]["success"] == 1
    assert not candidate.exists()
    assert quarantine_path.exists()

    manifest_path = demo_dir / QUARANTINE_DIRNAME / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["items"][0]["status"] == "QUARANTINED"

    app.multiselect[0].set_value([str(quarantine_path)])
    _find_button(app, t("home.quarantine.restore_button")).click().run()

    restored = app.session_state["folder_restore_result"]
    assert restored["summary"]["success"] == 1
    assert candidate.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["items"][0]["status"] == "RESTORED"

    assert "folder_report_snapshot" in app.session_state


def test_streamlit_records_and_search_pages_load(tmp_path: Path):
    del tmp_path
    app_main._bootstrap_services.clear()
    app = AppTest.from_file("app.py", default_timeout=15)
    app.run()

    assert not app.exception
    assert any(text_input.label == t("search_records.records_filters.search") for text_input in app.text_input)
    assert any(button.label == t("search_records.maintenance_refresh") for button in app.button)
