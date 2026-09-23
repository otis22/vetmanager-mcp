"""Stage 342: keep KI-45 and guarded seed updates in sync."""

import json
from argparse import Namespace
from pathlib import Path

import pytest
from sqlalchemy import select

from storage_models import KnownIssue


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "artifacts/known-issues/stage-332"


def test_ki45_seed_uses_applied_stage332_configuration():
    from scripts import seed_known_issues as seed

    issue = next(item for item in seed.SEED_ISSUES if item.slug == "report-export-not-available")
    assert issue.match_rules == json.loads((FIXTURE / "ki45-match-rules.json").read_text())
    assert issue.agent_playbook == json.loads((FIXTURE / "ki45-playbook.json").read_text())
    script = (ROOT / "scripts/apply_stage332_known_issues_prod.sh").read_text()
    assert 'fixture_dir=$repo_dir/artifacts/known-issues/stage-332' in script
    assert '"$fixture_dir/ki45-match-rules.json"' in script
    assert '"$fixture_dir/ki45-playbook.json"' in script
    seed_source = (ROOT / "scripts/seed_known_issues.py").read_text()
    assert '_stage332_config("ki45-match-rules.json")' in seed_source
    assert '_stage332_config("ki45-playbook.json")' in seed_source
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "FROM base AS production\n\nCOPY . ." in dockerfile
    assert not (ROOT / ".dockerignore").exists()


@pytest.mark.asyncio
async def test_triage_serialization_is_unchanged_for_seed(
    sqlite_session_factory_builder, tmp_path, monkeypatch,
):
    from scripts import seed_known_issues as seed

    factory = await sqlite_session_factory_builder(tmp_path / "stage342-serialization.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: factory)
    await seed.seed_known_issues(apply=True)
    async with factory() as session:
        issue = (await session.execute(select(KnownIssue).where(
            KnownIssue.title == next(item.title for item in seed.SEED_ISSUES
                                     if item.slug == "report-export-not-available")
        ))).scalar_one()
        issue.match_rules_json = json.dumps(json.loads(issue.match_rules_json), ensure_ascii=True, sort_keys=True)
        issue.agent_playbook_json = json.dumps(json.loads(issue.agent_playbook_json), ensure_ascii=True, sort_keys=True)
        await session.commit()

    result = await seed.seed_known_issues(apply=False)
    assert result["updated"] == 0


@pytest.mark.asyncio
async def test_apply_requires_exact_per_issue_field_approval_and_is_atomic(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys,
):
    from scripts import seed_known_issues as seed

    factory = await sqlite_session_factory_builder(tmp_path / "stage342-approval.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: factory)
    await seed.seed_known_issues(apply=True)
    items = seed.SEED_ISSUES[:2]
    async with factory() as session:
        for item in items:
            issue = (await session.execute(select(KnownIssue).where(KnownIssue.title == item.title))).scalar_one()
            issue.public_summary = "old summary"
        await session.commit()

    blocked = await seed.seed_known_issues(apply=True)
    assert blocked["status"] == "blocked"
    assert blocked["updated"] == 2
    assert sorted(blocked["changes"]) == sorted(f"{item.slug}:public_summary" for item in items)
    exit_code = await seed._main_async(Namespace(command=None, apply=True, allow_update=[]))
    output = capsys.readouterr().out
    assert exit_code == 2
    assert "would_update=" in output
    assert "old summary" not in output
    partial = await seed.seed_known_issues(
        apply=True, allow_updates=(f"{items[0].slug}:public_summary",)
    )
    assert partial["status"] == "blocked"
    stale_fields = await seed.seed_known_issues(
        apply=True, allow_updates=tuple(f"{item.slug}:priority" for item in items)
    )
    assert stale_fields["status"] == "blocked"
    async with factory() as session:
        for item in items:
            issue = (await session.execute(select(KnownIssue).where(KnownIssue.title == item.title))).scalar_one()
            assert issue.public_summary == "old summary"

    approved = await seed.seed_known_issues(
        apply=True,
        allow_updates=tuple(f"{item.slug}:public_summary" for item in items),
    )
    assert approved["status"] == "ok"
    assert approved["updated"] == 2
    assert (await seed.seed_known_issues(apply=True))["updated"] == 0
