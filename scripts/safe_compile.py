from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.safe_compileall import main

if __name__ == "__main__":
    has_target = any(not token.startswith("-") for token in sys.argv[1:])
    if not has_target:
        sys.argv.append(str(PROJECT_ROOT))
    main()
