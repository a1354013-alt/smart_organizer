from __future__ import annotations

import subprocess
import sys


def test_i18n_core_imports_without_streamlit():
    code = "import sys; import i18n_core; raise SystemExit(1 if 'streamlit' in sys.modules else 0)"
    result = subprocess.run([sys.executable, "-c", code], check=False)
    assert result.returncode == 0
