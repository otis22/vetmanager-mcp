"""Stage 406: CI image reuse, GHA cache and trusted release trigger."""

from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]


def workflow(name: str) -> dict:
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def steps(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def test_docs_push_skips_tests_but_has_lightweight_validation():
    tests = workflow("test.yml")
    for event in ("push", "pull_request"):
        ignored = set(tests["on"][event]["paths-ignore"])
        assert {"**.md", "PRD/**", "docs/**"} <= ignored
    assert "workflow_dispatch" in tests["on"]
    docs = workflow("docs.yml")
    assert "check_roadmap_structure.py" in steps(docs["jobs"]["validate"])


def test_one_image_build_feeds_three_test_jobs():
    jobs = workflow("test.yml")["jobs"]
    assert "build-image" in jobs
    build_steps = jobs["build-image"]["steps"]
    assert sum(step.get("uses", "").startswith("docker/build-push-action@") for step in build_steps) == 1
    assert "docker/setup-buildx-action@v3" in str(build_steps)
    assert "docker save" in steps(jobs["build-image"])
    assert "actions/upload-artifact@v4" in str(jobs["build-image"])
    for name in ("fast", "default", "postgres-activation-telemetry"):
        job = jobs[name]
        assert job["needs"] == "build-image"
        assert "actions/download-artifact@v4" in str(job)
        assert "docker load" in steps(job)
        assert "docker build" not in steps(job)


def test_ci_builds_use_gha_cache_and_keep_ecr_base():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "ARG BASE_IMAGE=public.ecr.aws/docker/library/python:3.12-slim" in dockerfile
    for name in ("test.yml", "test-real.yml"):
        contents = workflow(name)
        build_steps = [step for job in contents["jobs"].values()
                       for step in job["steps"] if step.get("uses", "").startswith("docker/build-push-action@")]
        assert len(build_steps) == 1
        assert "type=gha" in build_steps[0]["with"]["cache-from"]
        assert "type=gha" in build_steps[0]["with"]["cache-to"]


def test_deploy_requires_trusted_upstream_event():
    deploy = workflow("deploy-prod.yml")
    assert deploy["on"]["workflow_run"]["workflows"] == ["Tests"]
    gate = deploy["jobs"]["changes"]["if"]
    assert "head_repository.full_name == github.repository" in gate
    assert "workflow_run.event == 'push'" in gate
    assert "workflow_run.event == 'workflow_dispatch'" in gate


def test_deploy_scope_skips_docs_then_deploys_code():
    script = ROOT / "scripts/deploy_scope_check.sh"
    for paths, expected in ((["PRD/этап-406.md", "AssumptionLog.md"], "false"),
                            (["PRD/этап-406.md", "Dockerfile"], "true")):
        result = subprocess.run([str(script)], input="\0".join(paths).encode() + b"\0",
                                capture_output=True, check=True)
        assert result.stdout.decode().strip() == expected
