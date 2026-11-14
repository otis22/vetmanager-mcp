"""Host-side supervision of the live test's dedicated PostgreSQL container."""

import json
import subprocess
import time
from pathlib import Path


def owned_container(container_id, project, service="pg"):
    """Resolve and validate an exact ID before any state-changing Docker call."""
    if not container_id:
        raise RuntimeError("Missing isolated PostgreSQL container")
    result = subprocess.run(["docker", "inspect", container_id], check=True,
                            capture_output=True, text=True)
    info = json.loads(result.stdout)[0]
    labels = info.get("Config", {}).get("Labels", {})
    if labels.get("com.docker.compose.project") != project or (service is not None and labels.get("com.docker.compose.service") != service):
        raise RuntimeError("Refusing to change a container outside this test project")
    return info["Id"]


def supervise(command, compose, project, hook, log_path):
    """Run pytest, stopping PostgreSQL only after its upstream write returned."""
    hook = Path(hook)
    assert hook.is_dir() and not any(hook.iterdir())
    pg_id = subprocess.check_output([*compose, "ps", "-q", "pg"], text=True).strip()
    pg_id = owned_container(pg_id, project)
    stopped = False
    released = False
    deadline = None
    with Path(log_path).open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                if not released and (hook / "entered").exists():
                    owned_container(pg_id, project)
                    stopped = True  # A failed Docker response may still have stopped it.
                    subprocess.run(["docker", "stop", "-t", "3", pg_id], check=True,
                                   stdout=log, stderr=log)
                    released = True
                    (hook / "release").touch()
                    deadline = time.monotonic() + 60
                if stopped and (hook / "write_done").exists():
                    owned_container(pg_id, project)
                    subprocess.run([*compose, "up", "-d", "--wait", "pg"], check=True,
                                   stdout=log, stderr=log)
                    stopped = False
                    (hook / "restored").touch()
                if stopped and time.monotonic() > deadline:
                    raise TimeoutError("PostgreSQL recovery writer did not finish")
                time.sleep(.1)
            return process.returncode
        finally:
            if stopped:
                owned_container(pg_id, project)
                subprocess.run([*compose, "up", "-d", "--wait", "pg"], check=True,
                               stdout=log, stderr=log)
                (hook / "restored").touch()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
