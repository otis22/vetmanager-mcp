"""Этап 288 — правило «массовое берём отчётом» живёт в описаниях инструментов.

Решение владельца 03.09.2026 по отчёту #60: длинные и агрегирующие выборки
делаются заданием Report AI, а не тысячами поштучных вызовов. Решение было
записано только в известную проблему — а она доходит до агента через инжекцию,
которая за всю историю продукта не сработала ни разу (этап 283). То есть
на поведение оно не влияло никак.

Описание инструмента — единственный канал, который агент читает всегда.
Поэтому правило записывается туда, где ошибку и совершают: у инструментов,
по которым естественно пойти циклом.

Проверяется присутствие правила у конкретных инструментов, а не наличие слова
в файле: слово `report_ai` встречается в описаниях самих отчётных инструментов
и дало бы зелёный тест при полностью не сделанной работе.
"""

from __future__ import annotations

import pytest

from tool_descriptions import compose_tool_description


def _description_the_model_sees(tool_name: str) -> str:
    """Ровно то, что уезжает в `tools/list`.

    Первая версия теста читала только `SPECIAL_TOOL_DESCRIPTIONS` и поймала
    настоящую ошибку: правило для `get_invoice_by_id` было вписано в словарь
    приватных суффиксов. Сборка вынесена в общую функцию, чтобы проверка не
    могла разойтись с тем, что видит модель.
    """
    return compose_tool_description(tool_name) or ""

# Инструменты, по которым агент естественно идёт поштучно: отчёт #60 — добор
# позиций примерно шести тысяч счетов по одному, потому что пакетного способа нет.
LOOPED_TOOLS = (
    "get_invoice_by_id",
    "get_invoice_documents",
)


@pytest.mark.parametrize("tool_name", LOOPED_TOOLS)
def test_looped_tool_points_at_report_ai_for_bulk(tool_name: str) -> None:
    description = _description_the_model_sees(tool_name)

    assert "create_report_ai_job" in description, (
        f"{tool_name}: агент не узнает про отчёт как альтернативу циклу"
    )


@pytest.mark.parametrize("tool_name", LOOPED_TOOLS)
def test_the_rule_says_what_not_to_do(tool_name: str) -> None:
    """Одной ссылки на отчёты мало: без запрета цикл остаётся допустимым
    прочтением, а именно он и приводит к тысячам вызовов."""
    description = _description_the_model_sees(tool_name).lower()

    assert "one by one" in description or "per-invoice loop" in description


def test_report_ai_names_bulk_extraction_as_its_job() -> None:
    """Правило работает с двух сторон: инструмент цикла отсылает к отчётам,
    а отчёты подтверждают, что массовая выборка — их работа."""
    description = _description_the_model_sees("create_report_ai_job")

    assert "bulk" in description.lower()
