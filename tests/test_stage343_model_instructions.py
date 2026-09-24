"""The three active agent instructions must keep the same review contract."""

from pathlib import Path
import re

import pytest


FILES = (Path("AGENTS.md"), Path("CLAUDE.md"), Path(".cursor/rules/agent-workflow.mdc"))
START = "<!-- stage-343-model-contract:start -->"
END = "<!-- stage-343-model-contract:end -->"
VISUAL_START = "<!-- stage-345-visual-contract:start -->"
VISUAL_END = "<!-- stage-345-visual-contract:end -->"
VISUAL_REQUIRED = (
    "desktop и phone снимки `full_page`",
    "первый экран телефона — отдельным PNG",
    "тема без реализации не включается",
    "побайтные дубли и пропуски — ошибка подготовки evidence",
    "прочитать весь видимый текст",
    "бессмысленные, склеенные, противоречивые фразы",
    "повторы вопросов/ответов, пустые подписи и элементы вне палитры",
)


def check_visual_contract(text: str) -> list[str]:
    block = text.split(VISUAL_START, 1)[1].split(VISUAL_END, 1)[0] if VISUAL_START in text and VISUAL_END in text else ""
    return [part for part in VISUAL_REQUIRED if part not in block]
REQUIRED = (
    "gpt-6-sol",
    "gpt-6-luna",
    "gpt-6-astra",
    "одновременно",
    "дождаться обоих",
    "если он исчерпан, повтор сильной пары допускается с записанным rationale без четвёртого Spark",
    "У Astra и Opus отдельные бюджеты: 2 валидных запуска на каждый гейт у каждого и не более 3 infrastructure attempts у каждого.",
    "Architecture Critique делит PRD-бюджет, визуальный гейт имеет отдельный бюджет.",
    "Если любая сторона не дала валидного ответа после трёх неуспешных попыток, гейт blocked и push запрещён.",
    "astra-<gate>-attempt-N-of-3.result.json",
    "validate_review_result.py --plain",
    "этот режим принимает severity `critical`/`high`/`medium`",
    "Astra получает скриншоты флагом `-i` и даёт решающее визуальное ревью.",
    "Opus запускается с `--image` и получает пиксели скриншотов.",
    "Opus `[]` засчитывается только если metadata содержит изображения с совпадающими путями, размерами и SHA-256.",
    "Без валидного визуального вердикта Astra гейт blocked.",
    "Codex CLI ≥ 0.155",
    "Если после исчерпания бюджетов сильного ревью в код внесена любая правка, проверить её Spark (`gpt-6-luna` как отдельный scout) и тестами",
    "push разрешён при закрытых critical/high и валидных verdict обоих ревьюеров. Это не замена неуспешному сильному гейту без валидного verdict.",
)


def check_contract(text: str) -> list[str]:
    block = text.split(START, 1)[1].split(END, 1)[0] if START in text and END in text else ""
    missing = [part for part in REQUIRED if part not in block]
    if re.search(r"gpt-5\.6(?:-[a-z]+)?", text):
        missing.append("старый слаг gpt-5.6")
    return missing


@pytest.mark.parametrize("path", FILES)
def test_current_model_contract(path: Path) -> None:
    assert not (missing := check_contract(path.read_text(encoding="utf-8"))), (path, missing)


def test_model_contract_blocks_are_identical() -> None:
    blocks = [path.read_text(encoding="utf-8").split(START, 1)[1].split(END, 1)[0] for path in FILES]
    assert blocks[0] == blocks[1] == blocks[2]


def test_visual_contract_blocks_are_identical_and_complete() -> None:
    blocks = [path.read_text(encoding="utf-8").split(VISUAL_START, 1)[1].split(VISUAL_END, 1)[0] for path in FILES]
    assert blocks[0] == blocks[1] == blocks[2]
    assert all(not check_visual_contract(path.read_text(encoding="utf-8")) for path in FILES)


@pytest.mark.parametrize("part", VISUAL_REQUIRED)
def test_visual_contract_guard_detects_missing_clause(part: str) -> None:
    text = FILES[0].read_text(encoding="utf-8")
    assert part in text
    assert part in check_visual_contract(text.replace(part, "", 1))


@pytest.mark.parametrize("broken_part", REQUIRED)
@pytest.mark.parametrize("path", FILES)
def test_contract_guard_detects_each_missing_rule(path: Path, broken_part: str) -> None:
    text = path.read_text(encoding="utf-8")
    prefix, rest = text.split(START, 1)
    block, suffix = rest.split(END, 1)
    assert broken_part in block
    broken = prefix + START + block.replace(broken_part, "") + END + suffix
    assert broken_part in check_contract(broken)


@pytest.mark.parametrize("path", FILES)
def test_contract_guard_detects_old_slug(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "старый слаг gpt-5.6" in check_contract(text + "\ngpt-5.6-sol\n")


@pytest.mark.parametrize("path", FILES)
@pytest.mark.parametrize(
    ("old", "replacement"),
    [
        ("У Astra и Opus отдельные бюджеты: 2 валидных запуска на каждый гейт у каждого и не более 3 infrastructure attempts у каждого.", "У Astra и Opus общий бюджет: 2 валидных запуска и 3 infrastructure attempts."),
        ("Если любая сторона не дала валидного ответа после трёх неуспешных попыток, гейт blocked и push запрещён.", "Если любая сторона не дала ответа, push разрешён после записи rationale."),
        ("Без валидного визуального вердикта Astra гейт blocked.", "Без валидного визуального вердикта Astra можно принять текстовый verdict Opus."),
        ("Opus `[]` засчитывается только если metadata содержит изображения с совпадающими путями, размерами и SHA-256.", "Opus `[]` засчитывается без изображений."),
    ],
)
def test_contract_guard_rejects_semantic_regression(path: Path, old: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    assert old in check_contract(text.replace(old, replacement, 1))
