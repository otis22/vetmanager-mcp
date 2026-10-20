"""Stage 424: all mandatory PostgreSQL regressions run in required CI."""

import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from scripts.check_stage424_postgres_results import REQUIRED_FILES, validate_results


def test_postgres_job_runs_unrestricted_marker_contour_and_result_gate():
    workflow = yaml.safe_load(Path(".github/workflows/test.yml").read_text())
    job = workflow["jobs"]["postgres-activation-telemetry"]
    step = next(step for step in job["steps"] if step.get("name", "").startswith("Run mandatory PostgreSQL"))
    assert not job.get("if")
    assert not step.get("if")
    assert not step.get("continue-on-error")
    tokens = shlex.split(step["run"].replace("\\\n", " "))
    image_index = tokens.index("vetmanager-mcp-test")
    assert tokens[image_index + 1:] == [
        "sh", "-c",
        "pytest -q -m postgres --junitxml=/tmp/stage424-postgres.xml && "
        "python scripts/check_stage424_postgres_results.py /tmp/stage424-postgres.xml",
    ]


def test_all_mandatory_files_are_selected_by_postgres_marker():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "postgres"],
        capture_output=True, text=True, check=True,
    )
    for file in REQUIRED_FILES:
        assert f"tests/{file}.py::" in result.stdout, file


def test_result_gate_rejects_missing_file_and_skip(tmp_path):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for file in sorted(REQUIRED_FILES):
        ET.SubElement(suite, "testcase", classname=f"tests.{file}", name="test_case")
    path = tmp_path / "results.xml"
    ET.ElementTree(root).write(path)
    assert len(validate_results(path)) == len(REQUIRED_FILES)

    suite.remove(suite[-1])
    ET.ElementTree(root).write(path)
    try:
        validate_results(path)
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("Missing mandatory PostgreSQL testcase was accepted")

    case = ET.SubElement(suite, "testcase", classname=f"tests.{sorted(REQUIRED_FILES)[-1]}", name="test_case")
    ET.SubElement(case, "skipped")
    ET.ElementTree(root).write(path)
    try:
        validate_results(path)
    except ValueError as exc:
        assert "did not pass" in str(exc)
    else:
        raise AssertionError("Skipped PostgreSQL testcase was accepted")
