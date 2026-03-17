from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "templates"


def main() -> int:
    invalid_files: list[str] = []
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            invalid_files.append(str(path.relative_to(ROOT)))
    if invalid_files:
        print("UTF-8 check failed for:")
        for file_name in invalid_files:
            print(f" - {file_name}")
        return 1
    print("All HTML templates decode as UTF-8.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
