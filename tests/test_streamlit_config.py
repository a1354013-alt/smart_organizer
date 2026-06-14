from __future__ import annotations

import tomllib
from pathlib import Path


def test_streamlit_config_has_expected_theme_and_server_settings():
    config_path = Path(".streamlit/config.toml")

    assert config_path.exists()

    payload = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert payload["theme"]["base"] == "light"
    assert payload["theme"]["primaryColor"] == "#ff4b6e"
    assert payload["theme"]["backgroundColor"] == "#f6f9fc"
    assert payload["theme"]["secondaryBackgroundColor"] == "#ffffff"
    assert payload["theme"]["textColor"] == "#0f172a"
    assert payload["browser"]["gatherUsageStats"] is False
    assert payload["server"]["address"] == "localhost"
    assert payload["server"]["port"] == 8501
