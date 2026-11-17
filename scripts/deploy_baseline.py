#!/usr/bin/env python3
"""Find the actual SHA recorded by the last successful production deploy job."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ci_scope import GitHub, SHA

MARKER = "Record deployed commit "


def pages(api, path, key, **query):
    """Read every API page; a failed or malformed response cannot prove a baseline."""
    page = 1
    while True:
        data = api.get(path + "?" + urlencode({**query, "per_page": 100, "page": page}))
        items = data[key]
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("invalid deployment history")
        yield from items
        if len(items) < 100:
            return
        page += 1


def last_deployed_sha(api) -> str:
    """Never substitute workflow_run.head_sha or an older unproven deployment."""
    runs = pages(api, "/actions/workflows/deploy-prod.yml/runs", "workflow_runs",
                 branch="main", status="completed")
    for run in runs:
        run_id = run["id"]
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
            raise ValueError("invalid deployment run ID")
        jobs = list(pages(api, f"/actions/runs/{run_id}/jobs", "jobs"))
        deployed = [job for job in jobs if job.get("name") == "deploy"
                    and job.get("conclusion") == "success"]
        if not deployed:
            continue
        if len(deployed) != 1:
            return ""
        markers = [step for step in deployed[0].get("steps", [])
                   if step.get("name", "").startswith(MARKER)]
        if len(markers) != 1 or markers[0].get("conclusion") != "success":
            return ""
        sha = markers[0]["name"][len(MARKER):]
        return sha if SHA.fullmatch(sha) else ""
    return ""


def main() -> int:
    try:
        sha = last_deployed_sha(GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Avoid logging request URLs, credentials or response payloads.
        print("Deployment baseline unavailable; require deployment after freshness check.", file=sys.stderr)
        return 1
    print(sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
