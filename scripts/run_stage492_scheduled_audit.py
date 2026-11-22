#!/usr/bin/env python3
"""Audit every worker snapshot returned by the production read-only forced command."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from check_stage492_audit import parse_freeze, verify


def main(snapshot: Path) -> None:
    payload = json.loads(snapshot.read_text())
    workers = payload.get("workers")
    if not isinstance(workers, list) or not workers:
        raise ValueError("missing production worker inventory")
    inventory = payload.get("worker_inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("missing independent worker inventory")
    inventory_ids = {}
    for item in inventory:
        if not isinstance(item, dict) or set(item) != {"service", "container_id"}:
            raise ValueError("invalid worker inventory row")
        service, container = item["service"], item["container_id"]
        if (not isinstance(service, str) or not re.fullmatch(r"mcp(?:[0-9]+)?", service) or
                not isinstance(container, str) or not re.fullmatch(r"[0-9a-f]{12,64}", container) or
                service in inventory_ids or container in inventory_ids.values()):
            raise ValueError("duplicate or invalid worker inventory row")
        inventory_ids[service] = container
    if any(not isinstance(worker, dict) or not isinstance(worker.get("service"), str)
           for worker in workers):
        raise ValueError("invalid worker snapshot")
    names_in_snapshot = [worker["service"] for worker in workers]
    if (len(names_in_snapshot) != len(inventory_ids) or
            set(names_in_snapshot) != set(inventory_ids)):
        raise ValueError("incomplete worker inventory")
    for worker in workers:
        name = worker["service"]
        if set(worker) != {"service", "container_id", "image_id", "freeze"}:
            raise ValueError("invalid worker snapshot")
        if worker["container_id"] != inventory_ids[name]:
            raise ValueError(f"container ID differs from inventory: {name}")
    expected = (Path(__file__).resolve().parents[1] / "requirements/production-installed.txt").read_text()
    names, images, freezes, errors = set(), set(), set(), []
    with tempfile.TemporaryDirectory() as temporary:
        for index, worker in enumerate(workers):
            name, image, freeze = worker["service"], worker["image_id"], worker["freeze"]
            if (not isinstance(name, str) or not re.fullmatch(r"mcp(?:[0-9]+)?", name) or
                    not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image) or
                    not isinstance(freeze, str) or not freeze or name in names):
                raise ValueError("invalid or duplicate worker")
            names.add(name)
            images.add(image)
            freezes.add(freeze)
            frozen = Path(temporary) / f"{index}.txt"
            output = Path(temporary) / f"{index}.json"
            frozen.write_text(freeze)
            try:
                parse_freeze(frozen)
            except ValueError as exc:
                errors.append(f"{name}: {exc}")
                continue
            try:
                scan = subprocess.run(["pip-audit", "-r", str(frozen), "--no-deps",
                                       "--disable-pip", "--format", "json", "--output", str(output)],
                                      capture_output=True, text=True)
            except OSError:
                errors.append(f"{name}: scanner launch failed")
                continue
            print(json.dumps({"worker": name, "scanner_exit": scan.returncode}))
            if scan.returncode not in (0, 1) or not output.is_file():
                errors.append(f"{name}: scanner failed or produced no JSON")
                continue
            try:
                verify(frozen, output)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{name}: {exc}")
            if freeze != expected:
                errors.append(f"{name}: running production packages differ from stage 492 snapshot")
    if len(images) != 1 or len(freezes) != 1:
        errors.append("production workers disagree on image or packages")
    released_image = os.environ.get("PROD_AUDIT_EXPECTED_IMAGE_ID", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", released_image):
        errors.append("released image ID is missing or malformed")
    elif images != {released_image}:
        errors.append("running production image differs from released image ID")
    if errors:
        raise ValueError("; ".join(errors))
    print(json.dumps({"workers_audited": sorted(names), "image_id": next(iter(images)),
                      "finding_policy": "four known cryptography IDs, expires 2026-12-22"}))


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]))
    except (IndexError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"production Python audit blocked: {exc}", file=sys.stderr)
        sys.exit(1)
