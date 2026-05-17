from __future__ import annotations

from pathlib import Path
import hashlib

import scripts.check_stage165_inventory_privacy as check_stage165


def test_stage165_inventory_privacy_checker_accepts_current_inventory(monkeypatch) -> None:
    assert check_stage165.TARGET.exists()
    monkeypatch.setattr(check_stage165.stage163, "find_matching_locations", lambda *_args: [])
    assert check_stage165.main() == 0


def test_stage165_inventory_privacy_checker_flags_common_pii_shapes() -> None:
    text = "\n".join(
        [
            "token eyJabc.eyJdef123.sigxyz",
            "mail someone@gmail.com",
            "phone +7 999 123 45 67",
            "chat_id 1234567",
            "улица Ленина",
            "api_key=abc_def-ghi+jkl/mno=pqr",
            '"secret": "abc_def-ghi+jkl/mno=pqr"',
            "0123456789abcdef0123456789abcdef01234567",
        ]
    )

    problem_kinds = {kind for kind, _ in check_stage165.find_generic_privacy_problems(text)}

    assert {
        "jwt-like",
        "email",
        "phone-like",
        "chat-id-like",
        "address-like",
        "secret-assignment-like",
        "long-token",
    }.issubset(problem_kinds)


def test_stage165_inventory_privacy_checker_allows_required_evidence_identifiers() -> None:
    source_snapshot = "commit:4f309031cf0023bfc68b3c2516746b9d06226e60"
    source_path = Path("artifacts/security/stage-165-critical-findings-inventory.md").as_posix()
    text = f"{source_snapshot}\n{source_path}\nS165-stage164-openapi-pii-examples\n"

    assert check_stage165.find_generic_privacy_problems(text) == []


def test_stage165_inventory_privacy_checker_flags_redacted_email_at_real_domain() -> None:
    problems = check_stage165.find_generic_privacy_problems("email redacted@gmail.com")

    assert ("email", "redacted@gmail.com") in problems


def test_stage165_inventory_privacy_checker_uses_stage163_hash_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    synthetic_secret = "stage165-synthetic-secret"
    synthetic_hash = hashlib.sha256(synthetic_secret.encode("utf-8")).hexdigest()
    target = tmp_path / "stage-165-critical-findings-inventory.md"
    target.write_text(synthetic_secret, encoding="utf-8")

    monkeypatch.setattr(check_stage165, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_stage165, "TARGET", target)
    monkeypatch.setattr(check_stage165.stage163, "HISTORICAL_DEVTR6_API_KEY_SHA256", synthetic_hash)
    monkeypatch.setattr(check_stage165.stage163, "candidate_files", lambda repo_root: [repo_root / target.name])
    monkeypatch.setattr(check_stage165.stage164, "scan_text", lambda *_args: [])

    assert check_stage165.main() == 1
