"""Host-side supervision of the live test's dedicated PostgreSQL container."""

import json
import subprocess
import time
from pathlib import Path
import xml.etree.ElementTree as ET


def validate_real_junit_results(group_one, group_two, outcome_one=None, outcome_two=None):
    """Require both real groups and the export and report regression cases to pass."""
    groups = []
    for path, outcome_path in ((group_one, outcome_one), (group_two, outcome_two)):
        try:
            root = ET.parse(path).getroot()
            cases = list(root.iter("testcase"))
        except ET.ParseError as exc:
            raise ValueError("Invalid real JUnit result") from exc
        if not cases or any(case.find(tag) is not None for case in cases
                            for tag in ("skipped", "failure", "error")):
            raise ValueError("Real JUnit contains no cases or a non-passing case")
        suites = list(root.iter("testsuite"))
        if not suites or any(int(suite.get("tests", "-1")) < 0 for suite in suites):
            raise ValueError("Real JUnit lacks case totals")
        if sum(int(suite.get("tests", "-1")) for suite in suites) != len(cases):
            raise ValueError("Real JUnit case total differs from cases")
        if outcome_path is not None:
            try:
                outcome = json.loads(Path(outcome_path).read_text())
                collected = outcome["collected"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ValueError("Real outcome missing or invalid") from exc
            if type(collected) is not int or collected != len(cases):
                raise ValueError("Real JUnit differs from collected outcome")
        groups.append(cases)
    required = {
        ("tests.test_stage276_live_export_download", "test_real_export_is_downloaded_cleaned_and_served_by_us"),
        ("tests.test_stage389_live", "test_stage389_two_live_pages"),
    }
    names = {(case.get("classname"), case.get("name")) for case in groups[0]}
    if not required <= names:
        raise ValueError("Real JUnit is missing a mandatory case")
    if not any(case.get("classname") == "tests.test_e2e_real" and
               case.get("name") == "test_real_web_account_can_issue_bearer_and_call_tool"
               for case in groups[1]):
        raise ValueError("Real JUnit group 2 is missing the web account case")


def validate_recovery_result(path):
    """A green pytest process is insufficient if the recovery case was skipped."""
    try:
        root = ET.parse(path)
    except ET.ParseError as exc:
        raise ValueError("Invalid recovery test result") from exc
    cases = [case for case in root.iter("testcase")
             if case.get("classname") == "tests.test_stage385_pg_recovery_live"
             and case.get("name") == "test_pg_restart_after_successful_upstream_write_never_serves_stale_get"]
    if len(cases) != 1 or any(cases[0].find(tag) is not None for tag in ("skipped", "failure", "error")):
        raise ValueError("Recovery must contain exactly one executed, successful case")


def validate_focus_result(path, nodes):
    """Every requested focused node must execute successfully, without skips."""
    try:
        root = ET.parse(path)
    except ET.ParseError as exc:
        raise ValueError("Invalid focused test result") from exc
    cases = list(root.iter("testcase"))
    if not cases or any(case.find(tag) is not None for case in cases
                        for tag in ("skipped", "failure", "error")):
        raise ValueError("Focused tests were skipped or failed")
    for node in nodes:
        file_name, *test_name = node.split("::")
        module = file_name.removesuffix(".py").replace("/", ".")
        if not any(case.get("classname") == module and
                   (not test_name or case.get("name", "").startswith(test_name[-1]))
                   for case in cases):
            raise ValueError("Requested focused test did not execute")


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
            try:
                if stopped:
                    owned_container(pg_id, project)
                    subprocess.run([*compose, "up", "-d", "--wait", "pg"], check=True,
                                   stdout=log, stderr=log)
                    (hook / "restored").touch()
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
