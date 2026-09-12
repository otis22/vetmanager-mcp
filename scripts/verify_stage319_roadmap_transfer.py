#!/usr/bin/env python3
"""Evidence check: the first archive transfer retained every moved stage body."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "a6085f2:Roadmap.md"
HEADING = re.compile(r"^## Этап ([0-9.]+[a-z]?)\.", re.MULTILINE)
SUFFIX = re.compile(r"^(#+ .*? — `(done|stop)`)( .+)$", re.MULTILINE)


def blocks(text: str) -> list[tuple[str, str]]:
    starts = list(HEADING.finditer(text))
    return [
        (match.group(1), text[match.start() : starts[index + 1].start() if index + 1 < len(starts) else len(text)])
        for index, match in enumerate(starts)
    ]


def normalise_suffixes(text: str) -> str:
    return SUFFIX.sub(lambda match: f"{match.group(1)}\n\n{match.group(3).lstrip()}", text)


def primary(number: str) -> int:
    return int(re.match(r"\d+", number).group())


def main() -> int:
    original = subprocess.run(["git", "show", BASELINE], cwd=ROOT, text=True, capture_output=True, check=True).stdout
    expected = [
        (number, normalise_suffixes(body).rstrip())
        for number, body in blocks(original)
        if primary(number) < 299
    ]
    actual = [
        (number, body.rstrip())
        for number, body in blocks(
            (ROOT / "Roadmap.md").read_text(encoding="utf-8")
            + (ROOT / "Roadmap-archive.md").read_text(encoding="utf-8")
        )
        if primary(number) < 299
    ]
    if sorted(actual) != sorted(expected):
        print("перенос не сохранил совпадение номеров и тел этапов")
        return 1
    print(f"сверены {len(expected)} перенесённых этапов: номера и тела совпадают")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
