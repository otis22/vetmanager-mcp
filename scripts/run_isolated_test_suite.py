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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.test_recovery_supervisor import owned_container, supervise, validate_recovery_result

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", action="append", default=[])
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--suite", choices=("all", "default", "real", "postgres", "recovery", "focus"), default="all")
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
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
    auth.touch(mode=0o600)
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

    def test_command(*command):
        return [*compose, "run", "--rm", "-T", "test", *command]

    def terminate(_sig, _frame):
        raise KeyboardInterrupt

    prior = signal.signal(signal.SIGTERM, terminate)
    try:
        if args.build and run("build", [*compose, "build", "test"]):
            return 1
        if run("startup", [*compose, "up", "-d", "--wait", "pg", "redis"]):
            return 1
        for database in ("stage385", "stage400", "stage408"):
            if run("create-" + database, [*compose, "exec", "-T", "pg", "createdb", "-U", "vetmanager", database]):
                return 1
        if args.suite in ("real", "all", "focus", "recovery"):
            required_auth = (["--require-all"] if args.suite in ("real", "all") else
                             ["--require-api"] if args.suite == "recovery" else [])
            if run("auth", test_command("python", "scripts/prepare_real_test_auth.py", "/evidence/auth.env", *required_auth)):
                return 1
        if args.suite in ("default", "all"):
            run("default", test_command("python", "scripts/run_default_test_suite.py"))
        if args.suite in ("postgres", "all"):
            run("postgres", test_command("sh", "-c", "python -W error -m pytest -q -m postgres "
                "--junitxml=/evidence/postgres.xml && python scripts/check_stage424_postgres_results.py /evidence/postgres.xml"))
        if args.suite in ("real", "all"):
            run("real", test_command("python", "scripts/run_opt_in_real_test_suite.py"), recovery=True)
        if args.suite in ("focus", "recovery"):
            nodes = args.tests or (["tests/test_stage385_pg_recovery_live.py"] if args.suite == "recovery" else [])
            if not nodes:
                parser.error("focus requires explicit pytest node IDs")
            run("focus", test_command("python", "-W", "error", "-m", "pytest", "-v", "-rs",
                "--junitxml=/evidence/focus.xml", *nodes), recovery=True)
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


if __name__ == "__main__":
    raise SystemExit(main())
