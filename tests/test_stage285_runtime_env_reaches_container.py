"""Этап 285: настройка, которую читает рантайм, обязана доезжать до контейнера.

Сторож этапа 284 закрывал только пересечение с `.env.example` — то, что явно
обещано оператору. Всё остальное он не видел, и разбор 03.09.2026 показал, что
видел он и того меньше: его извлекатель знал единственную форму чтения —
`os.environ.get("ИМЯ")` в корне, `tools/` и `vm_transport/`. Мимо проходили

* пакет `auth/` целиком — его просто не сканировали;
* обёртки `env_int` / `env_float` — пороги брейкера, TTL резолвера, лимиты
  bearer;
* `_is_truthy_env("ИМЯ")` и `_env_flag("ИМЯ", ...)`;
* чтение по **константе**: `os.environ.get(STREAMABLE_HTTP_DRAIN_ENABLED_ENV,
  ...)` — литерала в месте чтения нет вообще (нашло внешнее ревью);
* `get_rate_limit_config("ПРЕФИКС")`, который собирает имя из префикса:
  `ПРЕФИКС_ATTEMPTS` и `ПРЕФИКС_WINDOW_SECONDS`.

Поэтому счёт в этапе был занижен вдвое: не двенадцать настроек мимо контейнера,
а тридцать. Правило простое и без третьего варианта: имя, которое рантайм
читает из окружения, либо объявлено в сервисе `mcp`, либо не читается из
окружения вовсе. «Читается, но задать нельзя» — это и есть дефект: код видит
пустую строку и молча работает по умолчанию, а деплой при этом зелёный.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_RATE_LIMIT_SUFFIXES = ("_ATTEMPTS", "_WINDOW_SECONDS")
_NOT_RUNTIME = {"tests", "scripts", "alembic", ".venv", "__pycache__"}
# Список, а не отображение: `- NAME` передаёт значение только если оно задано.
# Разбор объявлений живёт здесь в одном экземпляре — сторож этапа 284 берёт
# его отсюда же, чтобы две регулярки не разъехались при смене формы записи.
_DECLARED = re.compile(r"^      -\s*([A-Z0-9_]+)", re.M)
_IMAGE_ENV = re.compile(r"^ENV\s+([A-Z0-9_]+)=", re.M)


def _runtime_sources() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*.py")
        if not _NOT_RUNTIME.intersection(path.relative_to(ROOT).parts)
    ]


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """`FOO_ENV = "FOO"` на уровне модуля — имя переменной окружения через шаг.

    Найдено внешним ревью: `server.py` читает окружение по константе, и
    регулярка по литералу такое чтение не видела вовсе.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
            if isinstance(value.value, str) and _ENV_NAME.fullmatch(value.value):
                constants[target.id] = value.value
    return constants


