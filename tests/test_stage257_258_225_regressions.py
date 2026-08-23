"""Regression coverage for stages 257, 258 and 225.3."""

from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from tools.medical_card import _medical_card_update_error
from vetmanager_client import VetmanagerError


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_manual_token_copy_names_the_result_and_wildcard_is_the_default() -> None:
    text = (REPO_ROOT / "web_html.py").read_text(encoding="utf-8")
    route = (REPO_ROOT / "web_routes_account.py").read_text(encoding="utf-8")

    assert "Выпустить Bearer-токен вручную" in text
    assert "confirm_wildcard_ip" not in text
    assert "confirm_wildcard_ip" not in route
    assert 'if not ip_mask_raw:\n            ip_mask_raw = "*.*.*.*"' in route


def test_diagnoses_type_error_is_a_clear_non_successful_tool_error() -> None:
    upstream = VetmanagerError(
        "Upstream API error (HTTP 500) — Cannot assign int to property "
        "Entity\\MedicalCard\\Diagnoses::$diagnoses of type array",
        status_code=500,
    )

    error = _medical_card_update_error(upstream)

    assert isinstance(error, ToolError)
    assert "did not update" in str(error)
    assert "not saved" in str(error)
    assert "do not clear" in str(error)


@pytest.mark.parametrize(
    "error",
    [
        VetmanagerError("Upstream API error (HTTP 500) — another failure", status_code=500),
        VetmanagerError("Cannot assign int to property Entity\\MedicalCard\\Diagnoses::$diagnoses of type array", status_code=400),
    ],
)
def test_only_confirmed_diagnoses_500_is_mapped(error: VetmanagerError) -> None:
    assert _medical_card_update_error(error) is None
