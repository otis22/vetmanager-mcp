#!/usr/bin/env python3
"""Print one exact stage heading from the Roadmap queue plus archive."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    if len(argv) not in {2, 4}:
        print("usage: find_roadmap_stage.py STAGE [Roadmap.md Roadmap-archive.md]", file=sys.stderr)
        return 2
    stage = argv[1]
    paths = [Path(value) for value in argv[2:]] or [root / "Roadmap.md", root / "Roadmap-archive.md"]
    pattern = re.compile(rf"^## Этап {re.escape(stage)}(?=[.:\s])")
    matches = [
        line
        for path in paths
        for line in path.read_text(encoding="utf-8").splitlines()
        if pattern.match(line)
    ]
    if len(matches) != 1:
        print(f"этап {stage}: найдено {len(matches)} заголовков, требуется ровно 1", file=sys.stderr)
        return 1
    print(matches[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
