"""Stage 478A: fail-closed CI scope and exact-tree reuse."""

from pathlib import Path
import os
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_docs_allowlist_is_narrow_and_rename_delete_are_product():
    from scripts.ci_scope import docs_only

    assert docs_only(b"M\0README.md\0A\0PRD/new.md\0")
    for changed in (b"", b"M\0README.md\0M\0server.py\0",
                    b"A\0unknown.md\0", b"M\0.github/workflows/docs.yml\0",
                    b"D\0README.md\0", b"R100\0README.md\0docs/new.md\0",
                    b"M\0docs/../server.py\0", b"M\0docs/a.txt\0",
                    b"M\0docs//a.md\0"):
        assert not docs_only(changed)


def test_main_docs_skip_needs_previous_success():
    from scripts.ci_scope import should_run_product

    assert not should_run_product("pull_request", True, False, False)
    assert not should_run_product("push", True, True, False)
    assert should_run_product("push", True, False, False)
    assert should_run_product("push", False, True, False)
    assert not should_run_product("push", False, False, True)
    assert should_run_product("push", False, False, False)
    assert should_run_product("workflow_dispatch", True, True, True)


def test_reuse_requires_independent_run_commit_and_workflow_proof():
    from scripts.ci_scope import valid_reuse

    tree = "a" * 40
    commit = "b" * 40
    head = "c" * 40
    workflow_blob = "d" * 40
    artifact = {"name": f"validated-tree-{tree}", "expired": False,
                "workflow_run": {"id": 42, "repository_id": 123}}
    run = {"id": 42, "repository": {"id": 123}, "head_repository": {"id": 123},
           "workflow_id": 9, "event": "pull_request", "conclusion": "success",
           "status": "completed", "head_sha": head,
           "path": ".github/workflows/test.yml"}
    tested_commit = {"tree": {"sha": tree},
                     "parents": [{"sha": "f" * 40}, {"sha": head}]}
    assert valid_reuse(tree, artifact, run, tested_commit, workflow_blob,
                       repo_id=123, workflow_id=9, expected_blob=workflow_blob,
                       tested_sha=commit)
    assert not valid_reuse("e" * 40, artifact, run, tested_commit, workflow_blob,
                           repo_id=123, workflow_id=9, expected_blob=workflow_blob,
                           tested_sha=commit)
    assert not valid_reuse(tree, artifact, {**run, "conclusion": "failure"},
                           tested_commit, workflow_blob, repo_id=123, workflow_id=9,
                           expected_blob=workflow_blob, tested_sha=commit)
    assert not valid_reuse(tree, artifact, {**run, "head_repository": {"id": 999}},
                           tested_commit, workflow_blob, repo_id=123, workflow_id=9,
                           expected_blob=workflow_blob, tested_sha=commit)
    assert not valid_reuse(tree, artifact, run, tested_commit, "e" * 40,
                           repo_id=123, workflow_id=9, expected_blob=workflow_blob,
                           tested_sha=commit)
    assert not valid_reuse(tree, artifact, run,
                           {"tree": {"sha": tree}, "parents": [{"sha": head}]},
                           workflow_blob, repo_id=123, workflow_id=9,
                           expected_blob=workflow_blob, tested_sha=commit)


def test_reuse_fetches_linked_run_and_rejects_forged_marker():
    from scripts.ci_scope import reusable_tree

    tree, tested, head, blob = "a" * 40, "b" * 40, "c" * 40, "d" * 40
    artifact = {"name": f"validated-tree-{tree}", "expired": False,
                "workflow_run": {"id": 42, "repository_id": 123},
                "archive_download_url": "https://api.github.com/repos/x/y/actions/artifacts/5/zip"}
    run = {"id": 42, "repository": {"id": 123}, "head_repository": {"id": 123},
           "workflow_id": 9, "event": "pull_request", "conclusion": "success",
           "status": "completed", "head_sha": head,
           "path": ".github/workflows/test.yml"}

    class API:
        def __init__(self, **overrides):
            self.responses = {
                "/actions/runs/42": run,
                f"/git/commits/{tested}": {"tree": {"sha": tree},
                                           "parents": [{"sha": "f" * 40}, {"sha": head}]},
            }
            self.responses.update(overrides)
            self.calls = []

        def get(self, path):
            self.calls.append(path)
            if path.startswith("/actions/artifacts?"):
                return {"artifacts": [artifact]}
            if path.startswith("/contents/.github/workflows/test.yml?"):
                return {"sha": blob}
            return self.responses[path]

        def artifact_commit(self, url):
            assert url == artifact["archive_download_url"]
            return tested

    api = API()
    assert reusable_tree(api, tree, 123, 9, blob)
    assert "/actions/runs/42" in api.calls
    assert f"/git/commits/{tested}" in api.calls
    assert any(p.startswith("/contents/.github/workflows/test.yml?") for p in api.calls)
    assert not reusable_tree(API(**{"/actions/runs/42": {**run, "workflow_id": 10}}),
                             tree, 123, 9, blob)
    assert not reusable_tree(API(**{f"/git/commits/{tested}":
                                    {"tree": {"sha": "e" * 40},
                                     "parents": [{"sha": "f" * 40}, {"sha": head}]}}),
                             tree, 123, 9, blob)


