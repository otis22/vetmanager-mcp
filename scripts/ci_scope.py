#!/usr/bin/env python3
"""Fail-closed GitHub Actions decision for documentation and exact-tree reuse."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import zipfile

SHA = re.compile(r"[0-9a-f]{40}\Z")
DOC_FILES = {"README.md", "Roadmap.md", "Roadmap-archive.md", "AssumptionLog.md",
             "AGENTS.md", "AGENT_ONBOARDING.md", "CLAUDE.md"}


def docs_only(raw: bytes) -> bool:
    parts = raw.split(b"\0")
    if not raw or parts[-1] or (len(parts) - 1) % 2:
        return False
    for status, encoded in zip(parts[0:-1:2], parts[1:-1:2]):
        try:
            path = encoded.decode("utf-8")
        except UnicodeDecodeError:
            return False
        if (status not in (b"A", b"M") or not path or "\\" in path
                or Path(path).as_posix() != path or ".." in Path(path).parts):
            return False
        if path in DOC_FILES:
            continue
        pieces = Path(path).parts
        if len(pieces) < 2 or pieces[0] not in ("PRD", "docs") or not path.endswith(".md"):
            return False
    return True


def should_run_product(event: str, is_docs: bool, previous_success: bool,
                       reusable: bool) -> bool:
    if event == "pull_request":
        return not is_docs
    if event == "push":
        return not ((is_docs and previous_success) or reusable)
    return True


def valid_reuse(tree: str, artifact: dict, run: dict, tested_commit: dict,
                producer_blob: str, *, repo_id: int, workflow_id: int,
                expected_blob: str, tested_sha: str) -> bool:
    return (
        bool(SHA.fullmatch(tree)) and bool(SHA.fullmatch(tested_sha))
        and artifact.get("name") == f"validated-tree-{tree}"
        and artifact.get("expired") is False
        and artifact.get("workflow_run", {}).get("id") == run.get("id")
        and artifact.get("workflow_run", {}).get("repository_id") == repo_id
        and run.get("repository", {}).get("id") == repo_id
        and run.get("head_repository", {}).get("id") == repo_id
        and run.get("workflow_id") == workflow_id
        and run.get("path") == ".github/workflows/test.yml"
        and run.get("event") == "pull_request"
        and run.get("status") == "completed" and run.get("conclusion") == "success"
        and bool(SHA.fullmatch(run.get("head_sha", "")))
        and tested_commit.get("tree", {}).get("sha") == tree
        and len(tested_commit.get("parents", [])) == 2
        and run["head_sha"] in [p.get("sha") for p in tested_commit.get("parents", [])]
        and producer_blob == expected_blob
    )


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def changed(base: str) -> bytes:
    if not SHA.fullmatch(base):
        raise ValueError("invalid base")
    return subprocess.run(["git", "diff", "--no-renames", "--name-status", "-z", base, "HEAD"],
                          check=True, capture_output=True).stdout


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, repo: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not token:
            raise ValueError("invalid GitHub context")
        self.root = f"https://api.github.com/repos/{repo}"
        self.token = token

    def get(self, path: str) -> dict:
        req = Request(self.root + path, headers={"Accept": "application/vnd.github+json",
                                                 "Authorization": f"Bearer {self.token}"})
        with urlopen(req, timeout=15) as response:
            return json.load(response)

    def artifact_commit(self, url: str) -> str:
        if not url.startswith(self.root + "/actions/artifacts/") or not url.endswith("/zip"):
            raise ValueError("unexpected artifact URL")
        req = Request(url, headers={"Accept": "application/vnd.github+json",
                                    "Authorization": f"Bearer {self.token}"})
        opener = build_opener(NoRedirect)
        try:
            opener.open(req, timeout=15)
        except Exception as exc:
            if getattr(exc, "code", None) != 302:
                raise
            location = exc.headers.get("Location", "")
        else:
            raise ValueError("missing artifact redirect")
        parsed = urlparse(location)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname == "api.github.com":
            raise ValueError("unexpected artifact redirect")
        with urlopen(Request(location), timeout=30) as response:
            archive = response.read(100_000)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            names = zf.namelist()
            if names != ["tested-commit.txt"]:
                raise ValueError("unexpected artifact content")
            sha = zf.read(names[0]).decode("ascii").strip()
        if not SHA.fullmatch(sha):
            raise ValueError("invalid tested commit")
        return sha


def previous_main_success(api: GitHub, before: str) -> bool:
    if not SHA.fullmatch(before):
        return False
    query = urlencode({"event": "push", "head_sha": before, "status": "success", "per_page": 100})
    runs = api.get(f"/actions/workflows/test.yml/runs?{query}").get("workflow_runs", [])
    return any(r.get("head_sha") == before and r.get("event") == "push"
               and r.get("conclusion") == "success" and r.get("head_branch") == "main"
               for r in runs)


def reusable_tree(api: GitHub, tree: str, repo_id: int, workflow_id: int,
                  expected_blob: str) -> bool:
    query = urlencode({"name": f"validated-tree-{tree}", "per_page": 100})
    artifacts = api.get(f"/actions/artifacts?{query}").get("artifacts", [])
    for artifact in artifacts:
        try:
            run_id = artifact["workflow_run"]["id"]
            run = api.get(f"/actions/runs/{run_id}")
            if run.get("conclusion") != "success" or run.get("event") != "pull_request":
                continue
            tested_sha = api.artifact_commit(artifact["archive_download_url"])
            tested_commit = api.get(f"/git/commits/{tested_sha}")
            producer = api.get("/contents/.github/workflows/test.yml?" +
                               urlencode({"ref": run["head_sha"]}))
            if valid_reuse(tree, artifact, run, tested_commit, producer.get("sha", ""),
                           repo_id=repo_id, workflow_id=workflow_id,
                           expected_blob=expected_blob, tested_sha=tested_sha):
                return True
        except (KeyError, ValueError, TypeError, AttributeError, OSError,
                UnicodeError, zipfile.BadZipFile):
            continue
    return False


def main() -> int:
    run_product, reason = True, "fail-closed"
    try:
        event = os.environ["GITHUB_EVENT_NAME"]
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        base = payload["pull_request"]["base"]["sha"] if event == "pull_request" else payload.get("before", "")
        is_docs = docs_only(changed(base)) if event in ("pull_request", "push") else False
        previous, reusable = False, False
        if event == "push":
            api = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
            if is_docs:
                previous = previous_main_success(api, base)
            else:
                tree = git("rev-parse", "HEAD^{tree}")
                repo_id = api.get("")["id"]
                workflow_id = api.get("/actions/workflows/test.yml")["id"]
                expected_blob = git("hash-object", ".github/workflows/test.yml")
                reusable = reusable_tree(api, tree, repo_id, workflow_id, expected_blob)
        run_product = should_run_product(event, is_docs, previous, reusable)
        reason = "docs" if is_docs and not run_product else "reuse" if reusable else "product"
    except (KeyError, ValueError, TypeError, AttributeError, OSError,
            subprocess.CalledProcessError, json.JSONDecodeError,
            UnicodeError, zipfile.BadZipFile) as exc:
        print(f"CI scope: full product contour ({type(exc).__name__})", file=sys.stderr)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"run_product={'true' if run_product else 'false'}\n")
    print(f"CI scope: {reason}; run_product={str(run_product).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
