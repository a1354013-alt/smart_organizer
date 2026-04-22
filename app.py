"""
Streamlit entrypoint (facade).

`app.py` remains the stable entrypoint for `streamlit run app.py`, but the implementation
is moved to `app_main.py` to keep responsibilities separated and reduce maintenance risk.
"""

# Keep version wiring explicit in the entrypoint (tests enforce this contract).
from version import APP_TITLE  # noqa: F401

# Importing `app_main` executes the Streamlit UI script (module-level code),
# preserving historical behavior for the runtime/demo package.
import app_main as _app_main  # noqa: F401
