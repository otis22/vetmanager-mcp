"""Stage 254.3: a documentation-only commit must not redeploy production.

The gate filtered the output of `git diff --name-only`. That command escapes
non-ASCII paths into octal and wraps them in quotes, and every PRD in this
repository is named in Russian — so a commit that added one looked like a
commit that touched the image, and prod was recreated for a text change.

Two halves are tested separately, because the defect lives in the seam:
the decision (this script, fed NUL-separated paths) and the way the paths are
produced (the workflow's git invocation, asserted as text — the test container
has no git, so an end-to-end run would silently skip in CI).
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "deploy_scope_check.sh"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-prod.yml"

RUSSIAN_PRD = "PRD/этап-241-дедупликация-событий.md"
ESCAPED_RUSSIAN_PRD = r'"PRD/\321\215\321\202\320\260\320\277-241.md"'


def _decide(*paths: str) -> str:
    payload = "".join(path + "\0" for path in paths).encode("utf-8")
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        input=payload,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8").strip()


def test_a_new_russian_named_prd_is_still_documentation():
    assert _decide(RUSSIAN_PRD, "Roadmap.md", "AssumptionLog.md") == "false"


def test_an_ascii_named_document_is_documentation_too():
    assert _decide("Roadmap.md") == "false"


def test_code_is_deployed():
    assert _decide("server.py") == "true"


def test_documentation_next_to_code_is_still_a_deploy():
    assert _decide(RUSSIAN_PRD, "server.py") == "true"


def test_a_russian_named_file_outside_the_document_paths_is_a_deploy():
    assert _decide("скрипты/деплой.sh") == "true"


def test_an_empty_range_deploys_rather_than_silently_skipping():
    assert _decide() == "true"


def test_the_escaped_form_is_not_recognised_as_documentation():
    # Not a wish, a warning: if the producer ever goes back to escaping paths,
    # this is what the decision sees, and it deploys. The guard against that is
    # the workflow assertion below.
    assert _decide(ESCAPED_RUSSIAN_PRD) == "true"


def test_the_workflow_produces_raw_paths_and_asks_the_script():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "scripts/deploy_scope_check.sh" in workflow
    assert "git -c core.quotepath=false diff --name-only -z" in workflow
    # The escaping trap lived in exactly this call; it must not come back.
    assert 'git diff --name-only "${base_sha}"' not in workflow


def test_the_decision_drains_its_input_instead_of_closing_the_pipe():
    # Review finding 28.08.2026: exiting on the first code path closes the pipe
    # under a still-writing `git diff`, which surfaces as exit 141 the moment
    # the workflow step gains `pipefail` — and only for commits that must
    # deploy. The write is far larger than a pipe buffer, so a reader that
    # leaves early is caught here rather than in CI.
    # ~400 KB — several pipe buffers, but small enough that `read -d ''`
    # (one syscall per byte) stays fast on a loaded runner.
    paths = ["server.py"] + [f"docs/page-{index}.md" for index in range(20_000)]
    payload = "".join(path + "\0" for path in paths).encode("utf-8")
    with subprocess.Popen(
        ["bash", str(SCRIPT_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(payload)
            process.stdin.flush()
        except BrokenPipeError:
            process.kill()
            raise AssertionError(
                "the decision closed the pipe while the producer was still writing"
            ) from None
        process.stdin.close()
        stdout = process.stdout.read()
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            # Without this the timeout would propagate into `Popen.__exit__`,
            # which waits on the child with no bound: a hung suite instead of
            # a failed test.
            process.kill()
            raise

    assert process.returncode == 0
    assert stdout.decode("utf-8").strip() == "true"
