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
    data_calls = []
    next_id = iter(range(100, 104))
    current_id = None

    def fake_call(_client, tool, args, _request_id):
        nonlocal current_id
        if tool == "create_report_ai_job":
            intents.append(args["intent_text"])
            if len(intents) % 2 == 0:
                return 200, {"structuredContent": {"data": {
                    "is_deduplicated": True, "job": {"id": current_id,
                                                   "status": "recognizing"}}}}
            current_id = next(next_id)
            return 200, {"structuredContent": {"data": {"job": {
                "id": current_id, "status": "recognizing"}}}}
        if tool == "get_report_ai_job":
            return 200, {"structuredContent": {"data": {"job": {
                "id": current_id, "status": "ready_to_save"}}}}
        if tool == "get_report_ai_job_data":
            data_calls.append(args["job_id"])
            return 200, {"structuredContent": {"data": {"rows": [],
                "next_action": {"call": {"tool": "rate_report_ai_job"}}}}}
        assert tool == "save_report_ai_job_as_report"
        return 200, {"structuredContent": {"data": {
            "report_id": 5, "next_action": {"call": {"tool": "get_report_ai_job_data"}}}}}

    monkeypatch.setattr(report_live, "_call", fake_call)
    first = report_live._seed_matched_report(None, year=2003, request_id=1)[1]
    second = report_live._seed_matched_report(None, year=2003, request_id=1)[1]
    assert intents == [first, first, second, second]
    assert data_calls == [100, 101]
    markers = [re.search(r"Метка проверки ([0-9a-f]{32}) не является фильтром данных", text)
               for text in (first, second)]
    assert all(markers)
    assert markers[0].group(1) != markers[1].group(1)
    assert markers[0].group(1) in first[:-1] + "!"


@pytest.mark.parametrize("bad_duplicate", ["flag", "job_id"])
def test_stage420_exact_repeat_requires_same_job_and_dedup_flag(monkeypatch, bad_duplicate):
    calls = 0

    def fake_call(_client, tool, _args, _request_id):
        nonlocal calls
        assert tool == "create_report_ai_job"
        calls += 1
        data = {"job": {"id": 41 if calls == 1 or bad_duplicate == "flag" else 42,
                        "status": "recognizing"}}
        if calls == 2:
            data["is_deduplicated"] = bad_duplicate != "flag"
        return 200, {"structuredContent": {"data": data}}

    monkeypatch.setattr(report_live, "_call", fake_call)
    with pytest.raises(AssertionError, match="exact repeated intent"):
        report_live._seed_matched_report(None, year=2003, request_id=1)
    assert calls == 2


def test_stage420_terminal_seed_is_not_used_for_active_job_dedup(monkeypatch):
    intents = []

    def fake_call(_client, tool, args, _request_id):
        if tool == "create_report_ai_job":
            intents.append(args["intent_text"])
            if len(intents) == 1:
                return 200, {"structuredContent": {"data": {"job": {
                    "id": 40, "status": "existing_report_matched"}}}}
            return 200, {"structuredContent": {"data": {
                "is_deduplicated": len(intents) == 3,
                "job": {"id": 41, "status": "recognizing"}}}}
        if tool == "get_report_ai_job":
            return 200, {"structuredContent": {"data": {"job": {
                "id": 41, "status": "ready_to_save"}}}}
        if tool == "get_report_ai_job_data":
            return 200, {"structuredContent": {"data": {"rows": [],
                "next_action": {"call": {"tool": "rate_report_ai_job"}}}}}
        assert tool == "save_report_ai_job_as_report"
        return 200, {"structuredContent": {"data": {
            "report_id": 5, "next_action": {"call": {"tool": "get_report_ai_job_data"}}}}}

    monkeypatch.setattr(report_live, "_call", fake_call)
    report_live._seed_matched_report(None, year=2003, request_id=1)
    assert len(intents) == 3
    assert intents[0] != intents[1] == intents[2]


def test_stage420_exact_repeat_is_checked_once_across_seed_years(monkeypatch):
    intents = []
    current_id = 0

    def fake_call(_client, tool, args, _request_id):
        nonlocal current_id
        if tool == "create_report_ai_job":
            intents.append(args["intent_text"])
            if len(intents) == 1:
                current_id = 41
                return 200, {"structuredContent": {"data": {"job": {
                    "id": current_id, "status": "recognizing"}}}}
            if len(intents) == 2:
                return 200, {"structuredContent": {"data": {
                    "is_deduplicated": True, "job": {"id": current_id,
                                                     "status": "recognizing"}}}}
            current_id = 42
            return 200, {"structuredContent": {"data": {"job": {
                "id": current_id, "status": "recognizing"}}}}
        if tool == "get_report_ai_job":
            status = "existing_report_matched" if current_id == 41 else "ready_to_save"
            return 200, {"structuredContent": {"data": {"job": {
                "id": current_id, "status": status}}}}
        if tool == "save_report_ai_job_as_report":
            return 200, {"structuredContent": {"data": {
                "report_id": 5, "next_action": {"call": {"tool": "get_report_ai_job_data"}}}}}
        assert tool == "get_report_ai_job_data"
        return 200, {"structuredContent": {"data": {"rows": [],
            "next_action": {"call": {"tool": "rate_report_ai_job"}}}}}

    monkeypatch.setattr(report_live, "_call", fake_call)
    report_live._seed_matched_report(None, year=2003, request_id=1)
    assert len(intents) == 3
    assert intents[0] == intents[1] != intents[2]


