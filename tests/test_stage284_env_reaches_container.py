"""Этап 284: настройка, объявленная оператору, обязана доезжать до контейнера.

`SUPPORT_EMAIL` был записан в `.env` на проде, деплой прошёл успешно, страница
уехала — и почта в кабинете не появилась. Сервис `mcp` в `docker-compose.yml`
перечисляет переменные окружения поимённо, а `.env` — только источник
подстановки: не названа в `environment:` — не существует внутри контейнера.
Ничто при этом не падает: приложение видит пустую строку и молча ведёт себя
как при незаданной настройке.

Правило: переменная, которая одновременно (1) предложена оператору в
`.env.example` и (2) читается рантаймом через `os.environ`, обязана быть
объявлена в сервисе `mcp`. Пересечение двух условий — не список исключений:
`TEST_*` читаются тестами, `POSTGRES_*` — соседним сервисом, `UID`/`GID` —
сборкой, и ни одна из них в рантайме не читается.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ENV_READ = re.compile(r"""os\.environ(?:\.get\(|\[)["']([A-Z0-9_]+)["']""")
_DECLARED = re.compile(r"^      ([A-Z0-9_]+):", re.M)


def _runtime_env_names() -> set[str]:
    names: set[str] = set()
    sources = list(ROOT.glob("*.py"))
    for package in ("tools", "vm_transport"):
        sources.extend((ROOT / package).rglob("*.py"))
    for source in sources:
        names.update(_ENV_READ.findall(source.read_text()))
    return names


def _operator_env_names() -> set[str]:
    names: set[str] = set()
    for line in (ROOT / ".env.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            names.add(line.split("=", 1)[0].strip())
    return names


def _declared_for_mcp_service() -> set[str]:
    compose = (ROOT / "docker-compose.yml").read_text()
    start = compose.index("\n  mcp:")
    end = compose.index("\n  prometheus:")
    return set(_DECLARED.findall(compose[start:end]))


def test_every_operator_setting_the_runtime_reads_reaches_the_container() -> None:
    expected = _operator_env_names() & _runtime_env_names()
    missing = sorted(expected - _declared_for_mcp_service())

    assert not missing, (
        "Переменные предложены оператору в .env.example и читаются рантаймом, "
        "но не объявлены в сервисе mcp — внутри контейнера их не будет, "
        f"и настройка молча не сработает: {missing}"
    )


def test_the_rule_has_something_to_guard() -> None:
    """Сторож, у которого пустое множество, зелен всегда и не значит ничего."""
    assert _operator_env_names() & _runtime_env_names()
