#!/usr/bin/env python3
"""Baseline/super-review resolution tracker (stage 104.5).

Scans `artifacts/review/*.md` and reports which review artifacts still carry
active "Do not merge" verdicts without a Resolution section. Optionally
appends a Resolution stub when given --auto-stub.

Also parses commit log for `@resolves review:path[#finding-id]` trailers and
emits a Markdown table mapping resolved findings → stage commits.

Usage:
  ./scripts/update_review_status.py                 # scan + report
  ./scripts/update_review_status.py --auto-stub     # append Resolution skeleton
  ./scripts/update_review_status.py --yaml          # findings in workflow-check YAML

Exit codes:
  0 — all reviews either resolved or marked superseded
  1 — at least one review artifact has active "Do not merge" without resolution
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from datetime import date as _date

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_DIR = REPO_ROOT / "artifacts" / "review"

# Regex patterns
DO_NOT_MERGE = re.compile(r"\*\*[Dd]o not merge\*\*", re.IGNORECASE)
RESOLUTION_HEADER = re.compile(r"^##\s+Resolution\b", re.MULTILINE)
# Require explicit superseded/resolved header or italic block (not word in prose).
SUPERSEDED_MARKER = re.compile(
    r"^##\s+(Superseded|Resolved)|_Verdict superseded|Verdict superseded",
    re.MULTILINE | re.IGNORECASE,
)
RESOLVES_TRAILER = re.compile(
    r"@resolves\s+review:(\S+?)(?:#([A-Za-z0-9_-]+))?(?:\s|$)", re.MULTILINE
)


def scan_review_files() -> list[dict]:
    """Return list of dicts {path, has_do_not_merge, has_resolution, status}."""
    if not REVIEW_DIR.exists():
        return []
    results = []
    for md in sorted(REVIEW_DIR.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        has_dnm = bool(DO_NOT_MERGE.search(text))
        has_res = bool(RESOLUTION_HEADER.search(text) or SUPERSEDED_MARKER.search(text))
        if has_dnm and not has_res:
            status = "open"
        elif has_dnm and has_res:
            status = "resolved"
        else:
            status = "informational"
        results.append({
            "path": md,
            "has_do_not_merge": has_dnm,
            "has_resolution": has_res,
            "status": status,
        })
    return results


def git_log_resolves() -> dict[str, list[tuple[str, str]]]:
    """Parse commit log for @resolves review:path[#id] trailers.

    Returns {review_path: [(commit_sha_short, finding_id_or_empty)]}.
    """
    try:
        out = subprocess.check_output(
            ["git", "log", "--pretty=format:%H%n%B%n@@COMMIT_END@@", "--all"],
            cwd=REPO_ROOT, text=True, errors="replace",
        )
    except subprocess.CalledProcessError:
        return {}
    resolves: dict[str, list[tuple[str, str]]] = {}
    current_sha = None
    for block in out.split("@@COMMIT_END@@"):
        lines = block.strip().splitlines()
        if not lines:
            continue
        sha = lines[0][:8] if lines[0] else None
        body = "\n".join(lines[1:])
        for m in RESOLVES_TRAILER.finditer(body):
            path = m.group(1)
            finding = m.group(2) or ""
            resolves.setdefault(path, []).append((sha or "?", finding))
    return resolves


def emit_yaml(findings: list[dict]) -> int:
    exit_code = 0
    for f in findings:
        if f["status"] != "open":
            continue
        rel = f["path"].relative_to(REPO_ROOT)
        print(f"- severity: medium")
        print(f"  reviewer: review-status-tracker")
        print(f"  category: unresolved_review")
        print(f"  file: {rel}")
        print(f'  lines: "N/A"')
        print(
            '  problem: "Review artifact has active \\"Do not merge\\" verdict '
            'without Resolution section"'
        )
        print(
            '  why_it_matters: "Blocker-level verdict on merged code misleads '
            'future readers; tooling parses stale status"'
        )
        print(
            '  suggested_fix: "Add ## Resolution section (see scripts/update_review_status.py --auto-stub); '
            'mark header as superseded"'
        )
        print(f"  confidence: 0.85")
        print(f"  codex_verdict: null")
        exit_code = 1
    return exit_code


def emit_human(findings: list[dict], resolves_map: dict[str, list[tuple[str, str]]]) -> int:
    if not findings:
        print("No review artifacts in artifacts/review/.", file=sys.stderr)
        return 0
    open_count = 0
    for f in findings:
        rel = f["path"].relative_to(REPO_ROOT)
        status = f["status"]
        emoji = {"open": "❌", "resolved": "✅", "informational": "ℹ️ "}.get(status, "?")
        print(f"{emoji} {status:15} {rel}")
        if status == "open":
            open_count += 1
        # Show resolves
        for key in (str(rel), rel.name):
            if key in resolves_map:
                for sha, fid in resolves_map[key]:
                    suffix = f"#{fid}" if fid else ""
                    print(f"     ← resolved by {sha}{suffix}")
                break
    print()
    print(f"Summary: {open_count} open / {len(findings)} total", file=sys.stderr)
    return 1 if open_count else 0


AUTO_STUB_TEMPLATE = """\

---

## Resolution ({today})

_Auto-stub generated by `scripts/update_review_status.py --auto-stub`. Review verdict
above superseded — findings closed in stages listed below. Fill in per-finding rows
manually from AssumptionLog + Roadmap X-b stages._

| Finding ID | Stage | Commit | Status |
|------------|-------|--------|--------|
| (fill in) | | | |

Original **Do not merge** verdict is kept for historical reference but is no longer
active. For the current state of the codebase, consult `Roadmap.md` and the latest
super-review in this directory.
"""


def auto_stub(findings: list[dict]) -> int:
    touched = 0
    for f in findings:
        if f["status"] != "open":
            continue
        md = f["path"]
        text = md.read_text(encoding="utf-8")
        if RESOLUTION_HEADER.search(text):
            continue
        stub = AUTO_STUB_TEMPLATE.format(today=_date.today().isoformat())
        md.write_text(text + stub, encoding="utf-8")
        touched += 1
        print(f"Appended Resolution stub to {md.relative_to(REPO_ROOT)}", file=sys.stderr)
    print(f"Touched {touched} file(s).", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yaml", action="store_true", help="Emit YAML findings")
    parser.add_argument("--auto-stub", action="store_true", help="Append Resolution stub to unresolved reviews")
    args = parser.parse_args()

    findings = scan_review_files()
    resolves_map = git_log_resolves()

    if args.auto_stub:
        return auto_stub(findings)
    if args.yaml:
        return emit_yaml(findings)
    return emit_human(findings, resolves_map)


if __name__ == "__main__":
    sys.exit(main())
