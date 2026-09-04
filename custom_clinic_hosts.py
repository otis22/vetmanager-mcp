"""Собственные адреса клиник — из окружения, не из репозитория.

Часть клиник открывает Ветменеджер не на `*.vetmanager.ru`, а на своём домене.
billing-api такую клинику знает и возвращает её адрес, но список разрешённых
зон (`host_validation.ALLOWED_HOST_SUFFIXES`) его отбрасывал — этап 292.

Решение владельца 04.09.2026: публичные зоны Ветменеджера остаются в коде, это
не секрет. Чужие адреса в открытый репозиторий не попадают — они живут в `.env`
на сервере. Здесь только имя переменной и разбор её формата.

Формат:

    CUSTOM_CLINIC_HOSTS=ключ_аккаунта=хост,ключ_аккаунта=хост

Ключ аккаунта — тот, по которому клиника заведена в billing-api (его выясняет
человек, а не догадывается код). Пустая переменная = поведение до этапа 292,
байт в байт.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from observability_logging import RUNTIME_LOGGER

CUSTOM_CLINIC_HOSTS_ENV = "CUSTOM_CLINIC_HOSTS"

# Разбор дешёвый, но `validate_domain` вызывается на каждом запросе рантайма,
# поэтому результат держим до тех пор, пока не изменилось само значение.
_parsed_cache: tuple[str, dict[str, str]] | None = None


def _hostname_only(raw: str) -> str:
    """Свести запись адреса к голому имени хоста.

    В `.env` адрес легко скопировать из браузера вместе со схемой, слэшем и
    портом. Ронять из-за этого подключение клиники — плохой размен.

    Разбор идёт тем же `urlsplit`, что и в `validate_resolved_vetmanager_origin`,
    и это не стилистика: там адрес сравнивается с `hostname`, где порт и
    userinfo уже отброшены. Своя, «похожая» нарезка строки давала бы
    `host:443` против `host` — молчаливое несовпадение, при котором запись в
    `.env` выглядит правильной, а клиника не подключается (находка внешнего
    ревью 04.09.2026).
    """
    host = raw.strip().lower().rstrip("/")
    if "//" not in host:
        host = f"//{host}"
    try:
        hostname = urlsplit(host).hostname or ""
    except ValueError:
        return ""
    return hostname.rstrip(".")


def custom_clinic_hosts() -> dict[str, str]:
    """Карта «ключ аккаунта → адрес клиники». Пустая, если ничего не настроено.

    Испорченная запись пропускается молча: опечатка в `.env` не должна ронять
    старт и отбирать доступ у всех остальных клиник.
    """
    global _parsed_cache
    raw = os.environ.get(CUSTOM_CLINIC_HOSTS_ENV) or ""
    if _parsed_cache is not None and _parsed_cache[0] == raw:
        return _parsed_cache[1]

    parsed: dict[str, str] = {}
    for entry in raw.split(","):
        key, separator, host = entry.partition("=")
        if not separator:
            continue
        key = key.strip().lower()
        host = _hostname_only(host)
        if not key or not host:
            continue
        parsed[key] = host

    _parsed_cache = (raw, parsed)
    return parsed


def custom_host_for_account(domain: str) -> str | None:
    """Адрес, разрешённый именно этому ключу аккаунта."""
    return custom_clinic_hosts().get(domain.strip().lower())


def account_key_for_custom_host(host: str) -> str | None:
    """Обратный ход: по адресу, который клиника видит в браузере, — её ключ.

    Ключ не выводится из адреса: `vm.clinic.example` → `clinic` выглядит
    очевидным, но это совпадение бренда с ключом, а не правило.
    """
    if not host:
        return None
    wanted = _hostname_only(host)
    for key, configured in custom_clinic_hosts().items():
        if configured == wanted:
            return key
    return None


def log_custom_clinic_hosts() -> None:
    """Сказать в журнал, доехала ли карта.

    Значение живёт только на сервере и при пересборке машины теряется молча.
    В журнал идёт количество, не адреса: по нему видно, пустая карта или нет.
    """
    RUNTIME_LOGGER.info(
        "Custom clinic hosts configured",
        extra={
            "event_name": "custom_clinic_hosts_configured",
            "host_count": len(custom_clinic_hosts()),
        },
    )
