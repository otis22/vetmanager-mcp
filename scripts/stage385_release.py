#!/usr/bin/env python3
"""Stage a versioned release and freeze a single-slot pre-385 rollback manifest."""

from __future__ import annotations

import argparse
import copy
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

import yaml


SHA = re.compile(r"[0-9a-f]{40,64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
EXCLUDES = (".git/", ".venv/", ".cursor/", "__pycache__/",
            ".pytest_cache/", ".env", "data/", "logs/")
SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
               "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=20")


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def _git_output(checkout: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(checkout), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _verified_checkout_sha(checkout: Path) -> str:
    head = _git_output(checkout, "rev-parse", "HEAD")
    if _git_output(checkout, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Release checkout must be clean")
    return head


def _tracked_files(checkout: Path) -> bytes:
    files = subprocess.run(["git", "-C", str(checkout), "ls-files", "--cached", "-z"],
                           check=True, capture_output=True).stdout
    if not files or any(path == b".env" or path.startswith(b".env/")
                        for path in files.split(b"\0") if path):
        raise ValueError("Release tracked files are empty or include .env")
    return files


def stage_remote_release(checkout: Path, ssh_target: str,
                         remote_dir: str, sha: str) -> str:
    """Rsync only into a fresh SHA directory; leave the live checkout untouched."""
    if not SHA.fullmatch(sha):
        raise ValueError("Release SHA must be a full lowercase Git SHA")
    if _verified_checkout_sha(checkout) != sha:
        raise ValueError("Release SHA does not match checkout HEAD")
    if not remote_dir.startswith("/") or ".." in Path(remote_dir).parts or "\n" in remote_dir:
        raise ValueError("Remote directory must be an absolute safe path")
    if not ssh_target or any(char.isspace() for char in ssh_target):
        raise ValueError("Invalid SSH target")
    release_dir = f"{remote_dir.rstrip('/')}/releases/{sha}"
    release_parent = f"{remote_dir.rstrip('/')}/releases"
    _run(["ssh", *SSH_OPTIONS, ssh_target, f"mkdir -p -- {shlex.quote(release_parent)} && "
          f"mkdir -m 700 -- {shlex.quote(release_dir)}"])
    with tempfile.NamedTemporaryFile() as file_list:
        file_list.write(_tracked_files(checkout))
        file_list.flush()
        _run(["rsync", "-az", "-e", "ssh " + " ".join(SSH_OPTIONS),
              "--from0", f"--files-from={file_list.name}",
              *(f"--exclude={item}" for item in EXCLUDES),
              f"{checkout.resolve()}/", f"{ssh_target}:{release_dir}/"])
    return release_dir


def _volume_target(volume: object) -> str:
    if isinstance(volume, dict):
        return str(volume.get("target", ""))
    if isinstance(volume, str):
        fields = volume.split(":")
        return fields[1] if len(fields) > 1 else ""
    raise ValueError("Unknown Compose volume syntax")


def _is_code_bind(volume: object) -> bool:
    target = _volume_target(volume)
    if target == "/app":
        return True
    if not target.startswith("/app/"):
        return False
    if isinstance(volume, dict):
        source = str(volume.get("source", ""))
        return volume.get("type") == "bind" or source.startswith((".", "/"))
    source = volume.split(":", 1)[0]
    return source.startswith((".", "/"))


def make_rollback_manifest(compose: dict, pre385_image_id: str,
                           compose_project_name: str, *, slot_count: int = 1) -> dict:
    if not IMAGE_ID.fullmatch(pre385_image_id):
        raise ValueError("Rollback image must be a pinned sha256 image ID")
    if not PROJECT.fullmatch(compose_project_name):
        raise ValueError("Rollback requires the existing Compose project name")
    manifest = copy.deepcopy(compose)
    if manifest.get("name") and manifest["name"] != compose_project_name:
        raise ValueError("Compose project name conflicts with rollback source")
    manifest["name"] = compose_project_name
    services = manifest.get("services")
    if not isinstance(services, dict) or "mcp" not in services:
        raise ValueError("Compose manifest has no MCP service")
    if slot_count not in (1, 3):
        raise ValueError("Rollback slot count must be one or three")
    if slot_count == 1:
        services.pop("mcp2", None)
        services.pop("mcp3", None)
    services.pop("test", None)
    for service in ("mcp", "mcp2", "mcp3")[:slot_count]:
        if service not in services:
            raise ValueError(f"Rollback manifest has no {service} service")
        mcp = services[service]
        mcp.pop("build", None)
        mcp["image"] = pre385_image_id
        volumes = mcp.get("volumes", [])
        mcp["volumes"] = [volume for volume in volumes if not _is_code_bind(volume)]
        if not any(_volume_target(volume) == "/app/data" for volume in mcp["volumes"]):
            raise ValueError("Rollback manifest must retain shared /app/data")
        environment = mcp.get("environment", [])
        if not isinstance(environment, list):
            raise ValueError("MCP environment must be Compose list syntax")
        mcp["environment"] = [
            f"MCP_WORKER_SLOTS={slot_count}" if str(item).startswith("MCP_WORKER_SLOTS=") else item
            for item in environment
        ]
    volumes = manifest.get("volumes")
    if not isinstance(volumes, dict):
        raise ValueError("Compose named volumes are missing")
    for volume_name, config in volumes.items():
        explicit = config.get("name") if isinstance(config, dict) else None
        volumes[volume_name] = {
            "external": True,
            "name": explicit or f"{compose_project_name}_{volume_name}",
        }
    return manifest


def write_rollback_manifest(output: Path, manifest: dict) -> None:
    """Create once so a later checkout cannot silently rewrite rollback evidence."""
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(manifest, handle, sort_keys=False, allow_unicode=True)
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("checkout", type=Path)
    stage.add_argument("ssh_target")
    stage.add_argument("remote_dir")
    stage.add_argument("sha")
    rollback = commands.add_parser("rollback-manifest")
    rollback.add_argument("compose_file", type=Path)
    rollback.add_argument("pre385_image_id")
    rollback.add_argument("compose_project_name")
    rollback.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "stage":
        print(stage_remote_release(args.checkout, args.ssh_target, args.remote_dir, args.sha))
    else:
        source = yaml.safe_load(args.compose_file.read_text())
        write_rollback_manifest(args.output,
                                make_rollback_manifest(source, args.pre385_image_id,
                                                       args.compose_project_name))
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
