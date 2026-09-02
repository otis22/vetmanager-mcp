#!/usr/bin/env python3
"""Structural gate for Roadmap.md — the file that claims to be the work queue.

Roadmap.md is 5000+ lines and ~290 stage headings. Anything that is not visible
at a glance stops being visible at all: on 2026-09-02 a review found two `todo`
items sitting inside `done` stages, an item filed under a foreign stage number,
and an open stage with no items at all. None of them were hidden — they were
just past the point where attention runs out.

The gate answers five questions about the file's shape, and nothing about the
quality of its text:

1. every stage heading carries a status from the closed vocabulary;
2. every item carries a status from the same vocabulary;
3. an item numbered N.M lives under stage N;
4. a closed stage (`done` / `stop`) holds no unfinished items;
5. an open stage (`todo` / `in_progress`) holds at least one item.

Usage:
    scripts/check_roadmap_structure.py [path/to/Roadmap.md]

Exit codes:
    0 — the file is well-formed
    1 — findings, printed one per line as `Roadmap.md:LINE: message`
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# `supervisor_pending` is a real state, not a typo: the work is written down,
# nobody is doing it, and it waits on a decision from the owner. It counts as
# open — that is the whole point of naming it.
OPEN_STATUSES = ("todo", "in_progress", "supervisor_pending")
CLOSED_STATUSES = ("done", "stop")
STATUSES = OPEN_STATUSES + CLOSED_STATUSES

# Stage and item numbers are dotted: stages run `234`, `103a` and `2.5`, items
# under them run `234.1` and `2.5.1.1`. An item belongs to a stage when the
# stage number is a prefix of it — matched on the dot, so `2.51.1` is not a
# child of stage `2.5`.
_STAGE_HEADING = re.compile(r"^## Этап (\d+(?:\.\d+)*)([a-z]?)[.:\s]")
_ITEM = re.compile(r"^- (\d+(?:\.\d+)+)\s")
_NESTED_BULLET = re.compile(r"^\s*[-*]\s")
_BACKTICKED = re.compile(r"`([^`]+)`")


def _status_of(text: str) -> str | None:
    """The last vocabulary word in backticks, or None.

    Items name tools and commits in backticks too, so the token has to be
    matched against the vocabulary rather than simply taken as the last one.
    """
    found = [token for token in _BACKTICKED.findall(text) if token in STATUSES]
    return found[-1] if found else None


@dataclass
class Item:
    number: str
    line: int
    status: str | None


@dataclass
class Stage:
    number: str
    suffix: str
    line: int
    status: str | None
    items: list[Item] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.number}{self.suffix}"

    def owns(self, item: Item) -> bool:
        return item.number.startswith(f"{self.number}.")


def parse(text: str) -> list[Stage]:
    """Read the file into stages and their items.

    An item may wrap over several lines; its status is looked for in the item's
    own paragraph only. Prose that follows a blank line is commentary, and a
    nested bullet is a thing of its own — neither may donate a status word to
    the item above it.
    """
    lines = text.split("\n")
    stages: list[Stage] = []
    current: Stage | None = None
    pending: list[str] | None = None
    pending_item: Item | None = None

    def close_item() -> None:
        nonlocal pending, pending_item
        if pending_item is not None:
            pending_item.status = _status_of(" ".join(pending or []))
        pending, pending_item = None, None

    for lineno, line in enumerate(lines, start=1):
        heading = _STAGE_HEADING.match(line)
        if heading:
            close_item()
            current = Stage(
                number=heading.group(1),
                suffix=heading.group(2),
                line=lineno,
                status=_status_of(line),
            )
            stages.append(current)
            continue

        item = _ITEM.match(line)
        if item and current is not None:
            close_item()
            pending_item = Item(number=item.group(1), line=lineno, status=None)
            pending = [line]
            current.items.append(pending_item)
            continue

        if pending_item is not None:
            if not line.strip() or not line.startswith("  "):
                close_item()
            elif _NESTED_BULLET.match(line):
                # A nested bullet is a thing of its own: it neither ends the
                # item nor lends it a status. Items 105.2 and 106.5 put their
                # own status on a line *after* such a list.
                continue
            else:
                pending.append(line)

    close_item()
    return stages


def check(stages: list[Stage], path_label: str) -> list[str]:
    vocabulary = " | ".join(f"`{status}`" for status in STATUSES)
    findings: list[str] = []

    for stage in stages:
        if stage.status is None:
            findings.append(
                f"{path_label}:{stage.line}: этап {stage.name} без статуса —"
                f" заголовок должен нести один из {vocabulary}"
            )

        if stage.status in OPEN_STATUSES and not stage.items:
            findings.append(
                f"{path_label}:{stage.line}: этап {stage.name} открыт"
                f" (`{stage.status}`), но не содержит ни одного пункта —"
                " такой этап ничего не сообщает о себе очереди"
            )

        for item in stage.items:
            if not stage.owns(item):
                findings.append(
                    f"{path_label}:{item.line}: пункт {item.number} стоит под"
                    f" этапом {stage.name} — номер пункта должен совпадать с"
                    " номером своего этапа"
                )
            if item.status is None:
                findings.append(
                    f"{path_label}:{item.line}: пункт {item.number} без статуса —"
                    f" пункт должен нести один из {vocabulary}"
                )
            elif stage.status in CLOSED_STATUSES and item.status in OPEN_STATUSES:
                findings.append(
                    f"{path_label}:{item.line}: пункт {item.number} остался"
                    f" `{item.status}` внутри этапа со статусом"
                    f" `{stage.status}` — незакрытая работа под закрытым"
                    " заголовком не видна в очереди"
                )

    return findings


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1] / "Roadmap.md"
    findings = check(parse(path.read_text(encoding="utf-8")), path.name)
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} нарушений структуры в {path.name}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
