"""Stage 413: the rendered Report AI prompt leads with the job journey."""

import pytest

from server import mcp


@pytest.fixture
async def helper_text():
    prompt = await mcp.get_prompt("report_ai_prompt_helper")
    rendered = await prompt.render(arguments={})
    return "\n".join(message.content.text for message in rendered.messages)


def test_short_core_and_intent_precede_runtime_appendix(helper_text):
    assert helper_text.startswith("# Report AI prompt helper")
    assert helper_text.index("## Короткий маршрут") < helper_text.index("## Как сформулировать `intent_text`")
    assert helper_text.index("## Как сформулировать `intent_text`") < helper_text.index("## Приложение: доступ и плейсхолдеры")
    assert helper_text.index("create_report_ai_job") < helper_text.index("[client:123:last_name]")
    assert helper_text.index("## Приложение: доступ и плейсхолдеры") > helper_text.index("## Data and export")
    assert "Do not ask for a clinic domain or API key" in helper_text
    assert "Не отправляйте ключ в чат" in helper_text


def test_canonical_route_and_failed_job_branch(helper_text):
    core = helper_text.split("## Короткий маршрут", 1)[1].split("## Как сформулировать", 1)[0]
    assert all(name in core for name in (
        "create_report_ai_job", "get_report_ai_job", "get_report_ai_job_data", "rate_report_ai_job"
    ))
    assert core.index("create_report_ai_job") < core.index("get_report_ai_job") < core.index("get_report_ai_job_data") < core.index("rate_report_ai_job")
    assert "get_report_ai_job(job_id=job_id, wait_seconds=30)" in core
    assert "get_report_ai_job(wait_seconds=30)" not in helper_text
    assert "failed" in core and "score=1" in core and "job_id" in core
    assert "без job_id" in core
    assert "добровольн" not in helper_text.lower()
    assert "voluntary" not in helper_text.lower()
    assert "только подготовленный" not in helper_text.lower()


def test_rating_scale_and_argument_contract(helper_text):
    for fragment in (
        "rate_report_ai_job(job_id, score, intent_text)",
        "`intent_text` и `score`",
        "обязательны; `comment` необязателен",
        "1 = отчёт даже не построился",
        "2 и выше — отчёт построился",
        "2 = построился, но задачу почти не решил",
        "5–6 = решил частично",
        "10 = задача решена полностью",
    ):
        assert fragment in helper_text


def test_ki_58_59_workarounds_survive(helper_text):
    assert "составе комбинаций" in helper_text
    assert "get_good_combination" in helper_text
    assert "calculate_good_combination_price" in helper_text
    assert "clinic_id" in helper_text
    assert "Do not ask Report AI to output a standalone `good.id` column" in helper_text
    assert "код/артикул/наименование товара" in helper_text
    assert "Колонка Report AI «Текущий остаток на складе» суммирует остаток по всем складам базы" in helper_text
    assert "get_good_stock_balance" in helper_text
    assert "обязательный `clinic_id`" in helper_text


def test_preview_is_only_a_decision_sample(helper_text):
    assert "preview_summary" in helper_text and "preview_example_row" in helper_text
    assert "не живые данные клиники" in helper_text
    assert "Нельзя отвечать пользователю по превью" in helper_text
    assert "намеренно" in helper_text and "выдуманные правдоподобные значения" in helper_text


def test_wait_observation_is_not_guarantee(helper_text):
    assert "6–10 секунд" in helper_text
    assert "не гарантия" in helper_text
    assert "get_report_ai_job(job_id=job_id, wait_seconds=30)" in helper_text


def test_csv_export_route_survives(helper_text):
    section = helper_text.split("## Data and export", 1)[1]
    for fragment in ("csv_export_url", "относительный путь", "get_report_ai_job_export",
                     "start_report_export", "report_file_id", "get_report_export_download", "download_url"):
        assert fragment in section


def test_vaccination_route_covers_pet_and_clinic(helper_text):
    section = helper_text.split("## Вакцинации", 1)[1].split("\n## ", 1)[0]
    for fragment in ("medicalCards", "vaccinations", "get_medical_cards", "get_vaccinations",
                     "Report AI", "vaccine_pets"):
        assert fragment in section