def _as_env_name(node: ast.expr | None, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if _ENV_NAME.fullmatch(node.value) else None
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _reads_environment(node: ast.Call) -> bool:
    """`os.environ.get` / `os.getenv` — и любой хелпер, в имени которого есть env.

    Именно так ловятся `env_int`, `env_float`, `_is_truthy_env` и `_env_flag`:
    перечислять их поимённо — значит забыть следующий.
    """
    name = _called_name(node)
    if name in {"get", "getenv"}:
        return "environ" in ast.dump(node.func) or name == "getenv"
    return "env" in name.lower()


def runtime_env_names() -> set[str]:
    """Всё, что рантайм читает из окружения, в любой из известных форм."""
    names: set[str] = set()
    for source in _runtime_sources():
        tree = ast.parse(source.read_text())
        constants = _module_constants(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript):
                target = node.value
                if isinstance(target, ast.Attribute) and target.attr == "environ":
                    found = _as_env_name(node.slice, constants)
                    if found:
                        names.add(found)
                continue
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if _called_name(node) == "get_rate_limit_config":
                prefix = _as_env_name(node.args[0], constants)
                if prefix:
                    names.update(prefix + suffix for suffix in _RATE_LIMIT_SUFFIXES)
                continue
            if _reads_environment(node):
                found = _as_env_name(node.args[0], constants)
                if found:
                    names.add(found)
    return names


def declared_for_mcp_service() -> set[str]:
    compose = (ROOT / "docker-compose.yml").read_text()
    start = compose.index("\n  mcp:")
    end = compose.index("\n  prometheus:")
    return set(_DECLARED.findall(compose[start:end]))


def _baked_into_the_image() -> set[str]:
    """Второй законный канал доставки — сборка образа.

    `ERROR_TRACKING_RELEASE` — версия кода, а не настройка оператора: её
    подставляет `deploy_server.sh` через `--build-arg`, а `Dockerfile`
    закрепляет как `ENV`. Первая версия этого этапа честно объявила её в
    `environment:` — и тем самым сломала бы прод: `GIT_SHA` на сервере в
    окружении не экспортирован, подстановка дала бы `unknown` и затёрла
    настоящий SHA. Канал признаётся, но не на слово: имя засчитывается,
    только если `Dockerfile` действительно его закрепляет.
    """
    return set(_IMAGE_ENV.findall((ROOT / "Dockerfile").read_text()))


def test_every_setting_the_runtime_reads_reaches_the_container() -> None:
    delivered = declared_for_mcp_service() | _baked_into_the_image()
    missing = sorted(runtime_env_names() - delivered)

    assert not missing, (
        "Рантайм читает эти переменные из окружения, но ни сервис mcp, ни "
        "сборка образа их не доставляют — внутри контейнера их не будет, и "
        f"задать их оператор не может ничем: {missing}"
    )


def test_the_image_channel_is_not_a_blanket_excuse() -> None:
    """Канал сборки признан ради одного имени и обязан оставаться узким.

    Если `Dockerfile` начнёт закреплять настройки пачками, разница схлопнется
    и правило замолчит — поэтому список того, что доставляется образом,
    проверяется поимённо.
    """
    assert _baked_into_the_image() & runtime_env_names() == {"ERROR_TRACKING_RELEASE"}


def test_the_extractor_sees_the_indirect_readers() -> None:
    """Сузить извлекатель — самый простой способ сделать этот тест зелёным.

    Множество имён тогда схлопнется, разница с объявленным станет пустой, и
    сторож будет молчать ровно про те чтения, ради которых он написан. Поэтому
    по одному представителю каждой непрямой формы проверяется явно.
    """
    names = runtime_env_names()

    assert "BEARER_RATE_LIMIT_REQUESTS" in names, "пакет auth/ не просканирован"
    assert "BREAKER_FAILURE_THRESHOLD" in names, "env_int/env_float не видны"
    assert "RATE_LIMIT_REQUIRE_REDIS" in names, "_is_truthy_env не виден"
    assert "WEB_SESSION_SECURE" in names, "_env_flag не виден"
    assert "STREAMABLE_HTTP_DRAIN_ENABLED" in names, "чтение по константе не видно"
    assert "WEB_LOGIN_RATE_LIMIT_ATTEMPTS" in names, "имя из префикса не собрано"


def test_security_settings_are_operable_on_the_running_service() -> None:
    """Отдельно и первыми — пункт 285.2.

    HSTS, `SameSite` сессии и доверенные прокси оператор считает
    настраиваемыми: их читает код, про них написано в документации. Пока их
    нет в сервисе, на боевом контуре они не управляются вообще.
    """
    declared = declared_for_mcp_service()

    for name in (
        "WEB_ENABLE_HSTS",
        "WEB_SESSION_SAMESITE",
        "WEB_SESSION_MAX_AGE_SECONDS",
        "WEB_TRUSTED_PROXY_IPS",
        "FORWARDED_ALLOW_IPS",
    ):
        assert name in declared, f"настройка безопасности {name} не управляется на бою"
