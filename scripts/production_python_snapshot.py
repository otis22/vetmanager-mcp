#!/usr/bin/env python3
"""Read-only forced-command target for production Python package inventory."""
import json
import re
import subprocess


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def snapshot():
    def workers(*args):
        raw = run("docker", "compose", "--profile", "production", "ps", *args,
                  "--format", "json")
        try:
            rows = json.loads(raw) if raw.startswith("[") else [
                json.loads(line) for line in raw.splitlines()]
        except json.JSONDecodeError as exc:
            raise ValueError("invalid Compose worker inventory") from exc
        found = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("Service"), str):
                raise ValueError("invalid Compose worker row")
            service = row["Service"]
            if not re.fullmatch(r"mcp(?:[0-9]+)?", service):
                continue
            container = row.get("ID")
            if (service in found or not isinstance(container, str) or
                    not re.fullmatch(r"[0-9a-f]{12,64}", container) or
                    container in found.values()):
                raise ValueError(f"duplicate or invalid MCP worker: {service}")
            if "status=running" in args and row.get("State") != "running":
                raise ValueError(f"non-running worker in running inventory: {service}")
            found[service] = container
        return found

    all_workers = workers("--all")
    running_workers = workers("--filter", "status=running")
    if not all_workers or running_workers != all_workers:
        raise ValueError(f"missing or unexpected running MCP worker: "
                         f"{sorted(set(all_workers) ^ set(running_workers))}")
    snapshots = []
    for service, container in sorted(running_workers.items()):
        image_id = run("docker", "inspect", "--format", "{{.Image}}", container)
        freeze = run("docker", "exec", container, "pip", "freeze", "--all")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) or not freeze:
            raise ValueError(f"invalid worker snapshot: {service}")
        snapshots.append({"service": service, "container_id": container,
                          "image_id": image_id, "freeze": freeze + "\n"})
    return {"worker_inventory": [
        {"service": service, "container_id": container}
        for service, container in sorted(running_workers.items())],
        "workers": snapshots}


if __name__ == "__main__":
    print(json.dumps(snapshot(), separators=(",", ":")))
