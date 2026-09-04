"""Shared validation helpers for resolved Vetmanager clinic origins."""

from __future__ import annotations

from urllib.parse import urlparse

from custom_clinic_hosts import custom_host_for_account
from exceptions import HostResolutionError

# Публичные зоны Ветменеджера. Собственные адреса клиник сюда не дописываются —
# они приходят из окружения (`CUSTOM_CLINIC_HOSTS`, этап 292), потому что это
# чужие адреса и в открытом репозитории им не место.
ALLOWED_HOST_SUFFIXES = ("vetmanager.cloud", "vetmanager2.ru")


def validate_resolved_vetmanager_origin(host: str, *, domain: str) -> str:
    """Validate billing-resolved origin and return normalized HTTPS origin."""
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise HostResolutionError(f"Resolved host must use HTTPS for domain '{domain}'.")
    if parsed.username or parsed.password:
        raise HostResolutionError(f"Resolved host must not include userinfo for domain '{domain}'.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise HostResolutionError(f"Resolved host has invalid port for domain '{domain}'.") from exc
    if port not in (None, 443):
        raise HostResolutionError(
            f"Resolved host must not use a custom port for domain '{domain}'."
        )
    if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
        raise HostResolutionError(
            f"Resolved host must be a bare origin for domain '{domain}'."
        )
    in_public_zone = any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in ALLOWED_HOST_SUFFIXES
    )
    # Этап 292. Проверка добавляется к зонам, а не заменяет их: опечатка в
    # карте не должна отбирать доступ у клиники, которая работает сегодня.
    # При этом сама она строже — адрес привязан к конкретному ключу аккаунта,
    # тогда как зона разрешает любой хост внутри себя.
    # `rstrip(".")` — чтобы два разбора сходились: карта из окружения приводит
    # адрес к виду без завершающей точки, и без этого `host.` из billing-api
    # не совпал бы с настроенным `host` (второй ход ревью 04.09.2026).
    if not in_public_zone and hostname.rstrip(".") != custom_host_for_account(domain):
        raise HostResolutionError(f"Resolved host is not allowlisted for domain '{domain}'.")
    if not hostname:
        raise HostResolutionError(f"Resolved host is missing hostname for domain '{domain}'.")
    return f"https://{hostname}"
