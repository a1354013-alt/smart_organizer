from __future__ import annotations

from ui_records import build_records_maintenance_actions


def test_records_maintenance_actions_visible_without_rows():
    actions = build_records_maintenance_actions([])
    labels = {str(action["label"]) for action in actions}

    assert "Refresh file locations" in labels
    assert "Rebuild FTS rows" in labels
    assert "Reclassify selected record" in labels
    reclassify = next(action for action in actions if action["label"] == "Reclassify selected record")
    assert reclassify["enabled"] is False
