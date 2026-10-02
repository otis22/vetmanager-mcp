"""Stage 355: the model sees placeholders while a person may resolve names locally."""

import re

import pytest

from landing_page import render_landing_page
from prompts import get_report_ai_prompt_helper_text
from server import mcp


def _assert_agent_boundary(text: str) -> None:
    lower = text.lower()
    assert "[client:123:last_name]" in text
    assert "[user:5:doctor_name]" in text
    assert "переменной окружения" in lower
    assert "не запускайте" in lower
    assert "не читайте" in lower
    assert "вне сессии агента" in lower
    assert "человеку" in lower
    assert "не передавайте плейсхолдер" in lower
    assert "get" in lower and "client" in lower and "user" in lower
    assert "first_name" in text and "last_name" in text and "middle_name" in text
    assert "doctor_name" in text
    assert "одобрен" in lower
    assert "сотрудник перед запуском проверяет код" in lower
    assert "не вывод" in lower
    assert "не отправляйте ключ" in lower
    assert "в этом режиме вернёт тот же плейсхолдер" in lower
    assert "разные плейсхолдеры обозначают разных людей" in lower
    assert "такой вызов отклоняется" in lower


def test_server_instructions_deliver_resolution_boundary() -> None:
    _assert_agent_boundary(mcp.instructions or "")


@pytest.mark.asyncio
async def test_prompt_and_report_helper_deliver_boundary() -> None:
    prompt = await mcp.get_prompt("daily_schedule")
    rendered = await prompt.render(arguments={"date": "2026-10-02"})
    body = "\n".join(str(message.content) for message in rendered.messages)
    _assert_agent_boundary(body)
    _assert_agent_boundary(get_report_ai_prompt_helper_text())


@pytest.mark.asyncio
async def test_tool_descriptions_do_not_promise_automatic_resolution() -> None:
    tools = {tool.name: tool.description for tool in await mcp.list_tools()}
    for name in ("get_users", "get_user_by_id", "get_clients", "get_client_by_id", "get_daily_schedule"):
        description = tools[name]
        assert "application resolver" not in description
        assert "resolved by the application" not in description
        assert "клиник" in description.lower()
        assert "плейсхолдер" in description.lower()


def test_landing_faq_explains_private_mode_and_resolution() -> None:
    html = render_landing_page()
    faq = html.split('id="faq"', 1)[1].split("</section>", 1)[0]
    questions = (
        "Безопасно ли это?",
        "Что такое режим без персональных данных?",
        "Как пользователь увидит имена, если помощнику они недоступны?",
        "Как устроена подстановка значений (резолв)?",
        "Как сделать подстановку на примере Telegram-бота?",
        "Что происходит, если подстановка не выполнена?",
    )
    assert all(faq.count(question) == 1 for question in questions)
    assert [faq.index(question) for question in questions] == sorted(faq.index(question) for question in questions)
    assert len(re.findall(r"<details\b", faq)) == 9
    for phrase in (
        "[client:123:last_name]", "[user:5:doctor_name]", "[client:123:cell_phone]",
        "get_client_by_id", "get_user_by_id", "get_pet_by_id", "не более 50 уникальных",
        "не более 10 секунд на одну попытку подстановки.", "ключ 1", "ключ 2", "CSV, Markdown, TXT",
        "Метка остаётся в тексте без изменений",
        "Подставляйте значения только для известных меток.",
        "Подставляйте контактные данные — телефон, адрес электронной почты и почтовый адрес — только для меток, полученных из ответа Vetmanager в этом же запросе",
        "так модель не сможет получить контакты перебором идентификаторов.",
        "Значения обезличенных полей видит только пользователь: в модель они не передаются.",
        "Имена, которые сотрудники вписали в свободный текст, например в заметки медкарты, режим не распознаёт.",
    ):
        assert phrase.lower() in faq.lower()
    assert "Имена подставляются для любых меток" not in faq
    assert "не более 10 секунд на всю подстановку" not in faq
    assert "Персональные данные видит только пользователь, а в модель они не попадают ни на одном этапе." not in faq
    assert 'id="privacy-two-keys"' not in html
    assert "Как человек видит имена, а модель — нет" not in html
    assert "privacy-keys-card" not in html
    assert not re.search(r"(?:vm_st_|(?:api[_ -]?key|rest[_ -]?key)\s*[=:]\s*[\"']?\w{8,})", faq, re.I)
    assert not re.search(r"(?:передайте|пришлите|вставьте).{0,40}ключ.{0,25}(?:модел|чат|агент)", faq, re.I)


def test_guidance_has_no_key_literal_or_instruction_to_share_key() -> None:
    text = "\n".join((mcp.instructions or "", get_report_ai_prompt_helper_text()))
    assert not re.search(r"(?:vm_st_|(?:api[_ -]?key|rest[_ -]?key)\s*[=:]\s*[\"']?\w{8,})", text, re.I)
    assert not re.search(r"(?:передайте|пришлите|вставьте).{0,40}ключ.{0,25}(?:модел|чат|агент)", text, re.I)
