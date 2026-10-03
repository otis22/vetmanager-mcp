"""Stage 364: public resolution advice stays within the agent contract."""

import re

import pytest

from landing_page import render_landing_page
from placeholder_resolution_guidance import AGENT_RESOLUTION_GUIDANCE


def _resolution_answer(html: str) -> str:
    start = html.index("Как устроена подстановка значений (резолв)?")
    return html[start:html.index("</details>", start)]


def _assert_faq_contract(html: str) -> None:
    answer = _resolution_answer(html)
    assert "REST-ключ Vetmanager или отдельное подключение без обезличивания" in html
    assert "с REST-ключом Vetmanager — прямым GET-запросом к REST API Vetmanager" in answer
    assert "с отдельным подключением без обезличивания — через инструменты подключения" in answer
    assert all(name in answer for name in ("get_client_by_id", "get_user_by_id", "get_pet_by_id"))

    allowed = re.search(r"только (GET /rest/api/[^;]+); не принимайте", AGENT_RESOLUTION_GUIDANCE)
    assert allowed is not None
    entities = set(re.findall(r"GET /rest/api/(\w+)/\{ID\}", allowed.group(1)))
    assert entities == {"client", "user"}
    assert "Иные сущности и поля оставляйте плейсхолдерами" in AGENT_RESOLUTION_GUIDANCE
    assert "подставляйте лишь подтверждённые поля имени last_name, first_name, middle_name" in AGENT_RESOLUTION_GUIDANCE
    assert "Помощник может подготовить скрипт только для подстановки имён клиентов и сотрудников; этот скрипт не охватывает метки питомцев и контактов." in answer
    assert "Помощник может подготовить такой скрипт по этому описанию." not in answer


def test_faq_matches_key_auth_and_agent_guidance() -> None:
    _assert_faq_contract(render_landing_page())


def test_guard_rejects_return_to_unscoped_script_promise() -> None:
    html = render_landing_page()
    regressed = html.replace(
        "Помощник может подготовить скрипт только для подстановки имён клиентов и сотрудников; этот скрипт не охватывает метки питомцев и контактов.",
        "Помощник может подготовить такой скрипт по этому описанию.",
    )
    assert regressed != html
    with pytest.raises(AssertionError):
        _assert_faq_contract(regressed)


def test_guard_rejects_mcp_tools_for_rest_key() -> None:
    html = render_landing_page()
    regressed = html.replace(
        "с REST-ключом Vetmanager — прямым GET-запросом к REST API Vetmanager; с отдельным подключением без обезличивания — через инструменты подключения ",
        "через инструменты подключения ",
    )
    assert regressed != html
    with pytest.raises(AssertionError):
        _assert_faq_contract(regressed)
