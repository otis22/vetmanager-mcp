"""Stage 330 — clinical numbers must not be mistaken for phone numbers."""

import error_tracking
import pytest
from pathlib import Path

from agent_feedback_service import sanitize_text as sanitize_feedback_text
from depersonalization import REDACTED_PHONE, sanitize_tool_result


def _free_text(text: str) -> str:
    return sanitize_tool_result({"description": text})["description"]


@pytest.mark.parametrize(
    "clinical_text",
    [
        "Диурез: 50 45 60 55 40 мл.",
        '<polyline points="10.5,20.3 30.1,40.2"/>',
        '<div style="left:120px;top:45px">график</div>',
    ],
)
def test_stage330_report74_clinical_numbers_survive_in_both_sanitizers(clinical_text: str) -> None:
    """The #74 synthetic corpus is a guard against the original broad regex."""
    assert _free_text(clinical_text) == clinical_text
    assert error_tracking._redact_exception_value(clinical_text) == clinical_text


@pytest.mark.parametrize(
    "phone",
    [
        "+7 (999) 123-45-67",
        "8 999 123 45 67",
        "89991234567",
        "+123456789012",
        "+380 44 123 45 67",
        "999-123-45-67",
        "8 (918) 414-01-11",
        "8-918-414-01-11",
        "+7(999)123-45-67", "8(999)123-45-67", "+7 (999) 1234567", "8 999 1234567", "+7 9991234567",
    ],
)
def test_stage330_existing_phone_corpus_stays_redacted(phone: str) -> None:
    assert _free_text(f"Телефон: {phone}") == f"Телефон: {REDACTED_PHONE}"
    assert error_tracking._redact_exception_value(f"phone={phone}") == "phone=[Filtered]"


def test_stage330_unit_context_is_local_to_its_number() -> None:
    text = "тел. 89991234567, вес 5 кг"

    assert _free_text(text) == f"тел. {REDACTED_PHONE}, вес 5 кг"
    assert error_tracking._redact_exception_value(text) == "тел. [Filtered], вес 5 кг"


@pytest.mark.parametrize(
    "contact_text",
    [
        "89991234567 г. Москва",
        "тел. 89991234567 г москва",
        "89991234567 г",
        "перезвонить 89991234567 после 14:30",
        "89991234567 10:00-18:00",
        "звоните 89991234567 до 20:00",
    ],
)
def test_stage330_context_never_becomes_contact_phone_bypass(contact_text: str) -> None:
    assert REDACTED_PHONE in _free_text(contact_text)
    assert "[Filtered]" in error_tracking._redact_exception_value(contact_text)


@pytest.mark.parametrize("text", ["тел. № 89991234567", "Тел.№ +7 999 123-45-67", "контакт #89991234567"])
def test_stage330_contact_marker_beats_identifier_context(text: str) -> None:
    assert REDACTED_PHONE in _free_text(text)


@pytest.mark.parametrize("identifier", ["643094100123456", "4600051000057"])
def test_stage330_unprefixed_microchip_and_ean_survive(identifier: str) -> None:
    assert _free_text(identifier) == identifier
    assert error_tracking._redact_exception_value(identifier) == identifier


@pytest.mark.parametrize("value", ["счёт № 81234567", "документ 8202609181"])
def test_stage330_short_numbers_starting_with_eight_are_not_phones(value: str) -> None:
    assert _free_text(value) == value


def test_stage330_eight_prefix_requires_a_separator() -> None:
    assert REDACTED_PHONE in _free_text("8 9991234567")


@pytest.mark.parametrize(
    "clinical_text",
    ["150 45 60 55 40", "Диурез: 120 45 60 мл", "150 120 45 60 мл", "Показатели: 150 120 45 60"],
)
def test_stage330_space_separated_short_groups_are_not_phones(clinical_text: str) -> None:
    assert _free_text(clinical_text) == clinical_text
    assert error_tracking._redact_exception_value(clinical_text) == clinical_text
    assert sanitize_feedback_text(clinical_text, limit=500) == clinical_text


@pytest.mark.parametrize("phone", ["+7 4852 45 67 89", "123-45-67", "тел. 123 45 67"])
def test_stage330_legacy_short_group_forms_remain_redacted(phone: str) -> None:
    assert REDACTED_PHONE in _free_text(phone)
    assert "[Filtered]" in error_tracking._redact_exception_value(phone)
    assert "[REDACTED]" in (sanitize_feedback_text(phone, limit=500) or "")


def test_stage330_error_tracking_uses_the_shared_lightweight_matcher() -> None:
    source = "\n".join(
        Path(module.__file__).read_text(encoding="utf-8")
        for module in (error_tracking, __import__("agent_feedback_service"))
    )

    assert "from phone_redaction import" in source
    assert "_PHONE_RE = re.compile" not in source
    assert "_PHONE_LIKE_RE = re.compile" not in Path(
        __import__("depersonalization").__file__
    ).read_text(encoding="utf-8")
