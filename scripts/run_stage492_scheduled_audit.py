#!/usr/bin/env python3
"""Audit every worker snapshot returned by the production read-only forced command."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_stage492_audit import verify


def main(snapshot: Path) -> None:
    payload = json.loads(snapshot.read_text())
    workers = payload.get("workers")
    if not isinstance(workers, list) or not workers:
        raise ValueError("missing production worker inventory")
    expected = (Path(__file__).resolve().parents[1] / "requirements/production-installed.txt").read_text()
    names, images, freezes = set(), set(), set()
    with tempfile.TemporaryDirectory() as temporary:
        for index, worker in enumerate(workers):
            if not isinstance(worker, dict) or set(worker) != {"service", "image_id", "freeze"}:
                raise ValueError("invalid worker snapshot")
            name, image, freeze = worker["service"], worker["image_id"], worker["freeze"]
            if (not isinstance(name, str) or not name.startswith("mcp") or
                    not isinstance(image, str) or not image.startswith("sha256:") or
                    not isinstance(freeze, str) or not freeze or name in names):
                raise ValueError("invalid or duplicate worker")
            names.add(name)
            images.add(image)
            freezes.add(freeze)
            if freeze != expected:
                raise ValueError("running production packages differ from stage 492 snapshot")
            frozen = Path(temporary) / f"{index}.txt"
            output = Path(temporary) / f"{index}.json"
            frozen.write_text(freeze)
            scan = subprocess.run(["pip-audit", "-r", str(frozen), "--no-deps",
                                   "--disable-pip", "--format", "json", "--output", str(output)],
                                  capture_output=True, text=True)
            if scan.returncode not in (0, 1) or not output.is_file():
                raise ValueError("scanner failed or produced no JSON")
            verify(frozen, output)
    if len(images) != 1 or len(freezes) != 1:
        raise ValueError("production workers disagree on image or packages")
    print(json.dumps({"workers_audited": sorted(names), "image_id": next(iter(images)),
                      "finding_policy": "four known cryptography IDs, expires 2026-12-22"}))


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]))
    except (IndexError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"production Python audit blocked: {exc}", file=sys.stderr)
        sys.exit(1)
