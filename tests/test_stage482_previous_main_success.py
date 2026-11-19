"""Stage 482: previous Tests success must survive GitHub's status-filter mismatch."""

from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.ci_scope import previous_main_success


BEFORE = "06c9c550d1f6bac1b6c6073f96a6e1911d4b9632"
RUN = {
    "id": 44472826301,
    "head_sha": BEFORE,
    "event": "push",
    "head_branch": "main",
    "path": ".github/workflows/test.yml",
    "status": "completed",
    "conclusion": "success",
}


class API:
    def __init__(self, runs):
        self.runs = runs
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        query = parse_qs(urlsplit(path).query)
        # Public GitHub API on 20 Nov: this run is absent for any status filter.
        if "status" in query:
            return {"total_count": 0, "workflow_runs": []}
        return self.runs


def test_historical_success_uses_unfiltered_query():
    api = API({"total_count": 1, "workflow_runs": [RUN]})
    assert previous_main_success(api, BEFORE)
    assert len(api.paths) == 1
    assert urlsplit(api.paths[0]).path == "/actions/workflows/test.yml/runs"
    assert parse_qs(urlsplit(api.paths[0]).query) == {
        "event": ["push"], "head_sha": [BEFORE], "per_page": ["100"]
    }


@pytest.mark.parametrize("change", [
    {"head_sha": "a" * 40}, {"event": "pull_request"},
    {"head_branch": "feature"}, {"path": ".github/workflows/other.yml"},
    {"status": "in_progress"}, {"conclusion": "failure"},
])
def test_untrusted_run_cannot_skip_product(change):
    api = API({"total_count": 1, "workflow_runs": [{**RUN, **change}]})
    assert not previous_main_success(api, BEFORE)


@pytest.mark.parametrize("payload", [
    {"total_count": 0, "workflow_runs": []},
    {"total_count": 1, "workflow_runs": []},
    {"total_count": 1, "workflow_runs": None},
    {"total_count": 1, "workflow_runs": [None]},
])
def test_missing_or_malformed_evidence_cannot_skip_product(payload):
    api = API(payload)
    assert not previous_main_success(api, BEFORE)


def test_api_error_cannot_skip_product():
    class BrokenAPI:
        def get(self, path):
            raise OSError("GitHub unavailable")

    with pytest.raises(OSError):
        previous_main_success(BrokenAPI(), BEFORE)
