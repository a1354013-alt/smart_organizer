from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True

from scripts.validate_dependency_locks import canonical_environment_lines, rewrite_committed_locks


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regenerate committed dependency lock files.")
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Allow compatible dependency upgrades while regenerating the committed lock files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    for line in canonical_environment_lines():
        print(line)
    if args.upgrade:
        print("Mode: explicit upgrade")
    else:
        print("Mode: committed-pin refresh (no upgrade)")
    changed_packages = rewrite_committed_locks(upgrade=args.upgrade)
    if changed_packages:
        print("Changed packages:")
        for entry in changed_packages:
            print(f"- {entry}")
    else:
        print("Changed packages: none")
    print("Reminder: run the full source validation workflow and the four CI matrix jobs before releasing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
