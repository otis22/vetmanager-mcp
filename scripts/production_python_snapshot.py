#!/usr/bin/env python3
"""Read-only forced-command target for production Python package inventory."""
import json
import re
import subprocess


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def snapshot():
    services = run("docker", "compose", "--profile", "production", "config", "--services").splitlines()
    worker_services = sorted(name for name in services if re.fullmatch(r"mcp(?:[0-9]+)?", name))
    if not worker_services:
        raise ValueError("no MCP worker services")
    workers = []
    for service in worker_services:
        container = run("docker", "compose", "--profile", "production", "ps", "-q", service)
        if not re.fullmatch(r"[0-9a-f]{12,64}", container):
            raise ValueError(f"missing or ambiguous worker: {service}")
        image_id = run("docker", "inspect", "--format", "{{.Image}}", container)
        freeze = run("docker", "exec", container, "pip", "freeze", "--all")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) or not freeze:
            raise ValueError(f"invalid worker snapshot: {service}")
        workers.append({"service": service, "image_id": image_id, "freeze": freeze + "\n"})
    return {"workers": workers}


if __name__ == "__main__":
    print(json.dumps(snapshot(), separators=(",", ":")))
