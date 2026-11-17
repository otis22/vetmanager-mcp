#!/usr/bin/env python3
"""Run repository test contours in a fresh, disposable Docker Compose project."""

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
import hashlib
import hmac
import fcntl
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.real_group_gate import (MANIFEST, digest_files, manifest_hash, runtime_files,
                                     test_files, validate_aggregate, validate_manifest, load_latest_attempts,
                                     validate_shard)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.test_recovery_supervisor import (
    owned_container, supervise, validate_focus_result, validate_recovery_result,
    validate_real_junit_results,
)

ROOT = Path(__file__).resolve().parents[1]


def contour_hmac(key, paths):
    configured = {name: value for name, value in os.environ.items()
                  if name.startswith(("TEST_", "STAGE385_", "STAGE400_", "STAGE408_", "RUN_REAL_"))}
    material = b"".join(Path(path).read_bytes() for path in paths) + json.dumps(configured, sort_keys=True).encode()
    return hmac.new(key, material, hashlib.sha256).hexdigest()


def resolve_test_image_id(compose, env=None):
    """Inspect the image Compose actually configured for its test service."""
    configuration = json.loads(subprocess.check_output(
        [*compose, "config", "--format", "json"], text=True, env=env))
    image = configuration["services"]["test"]["image"]
    if not isinstance(image, str) or not image:
        raise ValueError("test image is not configured")
    image_id = subprocess.check_output(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip()
    if not image_id.startswith("sha256:"):
        raise ValueError("test image ID is missing")
    return image_id


def current_real_image_evidence(compose, env):
    """Read current image and installed dependencies, never shard-supplied values."""
    image_id = resolve_test_image_id(compose, env)
    frozen = subprocess.check_output(
        ["docker", "run", "--rm", "--entrypoint", "python", image_id,
         "-m", "pip", "freeze"], text=True)
    return {"image_id": image_id,
            "dependency_fingerprint": hashlib.sha256(frozen.encode()).hexdigest()}


def group_image_build_required(root, *, requested):
    """Build once per real evidence root so every shard uses the same image."""
    if (root / "test-image.id").is_file():
        if requested:
            raise ValueError("real group rebuild would invalidate previous shards")
        return False
    return True


def pin_group_image(root, image_id):
    """Reject an external image replacement before a later group starts."""
    marker = root / "test-image.id"
    if marker.is_file():
        if marker.read_text().strip() != image_id:
            raise ValueError("real group test image changed between shards")
    else:
        marker.write_text(image_id + "\n")


def create_private_auth_file(path):
    """Refuse an existing file before a test token can be written to it."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", action="append", default=[])
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--suite", choices=("all", "default", "real", "postgres", "recovery", "focus"), default="all")
    parser.add_argument("--group")
    parser.add_argument("--list-groups", action="store_true")
    parser.add_argument("--validate-manifest", action="store_true")
    parser.add_argument("--aggregate", action="store_true")
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    if args.list_groups:
        for name, nodes in manifest["groups"].items():
            print(f"{name}: {len(nodes)} nodes")
        return 0
    if args.aggregate:
        if args.evidence_dir is None:
            parser.error("aggregate requires --evidence-dir")
        root = args.evidence_dir.resolve()
        validation = root / ("aggregate-collect-" + uuid.uuid4().hex[:12])
        subprocess.run([sys.executable, str(Path(__file__)), "--validate-manifest",
                        "--evidence-dir", str(validation),
                        *(item for path in args.env_file for item in ("--env-file", path))],
                       cwd=ROOT, check=True)
        lock = (root / "run.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("group run is still active") from exc
        attempts = load_latest_attempts(root)
        env_paths = args.env_file or ([str(ROOT / ".env")] if (ROOT / ".env").exists() else [])
        key_path = root / "contour.key"
        if not key_path.is_file():
            raise ValueError("missing contour key")
        contour = contour_hmac(key_path.read_bytes(), env_paths)
        environment = dict(os.environ)
        environment.update(TEST_POSTGRES_PASSWORD="stage469-synthetic",
                           TEST_STORAGE_ENCRYPTION_KEY="stage469-synthetic",
                           TEST_WEB_SESSION_SECRET="stage469-synthetic")
        image_compose = ["docker", "compose", "--profile", "test",
                         *(item for path in env_paths for item in ("--env-file", str(Path(path).resolve()))),
                         "-f", str(ROOT / "docker-compose.test.yml")]
        current_image = current_real_image_evidence(image_compose, environment)
        expected = {name: {"manifest_hash": manifest_hash(manifest),
                           "runtime_fingerprint": digest_files(runtime_files()),
                           "test_fingerprint": digest_files(test_files(manifest, name)),
                           "contour_identity": contour,
                           **current_image}
                    for name in manifest["groups"] if name in attempts}
        validate_aggregate(manifest, attempts, root, expected)
        print("aggregate: all groups passed")
        return 0
    if args.group and args.group not in manifest["groups"]:
        parser.error("unknown real group")
    if args.group and args.evidence_dir is None:
        parser.error("group requires --evidence-dir")
    evidence_root = args.evidence_dir.resolve() if args.group else None
    if args.group:
        if evidence_root == ROOT or ROOT in evidence_root.parents:
            parser.error("evidence must be outside repository")
        evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        initial_runtime = digest_files(runtime_files())
        initial_tests = digest_files(test_files(manifest, args.group))
        if evidence_root.stat().st_mode & 0o077:
            parser.error("evidence root is accessible to other users")
        run_lock = (evidence_root / "run.lock").open("a")
        try:
            fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another group is using this upstream guard") from exc
        index_path = evidence_root / "attempts.jsonl"
        args.build = group_image_build_required(evidence_root, requested=args.build)
        if index_path.exists() and args.group != "write-restore":
            latest_write = None
            for line in index_path.read_text().splitlines():
                entry = json.loads(line)
                if entry["group"] == "write-restore":
                    latest_write = entry
            if latest_write is not None:
                path = evidence_root / latest_write["directory"] / "shard.json"
                if not path.is_file() or json.loads(path.read_text()).get("results") != {"test": 0, "cleanup": 0}:
                    raise ValueError("unfinished write/restore group blocks later groups")
        evidence = evidence_root / (args.group + "-" + uuid.uuid4().hex[:12])
        # Register attempt before any build or test; a later failed attempt supersedes green.
        with index_path.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(json.dumps({"group": args.group, "directory": evidence.name}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            fcntl.flock(stream, fcntl.LOCK_UN)
    else:
        evidence = (args.evidence_dir or Path(tempfile.mkdtemp(prefix="vetmanager-tests-"))).resolve()
    if evidence == ROOT or ROOT in evidence.parents:
        parser.error("Evidence and generated credentials must be outside the repository")
    evidence.mkdir(parents=True, exist_ok=True)
    if (evidence / "summary.json").exists():
        parser.error("Use a new evidence directory for each run")
    hook = evidence / "pg-hook"
    hook.mkdir(exist_ok=True)
    if any(hook.iterdir()):
        parser.error("Recovery hook directory must be empty")
    project = "vm-test-" + uuid.uuid4().hex[:12]
    runtime = evidence / "runtime.env"
    generated = {
        "TEST_POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "TEST_STORAGE_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "TEST_WEB_SESSION_SECRET": secrets.token_urlsafe(32),
    }
    fd = os.open(runtime, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in generated.items()))
    auth = evidence / "auth.env"
    create_private_auth_file(auth)
    volumes = [f"{evidence}:/evidence"]
    docker = shutil.which("docker")
    plugin = next((p for p in (
        Path("/usr/libexec/docker/cli-plugins/docker-compose"),
        Path("/usr/lib/docker/cli-plugins/docker-compose"),
        Path("/usr/local/lib/docker/cli-plugins/docker-compose"),
    ) if p.is_file()), None)
    if docker and plugin:
        volumes += [f"{Path(docker).resolve()}:/usr/bin/docker:ro",
                    f"{plugin}:/usr/libexec/docker/cli-plugins/docker-compose:ro"]
    override = evidence / "mounts.json"
    override.write_text(json.dumps({"services": {"test": {"volumes": volumes}}}))
    compose = ["docker", "compose", "-p", project, "--profile", "test"]
    for path in args.env_file or ([str(ROOT / ".env")] if (ROOT / ".env").exists() else []):
        compose += ["--env-file", str(Path(path).resolve())]
    compose += ["--env-file", str(runtime), "--env-file", str(auth),
                "-f", str(ROOT / "docker-compose.test.yml"), "-f", str(override)]
    summary = {"project": project, "sha": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "results": {}}

    def run(name, command, recovery=False):
        print(f"Running {name}; evidence: {evidence / (name + '.log')}", flush=True)
        if recovery:
            code = supervise(command, compose, project, hook, evidence / (name + ".log"))
        else:
            with (evidence / (name + ".log")).open("w") as log:
                process = subprocess.Popen(command, cwd=ROOT, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = process.wait()
                except BaseException:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                    raise
        summary["results"][name] = code
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"{name}: exit {code}", flush=True)
        return code

    def test_command(*command, real=False, real_junit=False):
        grace = ["-e", "VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS=0.5"] if real else []
        if real_junit:
            grace += ["-e", "REAL_JUNIT_DIR=/evidence"]
        return [*compose, "run", "--rm", "-T", *grace, "test", *command]

    def terminate(_sig, _frame):
        raise KeyboardInterrupt

    prior = signal.signal(signal.SIGTERM, terminate)
    try:
        if args.build and run("build", [*compose, "build", "test"]):
            return 1
        if args.group:
            pin_group_image(evidence_root, resolve_test_image_id(compose))
        if run("startup", [*compose, "up", "-d", "--wait", "pg", "redis"]):
            return 1
        for database in ("stage385", "stage400", "stage408"):
            if run("create-" + database, [*compose, "exec", "-T", "pg", "createdb", "-U", "vetmanager", database]):
                return 1
        if args.group or args.validate_manifest:
            collect_command = test_command("python", "-m", "pytest", "--collect-only", "-q", "-m",
                                           manifest["marker_expression"], "tests/")
            if run("collect", collect_command):
                return 1
            collected = [line.strip() for line in (evidence / "collect.log").read_text().splitlines()
                         if line.startswith("tests/") and "::" in line]
            validate_manifest(manifest, collected)
            if args.validate_manifest and not args.group:
                return 0
        if args.suite in ("real", "all", "focus", "recovery"):
            required_auth = (["--require-all"] if args.suite in ("real", "all") else
                             ["--require-api"] if args.suite == "recovery" else [])
            if run("auth", test_command("python", "scripts/prepare_real_test_auth.py", "/evidence/auth.env", *required_auth)):
                return 1
        if args.group:
            before = initial_runtime
            tests_before = initial_tests
            if before != digest_files(runtime_files()) or tests_before != digest_files(test_files(manifest, args.group)):
                raise ValueError("sources changed during group build or auth")
            nodes_file = evidence / "nodes.json"
            nodes_file.write_text(json.dumps(manifest["groups"][args.group]))
            run("real-group", test_command("python", "scripts/run_opt_in_real_test_suite.py",
                                            "--group-nodes-file", "/evidence/nodes.json",
                                            real=True, real_junit=True), recovery=True)
            (evidence / "group.xml").rename(evidence / f"{args.group}.xml") if (evidence / "group.xml").exists() else None
            (evidence / "group.outcome.json").rename(evidence / f"{args.group}.outcome.json") if (evidence / "group.outcome.json").exists() else None
            image_id = resolve_test_image_id(compose)
            dependency = subprocess.check_output([*compose, "run", "--rm", "-T", "test", "python", "-m", "pip", "freeze"], text=True)
            env_paths = args.env_file or ([str(ROOT / ".env")] if (ROOT / ".env").exists() else [])
            key_path = evidence_root / "contour.key"
            if not key_path.exists():
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(os.urandom(32))
            contour = contour_hmac(key_path.read_bytes(), env_paths)
            shard = {"group": args.group, "nodes": manifest["groups"][args.group],
                     "created_at": time.time(),
                     "manifest_hash": manifest_hash(manifest), "runtime_fingerprint": before,
                     "test_fingerprint": tests_before, "dependency_fingerprint": hashlib.sha256(dependency.encode()).hexdigest(),
                     "contour_identity": contour, "image_id": image_id,
                     "results": {"test": summary["results"]["real-group"], "cleanup": 1}}
            (evidence / "shard.json").write_text(json.dumps(shard, indent=2) + "\n")
            if before != digest_files(runtime_files()) or tests_before != digest_files(test_files(manifest, args.group)):
                raise ValueError("sources changed during group run")
            return 0
        if args.suite in ("default", "all"):
            run("default", test_command("python", "scripts/run_default_test_suite.py"))
        if args.suite in ("postgres", "all"):
            run("postgres", test_command("sh", "-c", "python -W error -m pytest -q -m postgres "
                "--junitxml=/evidence/postgres.xml && python scripts/check_stage424_postgres_results.py /evidence/postgres.xml"))
        if args.suite in ("real", "all"):
            run("real", test_command("python", "scripts/run_opt_in_real_test_suite.py",
                                     real=True, real_junit=True), recovery=True)
            try:
                validate_real_junit_results(
                    evidence / "real-group-1.xml", evidence / "real-group-2.xml",
                    evidence / "real-group-1.outcome.json", evidence / "real-group-2.outcome.json")
                real_junit_code = 0
            except (OSError, ValueError):
                real_junit_code = 1
            summary["results"]["real-junit-result"] = real_junit_code
            (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        if args.suite in ("focus", "recovery"):
            nodes = args.tests or (["tests/test_stage385_pg_recovery_live.py"] if args.suite == "recovery" else [])
            if not nodes:
                parser.error("focus requires explicit pytest node IDs")
            run("focus", test_command("python", "-W", "error", "-m", "pytest", "-v", "-rs",
                "--junitxml=/evidence/focus.xml", *nodes, real=True), recovery=True)
            try:
                validate_focus_result(evidence / "focus.xml", nodes)
                focus_code = 0
            except (OSError, ValueError):
                focus_code = 1
            summary["results"]["focus-result"] = focus_code
            (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            if args.suite == "recovery":
                try:
                    validate_recovery_result(evidence / "focus.xml")
                    code = 0
                except (OSError, ValueError):
                    code = 1
                summary["results"]["recovery-result"] = code
                (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return int(any(summary["results"].values()))
    finally:
        signal.signal(signal.SIGTERM, prior)
        # Never clean an existing installation, even if Compose returned a bad ID.
        ids = subprocess.check_output([*compose, "ps", "-a", "-q"], text=True).split()
        for container in ids:
            owned_container(container, project, service=None)
        if run("cleanup", [*compose, "down", "-v", "--remove-orphans"]):
            raise RuntimeError("Isolated test cleanup failed")
        if args.group and (evidence / "shard.json").exists():
            shard = json.loads((evidence / "shard.json").read_text())
            shard["results"]["cleanup"] = 0
            (evidence / "shard.json").write_text(json.dumps(shard, indent=2) + "\n")
            validate_shard(manifest, shard, evidence, {key: shard[key] for key in (
                "manifest_hash", "runtime_fingerprint", "test_fingerprint", "dependency_fingerprint", "contour_identity")})
        if args.group:
            run_lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
