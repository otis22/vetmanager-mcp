from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_dependency_exports_match_one_frozen_lock():
    subprocess.run(["uv", "lock", "--check", "--offline"], cwd=ROOT,
                   capture_output=True, text=True, check=True)
    for flags, output in ((("--no-dev",), "requirements/production.txt"),
                          (("--group", "dev"), "requirements/test.txt"),
                          (("--only-group", "audit"), "requirements/audit.txt")):
        result = subprocess.run(
            ["uv", "export", "--frozen", "--no-emit-project", "--no-header",
             "--no-annotate", "--python", "3.12", *flags],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        assert (ROOT / output).read_text() == result.stdout
        assert "--hash=sha256:" in result.stdout


def test_docker_installs_only_hash_exports():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "pip install --require-hashes" in dockerfile
    assert 'pip install --no-cache-dir "anyio' not in dockerfile
