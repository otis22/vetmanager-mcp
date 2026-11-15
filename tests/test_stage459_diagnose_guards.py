"""Regression checks for stage 459 real-suite evidence and test fixtures."""

import ast
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pytest

from scripts.test_recovery_supervisor import validate_real_junit_results
from scripts.run_isolated_test_suite import create_private_auth_file
from tests import test_stage420_live as report_live


def _junit(path, cases):
    root = ET.Element("testsuite", tests=str(len(cases)))
    for module, name, outcome in cases:
        case = ET.SubElement(root, "testcase", classname=module, name=name)
        if outcome:
            ET.SubElement(case, outcome)
    ET.ElementTree(root).write(path)


_EXPORT = ("tests.test_stage276_live_export_download",
           "test_real_export_is_downloaded_cleaned_and_served_by_us", None)
_PAGES = ("tests.test_stage389_live", "test_stage389_two_live_pages", None)
_WEB = ("tests.test_e2e_real", "test_real_web_account_can_issue_bearer_and_call_tool", None)


@pytest.mark.parametrize("variant", ["valid", "missing-xml", "skip", "failure",
                                     "missing-node", "missing-collected-case"])
def test_real_junit_requires_two_clean_groups_and_mandatory_nodes(tmp_path, variant):
    first, second = tmp_path / "one.xml", tmp_path / "two.xml"
    cases = [_EXPORT, _PAGES]
    if variant == "skip":
        cases[0] = (*_EXPORT[:2], "skipped")
    elif variant == "failure":
        cases[0] = (*_EXPORT[:2], "failure")
    elif variant == "missing-node":
        cases.pop()
    _junit(first, cases)
    if variant != "missing-xml":
        _junit(second, [_WEB])
    first_outcome, second_outcome = tmp_path / "one.json", tmp_path / "two.json"
    first_outcome.write_text(json.dumps({"collected": len(cases) +
                                          (1 if variant == "missing-collected-case" else 0)}))
    second_outcome.write_text(json.dumps({"collected": 1}))
    if variant == "valid":
        validate_real_junit_results(first, second, first_outcome, second_outcome)
    else:
        with pytest.raises((OSError, ValueError)):
            validate_real_junit_results(first, second, first_outcome, second_outcome)


def test_seed_intents_use_unique_marker_and_preserve_it(monkeypatch):
    intents = []
    next_id = iter(range(100, 104))

    def fake_call(_client, tool, args, _request_id):
        if tool == "create_report_ai_job":
            intents.append(args["intent_text"])
            return 200, {"structuredContent": {"data": {"job": {
                "id": next(next_id), "status": "ready_to_save"}}}}
        assert tool == "save_report_ai_job_as_report"
        return 200, {"structuredContent": {"data": {
            "report_id": 5, "next_action": {"call": {"tool": "get_report_ai_job_data"}}}}}

    monkeypatch.setattr(report_live, "_call", fake_call)
    first = report_live._seed_matched_report(None, year=2003, request_id=1)[1]
    second = report_live._seed_matched_report(None, year=2003, request_id=1)[1]
    assert intents == [first, second]
    markers = [re.search(r"Метка проверки ([0-9a-f]{32}) не является фильтром данных", text)
               for text in intents]
    assert all(markers)
    assert markers[0].group(1) != markers[1].group(1)
    assert markers[0].group(1) in first[:-1] + "!"


def test_web_happy_path_client_has_bounded_60_second_timeout():
    tree = ast.parse(Path("tests/test_e2e_real.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "test_real_web_account_can_issue_bearer_and_call_tool")
    clients = [node for node in ast.walk(function) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr == "Client"
               and isinstance(node.func.value, ast.Name) and node.func.value.id == "httpx"]
    assert len(clients) == 1
    timeout = next((keyword.value for keyword in clients[0].keywords
                    if keyword.arg == "timeout"), None)
    assert isinstance(timeout, ast.Constant) and timeout.value == 60


def test_auth_file_creation_refuses_preexisting_permissive_file(tmp_path):
    auth = tmp_path / "auth.env"
    auth.write_text("sentinel")
    auth.chmod(0o644)
    with pytest.raises(FileExistsError):
        create_private_auth_file(auth)
    assert auth.read_text() == "sentinel"
    assert auth.stat().st_mode & 0o777 == 0o644


def test_auth_file_creation_sets_private_mode(tmp_path):
    auth = tmp_path / "auth.env"
    create_private_auth_file(auth)
    assert auth.stat().st_mode & 0o777 == 0o600
