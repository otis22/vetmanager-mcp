#!/usr/bin/env python3
"""Move closed Roadmap stages outside the owner's 20-number queue window.

The archive is append-only and keeps the order in which stages are closed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from check_roadmap_structure import CLOSED_STATUSES, Stage, parse

ARCHIVE_HEADER = """# Архив Roadmap

Закрытая история очереди. Архив append-only и не редактируется; порядок — по
времени закрытия. Позднее закрытие добавляется в хвост. Ищите запись по номеру.
Пропуски 187–188 намеренны.

"""


def stage_key(stage: Stage) -> tuple[tuple[int, ...], str]:
    return tuple(int(part) for part in stage.number.split(".")), stage.suffix


def blocks(text: str) -> tuple[str, list[tuple[Stage, str]]]:
    stages = parse(text)
    lines = text.splitlines(keepends=True)
    starts = [stage.line - 1 for stage in stages]
    prefix = "".join(lines[: starts[0]]) if starts else text
    result: list[tuple[Stage, str]] = []
    for index, stage in enumerate(stages):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        result.append((stage, "".join(lines[starts[index] : end])))
    return prefix, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--roadmap", type=Path, default=root / "Roadmap.md")
    parser.add_argument("--archive", type=Path, default=root / "Roadmap-archive.md")
    args = parser.parse_args(argv)

    roadmap_text = args.roadmap.read_text(encoding="utf-8")
    archive_text = args.archive.read_text(encoding="utf-8") if args.archive.exists() else ARCHIVE_HEADER
    queue_prefix, queue_blocks = blocks(roadmap_text)
    archive_prefix, archive_blocks = blocks(archive_text)
    if not queue_blocks:
        print("Roadmap has no stages", file=sys.stderr)
        return 1
    maximum = max(int(stage.number.split(".")[0]) for stage, _ in queue_blocks)
    candidates = [
        (stage, body)
        for stage, body in queue_blocks
        if stage.status in CLOSED_STATUSES and int(stage.number.split(".")[0]) < maximum - 20
    ]
    candidate_names = {stage.name for stage, _ in candidates}
    moved = candidates
    new_queue = queue_prefix + "".join(body for stage, body in queue_blocks if stage.name not in candidate_names)
    new_archive = archive_prefix + "".join(body for _, body in archive_blocks) + "".join(body for _, body in moved)
    if new_queue != roadmap_text:
        args.roadmap.write_text(new_queue, encoding="utf-8")
    if new_archive != archive_text:
        args.archive.write_text(new_archive, encoding="utf-8")
    print(f"moved {len(moved)} stage(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
