"""Stage 407: every live build resolves the public, pinned GHCR base."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DIGEST = "sha256:139b146ecf6cadf1960a88887c83846bd030bf1bc0a478fae48215c49917c075"
BASE = f"ghcr.io/otis22/python:3.12-slim@{DIGEST}"


def test_dockerfile_pins_public_ghcr_base_for_all_targets():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert f"ARG BASE_IMAGE={BASE}" in dockerfile
    assert "FROM ${BASE_IMAGE} AS base" in dockerfile
    assert "public.ecr.aws" not in dockerfile


def test_ci_and_production_build_paths_do_not_override_or_resolve_ecr():
    workflows = ROOT / ".github/workflows"
    for name in ("test.yml", "test-real.yml", "deploy-prod.yml"):
        content = (workflows / name).read_text()
        assert "public.ecr.aws" not in content, name
        assert "BASE_IMAGE=" not in content, name
    compose = (ROOT / "docker-compose.yml").read_text()
    deploy = (ROOT / "scripts/stage385_deploy.py").read_text()
    assert "public.ecr.aws" not in compose + deploy
    assert "BASE_IMAGE" not in compose + deploy
    tests = yaml.load((workflows / "test.yml").read_text(), Loader=yaml.BaseLoader)
    assert tests["jobs"]["postgres-activation-telemetry"]["services"]["postgres"]["image"] == "postgres:16-alpine"


def test_deploy_checks_remote_docker_architecture_before_build():
    deploy = (ROOT / ".github/workflows/deploy-prod.yml").read_text()
    assert "docker info --format" in deploy
    assert "x86_64" in deploy
    preflight = deploy.split("- name: Verify production Docker architecture", 1)[1].split("- name: Stage immutable release", 1)[0]
    assert "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new" in preflight
    assert deploy.index("docker info --format") < deploy.index("Stage immutable release")