def test_main_api_failure_runs_product(monkeypatch, tmp_path):
    import json
    from scripts import ci_scope

    payload = tmp_path / "event.json"
    payload.write_text(json.dumps({"before": "a" * 40}))
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(payload))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(ci_scope, "changed", lambda base: b"M\0README.md\0")
    monkeypatch.setattr(ci_scope, "previous_main_success", lambda api, before: (_ for _ in ()).throw(OSError()))
    assert ci_scope.main() == 0
    assert output.read_text() == "run_product=true\n"


def test_workflows_keep_checks_and_force_product_on_trust_surface_change():
    tests = yaml.load((ROOT / ".github/workflows/test.yml").read_text(), Loader=yaml.BaseLoader)
    docs = yaml.load((ROOT / ".github/workflows/docs.yml").read_text(), Loader=yaml.BaseLoader)
    assert "paths-ignore" not in tests["on"]["push"]
    assert "paths-ignore" not in tests["on"]["pull_request"]
    assert "paths" not in docs["on"]["push"]
    assert "paths" not in docs["on"]["pull_request"]
    assert docs["permissions"] == {"contents": "read"}
    jobs = tests["jobs"]
    assert {"scope-and-reuse", "build-image", "fast", "default",
            "postgres-activation-telemetry", "validated-tree"} <= jobs.keys()
    assert "check_roadmap_structure.py" in str(jobs["scope-and-reuse"])
    assert "force_full" in str(jobs["scope-and-reuse"])
    force_step = next(step for step in jobs["scope-and-reuse"]["steps"]
                      if step.get("id") == "force")
    for path in (".github/workflows", "scripts/ci_scope.py",
                 "scripts/check_roadmap_structure.py", "scripts/run_default_test_suite.py"):
        assert path in force_step["run"]
    for name in ("build-image", "fast", "default", "postgres-activation-telemetry"):
        assert "scope-and-reuse" in str(jobs[name]["needs"])
        assert "run_product" in jobs[name]["if"]
    assert "github.run_id" in str(tests["concurrency"])
    assert "github.event_name == 'pull_request'" in str(tests["concurrency"])
    assert "validate" in docs["jobs"]
    assert {"scope-and-reuse", "build-image", "fast", "default",
            "postgres-activation-telemetry"} <= set(jobs["validated-tree"]["needs"])
    assert "github.sha" in str(jobs["validated-tree"]["steps"])


def test_main_force_guard_catches_earlier_commit_in_push(tmp_path):
    before = "a" * 40
    fake_git = tmp_path / "git"
    fake_git.write_text("#!/bin/sh\n# Earlier commit changed the decision script.\n"
                        "[ \"$3\" = \"$BEFORE_SHA\" ] && exit 1\nexit 0\n")
    fake_git.chmod(0o755)
    tests = yaml.load((ROOT / ".github/workflows/test.yml").read_text(), Loader=yaml.BaseLoader)
    script = next(step["run"] for step in tests["jobs"]["scope-and-reuse"]["steps"]
                  if step.get("id") == "force")
    script = script.replace("${{ github.event_name }}", "push")
    script = script.replace("${{ github.event.before }}", before)
    output = tmp_path / "output"
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
           "GITHUB_OUTPUT": str(output),
           "GITHUB_EVENT_NAME": "push", "BEFORE_SHA": before}
    subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path, env=env,
                   check=True, capture_output=True, text=True)
    assert "force_full=true" in output.read_text()
