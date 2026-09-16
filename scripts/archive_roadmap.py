#!/usr/bin/env python3
"""Move closed Roadmap stages outside the owner's 20-number queue window.

The archive is append-only and keeps the order in which stages are closed.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from check_roadmap_structure import CLOSED_STATUSES, OPEN_STATUSES, Stage, check, parse

ARCHIVE_HEADER = """# Архив Roadmap

Закрытая история очереди. Архив append-only и не редактируется; порядок — по
времени закрытия. Позднее закрытие добавляется в хвост. Ищите запись по номеру.
Пропуски 187–188 намеренны.

"""


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


def _prepare(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, path.stat().st_mode if path.exists() else 0o644)
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _replace_pair(roadmap: Path, archive: Path, new_queue: str, new_archive: str, old_archive: str | None) -> None:
    queue_temp = _prepare(roadmap, new_queue)
    archive_temp = _prepare(archive, new_archive)
    rollback_temp = _prepare(archive, old_archive) if old_archive is not None else None
    try:
        os.replace(archive_temp, archive)
        try:
            os.replace(queue_temp, roadmap)
        except BaseException:
            if rollback_temp is None:
                archive.unlink(missing_ok=True)
            else:
                try:
                    os.replace(rollback_temp, archive)
                except OSError as rollback_error:
                    recovery_path = rollback_temp
                    rollback_temp = None
                    raise OSError(
                        f"archive rollback failed; recovery copy preserved at {recovery_path}"
                    ) from rollback_error
                else:
                    rollback_temp = None
            raise
    finally:
        queue_temp.unlink(missing_ok=True)
        archive_temp.unlink(missing_ok=True)
        if rollback_temp is not None:
            rollback_temp.unlink(missing_ok=True)


def _preflight(queue: list[tuple[Stage, str]], archive: list[tuple[Stage, str]]) -> list[str]:
    findings = check([stage for stage, _ in queue], "Roadmap.md")
    findings += check([stage for stage, _ in archive], "Roadmap-archive.md")
    locations: dict[str, list[str]] = {}
    for label, entries in (("Roadmap.md", queue), ("Roadmap-archive.md", archive)):
        for stage, _ in entries:
            locations.setdefault(stage.name, []).append(label)
            if label == "Roadmap-archive.md" and stage.status in OPEN_STATUSES:
                findings.append(f"{label}:{stage.line}: открытый этап {stage.name} в архиве")
    for name, labels in locations.items():
        if len(labels) != 1:
            findings.append(f"этап {name} встречается {len(labels)} раза ({', '.join(labels)})")
    all_stages = [stage for stage, _ in queue + archive]
    maximum = max((int(stage.number.split(".")[0]) for stage in all_stages), default=0)
    cutoff = maximum - 19
    for stage, _ in archive:
        if stage.status in CLOSED_STATUSES and int(stage.number.split(".")[0]) >= cutoff:
            findings.append(f"Roadmap-archive.md:{stage.line}: закрытый этап {stage.name} из текущего окна")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--roadmap", type=Path, default=root / "Roadmap.md")
    parser.add_argument("--archive", type=Path, default=root / "Roadmap-archive.md")
    args = parser.parse_args(argv)

    roadmap_text = args.roadmap.read_text(encoding="utf-8")
    archive_existed = args.archive.exists()
    archive_text = args.archive.read_text(encoding="utf-8") if archive_existed else ARCHIVE_HEADER
    queue_prefix, queue_blocks = blocks(roadmap_text)
    archive_prefix, archive_blocks = blocks(archive_text)
    if not queue_blocks:
        print("Roadmap has no stages", file=sys.stderr)
        return 1
    findings = _preflight(queue_blocks, archive_blocks)
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    maximum = max(int(stage.number.split(".")[0]) for stage, _ in queue_blocks + archive_blocks)
    candidates = [
        (index, stage, body)
        for index, (stage, body) in enumerate(queue_blocks)
        if stage.status in CLOSED_STATUSES and int(stage.number.split(".")[0]) <= maximum - 20
    ]
    candidate_indexes = {index for index, _, _ in candidates}
    new_queue = queue_prefix + "".join(
        body for index, (_, body) in enumerate(queue_blocks) if index not in candidate_indexes
    )
    new_archive = archive_prefix + "".join(body for _, body in archive_blocks) + "".join(
        body for _, _, body in candidates
    )
    if candidates:
        try:
            _replace_pair(
                args.roadmap,
                args.archive,
                new_queue,
                new_archive,
                archive_text if archive_existed else None,
            )
        except OSError as exc:
            print(f"archive update failed: {exc}", file=sys.stderr)
            return 1
    print(f"moved {len(candidates)} stage(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
