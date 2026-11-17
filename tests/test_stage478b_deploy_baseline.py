"""Stage 478B-1: paginate deployment evidence and use actual cutover SHA."""

import pytest


DEPLOYED = "a" * 40
RUN_HEAD = "b" * 40


def successful_job(sha=DEPLOYED):
    return {"name": "deploy", "conclusion": "success", "steps": [
        {"name": "Record deployed commit " + sha, "conclusion": "success"}]}


class API:
    def __init__(self, runs, jobs):
        self.runs, self.jobs, self.calls = runs, jobs, []

    def get(self, path):
        from urllib.parse import parse_qs, urlsplit

        self.calls.append(path)
        query = parse_qs(urlsplit(path).query)
        assert query["per_page"] == ["100"]
        page = int(query["page"][0])
        if "/workflows/" in path:
            assert query["branch"] == ["main"] and query["status"] == ["completed"]
            return {"workflow_runs": self.runs[(page - 1) * 100:page * 100]}
        run_id = int(path.split("/runs/")[1].split("/")[0])
        return {"jobs": self.jobs[run_id][(page - 1) * 100:page * 100]}


def test_more_than_100_cancelled_ci_only_runs_use_actual_deployed_sha():
    from scripts.deploy_baseline import last_deployed_sha

    runs = [{"id": i, "head_sha": RUN_HEAD} for i in range(1, 103)]
    jobs = {i: [{"name": "deploy", "conclusion": "skipped"}] for i in range(1, 102)}
    jobs[102] = [successful_job()]
    api = API(runs, jobs)
    assert last_deployed_sha(api) == DEPLOYED
    assert any("page=2" in path for path in api.calls if "/workflows/" in path)


def test_jobs_pagination_finds_deploy_after_first_page():
    from scripts.deploy_baseline import last_deployed_sha

    api = API([{"id": 1, "head_sha": RUN_HEAD}], {1: [
        {"name": "other", "conclusion": "success"} for _ in range(100)] + [successful_job()]})
    assert last_deployed_sha(api) == DEPLOYED
    assert any("/runs/1/jobs" in p and "page=2" in p for p in api.calls)


@pytest.mark.parametrize("steps", [[], [{"name": "Record deployed commit bad", "conclusion": "success"}],
                                   [{"name": "Record deployed commit " + DEPLOYED, "conclusion": "failure"}],
                                   successful_job()["steps"] * 2])
def test_missing_invalid_or_ambiguous_marker_does_not_use_older_baseline(steps):
    from scripts.deploy_baseline import last_deployed_sha

    api = API([{"id": 1}, {"id": 2}], {
        1: [{"name": "deploy", "conclusion": "success", "steps": steps}],
        2: [successful_job()],
    })
    assert last_deployed_sha(api) == ""
    assert not any("/runs/2/jobs" in p for p in api.calls)


def test_absent_baseline_is_not_guessed():
    from scripts.deploy_baseline import last_deployed_sha

    assert last_deployed_sha(API([], {})) == ""


def test_api_failure_is_safe_cli_fallback(monkeypatch, capsys):
    from scripts import deploy_baseline

    class BrokenAPI:
        def __init__(self, *args):
            pass

        def get(self, path):
            raise OSError("synthetic failure")

    monkeypatch.setenv("GITHUB_REPOSITORY", "synthetic/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic")
    monkeypatch.setattr(deploy_baseline, "GitHub", BrokenAPI)
    assert deploy_baseline.main() == 1
    assert not capsys.readouterr().out.strip()
