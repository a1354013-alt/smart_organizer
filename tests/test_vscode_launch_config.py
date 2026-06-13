from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_vscode_launch_config_supports_streamlit_f5():
    launch = _read_json(PROJECT_ROOT / ".vscode" / "launch.json")

    assert launch["version"] == "0.2.0"
    configurations = launch["configurations"]
    assert isinstance(configurations, list) and configurations
    config = configurations[0]
    assert config["name"] == "Smart Organizer: Streamlit App"
    assert config["module"] == "streamlit"
    assert config["args"][:2] == ["run", "app.py"]
    assert "--server.port" in config["args"]


def test_vscode_tasks_cover_validation_and_release_workflow():
    tasks = _read_json(PROJECT_ROOT / ".vscode" / "tasks.json")

    assert tasks["version"] == "2.0.0"
    labels = {task["label"]: task["command"] for task in tasks["tasks"]}
    assert "Smart Organizer: Run tests" in labels
    assert labels["Smart Organizer: Run tests"] == "python -m pytest -q"
    assert "Smart Organizer: Validate source repository" in labels
    assert "validate_release_source.py --timeout-tail-lines 20" in labels["Smart Organizer: Validate source repository"]
    assert "Smart Organizer: Build release zip" in labels
    assert "Smart Organizer: Verify release zip" in labels


def test_vscode_extensions_and_gitignore_allow_tracked_workspace_files():
    extensions = _read_json(PROJECT_ROOT / ".vscode" / "extensions.json")
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert extensions["recommendations"] == [
        "ms-python.python",
        "ms-python.debugpy",
        "charliermarsh.ruff",
    ]
    assert ".vscode/*" in gitignore
    assert "!.vscode/launch.json" in gitignore
    assert "!.vscode/tasks.json" in gitignore
    assert "!.vscode/extensions.json" in gitignore
