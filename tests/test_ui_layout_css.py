from __future__ import annotations

from ui_common import inject_global_css


def test_inject_global_css_contains_fixed_height_dashboard_rules(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "ui_common.st.markdown",
        lambda value, unsafe_allow_html=False: captured.update(
            {"value": value, "unsafe_allow_html": unsafe_allow_html}
        ),
    )

    inject_global_css()

    css = str(captured["value"])
    assert captured["unsafe_allow_html"] is True
    assert "100vh" in css
    assert css.count("</style>") == 1
    assert ".block-container" in css
    assert 'section[data-testid="stSidebar"] > div:first-child' in css
    assert "@media (max-width: 900px)" in css
