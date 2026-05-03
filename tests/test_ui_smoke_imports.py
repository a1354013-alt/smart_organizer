from __future__ import annotations

import importlib


UI_MODULES = {
    "ui_home": ["render_home", "render_sidebar"],
    "ui_upload": ["render_upload"],
    "ui_review": ["render_review"],
    "ui_execute": ["render_execute"],
    "ui_search": ["render_search"],
    "ui_records": ["render_records"],
}


def test_app_main_importable():
    module = importlib.import_module("app_main")
    assert module is not None


def test_ui_modules_importable_and_render_functions_exist():
    for module_name, functions in UI_MODULES.items():
        module = importlib.import_module(module_name)
        for function_name in functions:
            assert hasattr(module, function_name), f"{module_name}.{function_name} missing"