def test_stage420_distinct_recognition_from_saved_evidence_is_not_false_dedup_failure(monkeypatch):
    """Sanitized 479 evidence: count versus count of admission ID."""
    seed = {"tables": ["admission"], "fields": ["Количество"],
            "filters": ["same date interval"], "group_by": ["month"], "order_by": []}
    repeat = {**seed, "fields": ["Количество(ID записи)"]}
    calls = []

    def fake_call(_client, tool, _args, _request_id):
        calls.append(tool)
        return 200, {"structuredContent": {"data": {"job": {
            "id": 2, "status": "ready_to_save", "recognized": repeat,
            "next_action": {"call": {"tool": "save_report_ai_job_as_report"}},
        }}}}

    monkeypatch.setattr(report_live, "_call", fake_call)
    report_live._check_repeated_intent_dedup(None, seed_report_id=1,
        seed_intent="request.", request_id=1, label="EVIDENCE", seed_recognized=seed)
    assert calls == ["create_report_ai_job"]


@pytest.mark.parametrize("different_shape", [True, False])
def test_stage420_existing_match_accepts_older_report_with_readable_data(monkeypatch, different_shape):
    """The older match can differ in structure if its data is readable."""
    recognized = {"tables": ["admission"], "fields": ["count"],
                  "filters": ["same interval"], "group_by": ["month"],
                  "order_by": []}
    calls = []

    def fake_call(_client, tool, _args, _request_id):
        calls.append(tool)
        if tool == "create_report_ai_job":
            return 200, {"structuredContent": {"data": {"job": {
                "id": 2, "status": "existing_report_matched", "report_id": 99,
                "recognized": {**recognized, "fields": ["sum"]} if different_shape else recognized,
                "next_action": {"call": {"tool": "get_report_ai_job_data",
                                         "arguments": {"job_id": 2}},
                                "required_args": ["job_id"]},
            }}}}
        assert tool == "get_report_ai_job_data"
        return 200, {"structuredContent": {"data": {"rows": [], "total": 0,
            "next_action": {"call": {"tool": "rate_report_ai_job"},
                            "required_args": ["job_id", "score", "intent_text"]}}}}

    monkeypatch.setattr(report_live, "_call", fake_call)
    report_live._check_repeated_intent_dedup(None, seed_report_id=1,
        seed_intent="request.", request_id=1, label="EVIDENCE", seed_recognized=recognized)
    assert calls == ["create_report_ai_job", "get_report_ai_job_data"]


@pytest.mark.parametrize("broken", ["action", "rows", "total", "rate_action"])
def test_stage420_matched_report_requires_next_action_and_readable_data(monkeypatch, broken):
    job = {"id": 2, "status": "existing_report_matched", "report_id": 99,
           "next_action": {"call": {"tool": "get_report_ai_job_data",
                                    "arguments": {"job_id": 2}}, "required_args": ["job_id"]}}
    data = {"rows": [], "total": 0,
            "next_action": {"call": {"tool": "rate_report_ai_job"},
                            "required_args": ["job_id", "score", "intent_text"]}}
    if broken == "action":
        job["next_action"]["call"]["tool"] = "save_report_ai_job_as_report"
    elif broken == "rows":
        data["rows"] = None
    elif broken == "total":
        data["total"] = None
    else:
        data["next_action"]["required_args"] = ["job_id"]

    def fake_call(_client, tool, _args, _request_id):
        result = {"job": job} if tool == "create_report_ai_job" else data
        return 200, {"structuredContent": {"data": result}}

    monkeypatch.setattr(report_live, "_call", fake_call)
    with pytest.raises(AssertionError):
        report_live._check_repeated_intent_dedup(None, seed_report_id=1,
            seed_intent="request.", request_id=1, label="EVIDENCE")


@pytest.mark.parametrize("change", ["equal", "missing_seed", "missing_repeat",
                                   "empty_fields", "null_field", "empty_tables",
                                   "permuted_fields", "permuted_filters"])
def test_stage420_new_report_requires_proven_structural_difference(change):
    seed = {"tables": ["admission"], "fields": ["count", "month"],
            "filters": ["date", "clinic"],
            "group_by": ["month"], "order_by": []}
    repeat = dict(seed)
    if change == "missing_seed":
        seed.pop("fields")
    elif change == "missing_repeat":
        repeat.pop("fields")
    elif change == "empty_fields":
        repeat["fields"] = []
    elif change == "null_field":
        repeat["fields"] = [None]
    elif change == "empty_tables":
        repeat["tables"] = []
    elif change == "permuted_fields":
        repeat["fields"] = list(reversed(seed["fields"]))
    elif change == "permuted_filters":
        repeat["filters"] = list(reversed(seed["filters"]))
    with pytest.raises(AssertionError, match="dedup failed|incomplete"):
        report_live._assert_distinct_recognized_report(seed, repeat)


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
