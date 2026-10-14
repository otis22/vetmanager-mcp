"""Resource acceptance uses real three-slot evidence and fails on missing data."""

import copy
import json
from pathlib import Path

from scripts.check_stage385_resource_gate import validate


SAMPLE = Path(__file__).parent / "fixtures" / "stage385_resource_gate_sample.json"


def test_real_resource_sample_passes():
    assert validate(json.loads(SAMPLE.read_text())) == []


def test_resource_guard_rejects_oom_memory_and_missing_prometheus():
    sample = json.loads(SAMPLE.read_text())
    broken = copy.deepcopy(sample)
    broken["after"]["cgroup"][1]["oom"] = 1
    assert validate(broken)
    broken = copy.deepcopy(sample)
    broken["after"]["cgroup"][0]["rss_peak_bytes"] = int(.8 * 2 * 1024**3)
    broken["rss_formula_bytes"] = sum(
        slot["rss_peak_bytes"] for slot in broken["after"]["cgroup"]) + 512 * 1024**2
    assert validate(broken)
    broken = copy.deepcopy(sample)
    broken["after"]["head_series"] = None
    assert validate(broken)
    broken = copy.deepcopy(sample)
    broken["after"]["cgroup"][0]["cpu_limit"] = 2
    assert validate(broken)


def test_resource_guard_rejects_incomplete_or_under_counted_run():
    sample = json.loads(SAMPLE.read_text())
    broken = copy.deepcopy(sample)
    broken["calls"] = 199
    assert validate(broken)
    broken = copy.deepcopy(sample)
    broken["metric_delta"] = 199
    assert validate(broken)
    broken = copy.deepcopy(sample)
    broken["after"]["pg_sessions"] = 41
    assert validate(broken)
