"""Этап 285, находка внешнего ревью: пустая строка — не то же, что отсутствие.

Первая версия объявления записала настройки как `NAME: ${NAME:-}`. Compose
кладёт в контейнер **пустую строку**, а не «ничего»: `os.environ.get("NAME",
"10")` возвращает `""`, дефолт не применяется, и `int("")` роняет процесс.
Проверено на живом compose: голое `- NAME` даёт `null` — переменной в
контейнере нет; `NAME=${NAME:-}` даёт `""` — есть и пустая.

Поэтому два правила, и оба здесь сторожатся.

1. Доставка: объявление настройки, которую читает рантайм, не имеет права
   создавать пустую строку. Форма записи — сквозная передача.
2. Чтение: читатель числовой настройки обязан пережить пустое значение и
   вернуться к своему дефолту. Оператор может написать `DB_POOL_SIZE=` в
   `.env` руками — падать на старте из-за этого нельзя.

Второе правило нужно именно вдобавок к первому: одна правильная форма записи
в одном файле — это не гарантия, это текущее состояние одного файла.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_stage285_runtime_env_reaches_container import runtime_env_names

ROOT = Path(__file__).resolve().parents[1]
_EMPTY_DEFAULT = re.compile(r"^\s*-\s*([A-Z0-9_]+)=\$\{[A-Z0-9_]+:-\}\s*$", re.M)


def _session_max_age_in_fresh_process(value: str) -> str:
    """`web_auth` читает настройку на импорте, поэтому проверяется импортом.

    Первая версия делала `importlib.reload(web_auth)` прямо в тесте — и роняла
    двадцать пять чужих тестов: перезагруженный модуль отдаёт новые объекты, а
    `web_routes_auth` держит ссылки на старые, и подпись сессии перестаёт
    сходиться. Отдельный процесс не трогает ничего в текущем и заодно точнее
    воспроизводит сценарий дефекта — падение на старте.
    """
    env = {**os.environ, "WEB_SESSION_MAX_AGE_SECONDS": value}
    result = subprocess.run(
        [sys.executable, "-c", "import web_auth; print(web_auth.SESSION_MAX_AGE_SECONDS)"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "импорт web_auth упал при "
        f"WEB_SESSION_MAX_AGE_SECONDS={value!r}: {result.stderr.strip()[-500:]}"
    )
    return result.stdout.strip()


def _mcp_service_block() -> str:
    compose = (ROOT / "docker-compose.yml").read_text()
    return compose[compose.index("\n  mcp:"):compose.index("\n  prometheus:")]


def test_no_declaration_turns_an_unset_setting_into_an_empty_string() -> None:
    offenders = sorted(set(_EMPTY_DEFAULT.findall(_mcp_service_block())) & runtime_env_names())

    assert not offenders, (
        "Эти настройки объявлены как ${NAME:-}: незаданная превращается в "
        "пустую строку, и дефолт из кода не применится. Писать сквозной "
        f"передачей — голым именем в списке: {offenders}"
    )


def test_the_form_check_knows_what_it_is_looking_for() -> None:
    """Регулярка, которая ничего не находит ни в каком тексте, бесполезна."""
    sample = "    environment:\n      - DB_POOL_SIZE=${DB_POOL_SIZE:-}\n      - LOG_LEVEL\n"

    assert _EMPTY_DEFAULT.findall(sample) == ["DB_POOL_SIZE"]


@pytest.mark.parametrize(
    "name",
    [
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "WEB_SESSION_MAX_AGE_SECONDS",
        "VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS",
        "WEB_LOGIN_RATE_LIMIT_ATTEMPTS",
        "WEB_LOGIN_RATE_LIMIT_WINDOW_SECONDS",
        "OAUTH_TOKEN_RATE_LIMIT_ATTEMPTS",
        "OAUTH_TOKEN_RATE_LIMIT_WINDOW_SECONDS",
    ],
)
def test_numeric_setting_survives_an_empty_value(name: str, monkeypatch) -> None:
    """Каждое имя проверяется через тот слой, который его действительно читает."""
    monkeypatch.setenv(name, "")

    if name in {"DB_POOL_SIZE", "DB_MAX_OVERFLOW"}:
        import storage

        engine = storage.create_database_engine(
            "postgresql+asyncpg://u:p@localhost:5432/db"
        )
        assert engine.pool.size() == 10 if name == "DB_POOL_SIZE" else True
        return

    if name == "WEB_SESSION_MAX_AGE_SECONDS":
        assert _session_max_age_in_fresh_process("") == str(60 * 60 * 24)
        return

    if name == "VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS":
        from env_utils import env_float

        assert env_float(name, 0.0, positive_only=False) == 0.0
        return

    from web_security import get_rate_limit_config

    prefix, _, _ = name.rpartition("_ATTEMPTS") if name.endswith("_ATTEMPTS") else name.rpartition("_WINDOW_SECONDS")
    attempts, window = get_rate_limit_config(
        prefix, default_attempts=7, default_window_seconds=11
    )
    assert (attempts, window) == (7, 11)


def test_the_grace_readers_go_through_the_tolerant_helper() -> None:
    """Пункт про `VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS` проверяется у источника.

    Хелпер терпим к пустой строке сам по себе — тест выше это и показывает,
    но он ничего не говорит про то, вызывают ли его два места закрытия
    клиентов. Поэтому здесь читается их код.
    """
    for module in ("host_resolver.py", "vm_transport/pool.py"):
        text = (ROOT / module).read_text()
        assert 'float(os.environ.get("VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS"' not in text, (
            f"{module}: сырой float() по переменной окружения падает на пустом значении"
        )
        assert "VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS" in text


@pytest.mark.parametrize(
    ("name", "read", "expected"),
    [
        ("DB_POOL_SIZE", lambda: __import__("storage").create_database_engine(
            "postgresql+asyncpg://u:p@localhost:5432/db").pool.size(), 0),
        ("WEB_SESSION_MAX_AGE_SECONDS", lambda: int(
            _session_max_age_in_fresh_process("0")), 0),
        ("WEB_LOGIN_RATE_LIMIT_ATTEMPTS", lambda: __import__(
            "web_security").get_rate_limit_config(
            "WEB_LOGIN_RATE_LIMIT", default_attempts=7, default_window_seconds=11)[0], 0),
    ],
)
def test_an_explicit_zero_is_not_silently_replaced(name, read, expected, monkeypatch) -> None:
    """Терпимость к пустому значению не должна стать глухотой к нулю.

    `env_int` по умолчанию отбрасывает значения <= 0 и подставляет дефолт.
    Сырой `int()` их принимал, поэтому перевод на хелпер без отключения
    `positive_only` завёл бы ту же болезнь с другого конца: настройка задана,
    а не действует.
    """
    monkeypatch.setenv(name, "0")

    assert read() == expected
