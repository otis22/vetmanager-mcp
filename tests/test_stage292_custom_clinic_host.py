"""Этап 292 — клиника на собственном домене подключается, адрес живёт в окружении.

Обращение 04.09.2026: клиника открывает Ветменеджер по своему адресу и не может
подключиться. Форма винила формат ввода, но настоящая стена была дальше —
резолв пропускал только зоны `vetmanager.cloud` и `vetmanager2.ru`, и правильно
введённый ключ аккаунта тоже не проходил.

Проверяется не только то, что своя клиника заработала, но и **граница риска**:
при пустой карте обе общие функции — а через них ходит каждая клиника — идут
теми же ветками, что и до этапа.

Настоящих клиентских адресов здесь нет и быть не может: карта задаётся тестом
на выдуманных значениях, а боевые адреса живут в `.env` на сервере.
"""

from __future__ import annotations

import re
import ssl
from pathlib import Path

import httpx
import pytest

from custom_clinic_hosts import CUSTOM_CLINIC_HOSTS_ENV, custom_clinic_hosts
from domain_validation import validate_domain
from exceptions import HostResolutionError
from host_validation import ALLOWED_HOST_SUFFIXES, validate_resolved_vetmanager_origin
from upstream_transport import classify_transport_error


CLINIC_KEY = "testclinic"
CLINIC_HOST = "vm2.testclinic.example"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CUSTOM_CLINIC_HOSTS_ENV, f"{CLINIC_KEY}={CLINIC_HOST}")


@pytest.fixture
def not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CUSTOM_CLINIC_HOSTS_ENV, raising=False)


# ── Граница риска: пустая карта не меняет ничего ─────────────────────────────


def test_without_configuration_a_custom_host_is_still_refused(not_configured: None) -> None:
    """Главная гарантия этапа для всех остальных клиник: пока карта пуста,
    резолв ведёт себя ровно как до этапа."""
    with pytest.raises(HostResolutionError):
        validate_resolved_vetmanager_origin(f"https://{CLINIC_HOST}", domain=CLINIC_KEY)


def test_without_configuration_the_form_still_refuses_a_dotted_address(
    not_configured: None,
) -> None:
    with pytest.raises(Exception):
        validate_domain(CLINIC_HOST)


def test_public_zones_work_with_and_without_configuration(configured: None) -> None:
    """Настроенная карта не должна ничего отнимать у обычных клиник."""
    assert (
        validate_resolved_vetmanager_origin("https://someclinic.vetmanager.cloud", domain="someclinic")
        == "https://someclinic.vetmanager.cloud"
    )
    assert (
        validate_resolved_vetmanager_origin("https://someclinic.vetmanager2.ru", domain="someclinic")
        == "https://someclinic.vetmanager2.ru"
    )


# ── Настроенная клиника ──────────────────────────────────────────────────────


def test_configured_host_is_accepted_for_its_account(configured: None) -> None:
    assert (
        validate_resolved_vetmanager_origin(f"https://{CLINIC_HOST}", domain=CLINIC_KEY)
        == f"https://{CLINIC_HOST}"
    )


def test_configured_host_is_pinned_to_its_own_account(configured: None) -> None:
    """Здесь новая проверка строже прежней: список зон разрешал любой хост зоны,
    а карта привязывает адрес к конкретному ключу аккаунта."""
    with pytest.raises(HostResolutionError):
        validate_resolved_vetmanager_origin(f"https://{CLINIC_HOST}", domain="otherclinic")


@pytest.mark.parametrize(
    "bad_origin",
    [
        f"http://{CLINIC_HOST}",
        f"https://{CLINIC_HOST}:8443",
        f"https://user:pass@{CLINIC_HOST}",
        f"https://{CLINIC_HOST}/vetmanager",
    ],
)
def test_the_other_origin_checks_still_apply_to_a_custom_host(
    configured: None, bad_origin: str
) -> None:
    """Разрешён адрес, а не всё, что на нём: схема, порт, userinfo и путь
    проверяются для своей клиники в полном объёме."""
    with pytest.raises(HostResolutionError):
        validate_resolved_vetmanager_origin(bad_origin, domain=CLINIC_KEY)


# ── Форма ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "typed",
    [CLINIC_HOST, f"https://{CLINIC_HOST}/", f"  {CLINIC_HOST.upper()}  ", f"http://{CLINIC_HOST}/index.php"],
)
def test_the_form_accepts_the_address_the_clinic_actually_opens(
    configured: None, typed: str
) -> None:
    """Клиника вводит тот адрес, который видит в браузере. Ключ аккаунта не
    угадывается из адреса — он берётся из настроенной карты."""
    assert validate_domain(typed) == CLINIC_KEY


def test_the_account_key_itself_still_works(configured: None) -> None:
    assert validate_domain(CLINIC_KEY) == CLINIC_KEY


# ── Разбор карты ─────────────────────────────────────────────────────────────


def test_missing_variable_is_an_empty_map(not_configured: None) -> None:
    assert custom_clinic_hosts() == {}


def test_broken_entries_are_ignored_instead_of_crashing_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Опечатка в `.env` не должна ронять сервис: испорченная запись пропадает,
    исправная продолжает работать."""
    monkeypatch.setenv(
        CUSTOM_CLINIC_HOSTS_ENV,
        f"мусор,=,key_without_host=, =hostless, {CLINIC_KEY} = {CLINIC_HOST.upper()} ",
    )

    assert custom_clinic_hosts() == {CLINIC_KEY: CLINIC_HOST}


def test_a_host_with_a_scheme_or_slash_is_reduced_to_the_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CUSTOM_CLINIC_HOSTS_ENV, f"{CLINIC_KEY}=https://{CLINIC_HOST}/")

    assert custom_clinic_hosts() == {CLINIC_KEY: CLINIC_HOST}


# ── Адреса клиник не живут в репозитории ─────────────────────────────────────


def test_no_clinic_address_is_hardcoded_into_the_allowlist() -> None:
    """Решение владельца 04.09.2026: публичные зоны Ветменеджера в коде, чужие
    адреса — только в окружении. Сторож ловит попытку дописать домен клиники
    в код вместо `.env`."""
    assert all("vetmanager" in suffix for suffix in ALLOWED_HOST_SUFFIXES), (
        f"в код попал чужой адрес: {ALLOWED_HOST_SUFFIXES}"
    )


# Настоящие зоны верхнего уровня: `.py`, `.md`, `.yml` под это не попадают, а
# `vm.clinic.example` — тем более, `example` не TLD. Список намеренно короткий:
# сторож ловит копипасту живого адреса, а не изобретает валидатор доменов.
_REAL_TLDS = "ru|by|com|net|org|kz|ua|cloud|io|dev"
_LOOKS_LIKE_A_HOST = re.compile(rf"\b(?:[a-z0-9-]+\.)+(?:{_REAL_TLDS})\b")
_OURS = ("vetmanager.ru", "vetmanager.cloud", "vetmanager2.ru")

# Адреса, которые в этих файлах законны: наш собственный сайт и публичные
# проекты. Список закрытый и это осознанно — новый чужой домен в файлах этапа
# обязан пройти через человека, а не появиться молча.
_KNOWN_PUBLIC = (
    "vromanichev.ru",
    "example.com",
    "github.com",
    "img.shields.io",
    "modelcontextprotocol.io",
    "opensource.org",
)

# Все файлы, которых касается этап, а не только те, где ошибку уже поймали:
# второй ход внешнего ревью 04.09.2026 справедливо заметил, что сторож на
# коротком списке остаётся зелёным при утечке в соседний изменённый файл.
_STAGE_FILES = (
    "custom_clinic_hosts.py",
    "host_validation.py",
    "domain_validation.py",
    "upstream_transport.py",
    "vetmanager_connection_service.py",
    "web_routes_account.py",
    "exceptions.py",
    "server.py",
    "docker-compose.yml",
    "pyproject.toml",
    "README.md",
    "tests/test_stage292_custom_clinic_host.py",
    "PRD/этап-292-клиника-на-своём-домене.md",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _stage_texts() -> dict[str, str]:
    root = _repo_root()
    texts = {name: (root / name).read_text(encoding="utf-8") for name in _STAGE_FILES}
    roadmap = (root / "Roadmap.md").read_text(encoding="utf-8")
    section = roadmap.split("## Этап 292.", 1)
    texts["Roadmap.md (этап 292)"] = section[1].split("\n## ", 1)[0] if len(section) > 1 else ""
    return texts


def test_no_real_clinic_address_leaks_into_the_repository() -> None:
    """Тот же запрет, но в том месте, где его и нарушили.

    Первая версия сторожа смотрела только на кортеж `ALLOWED_HOST_SUFFIXES` и
    осталась зелёной, когда настоящий адрес клиники уже лежал в PRD, в Roadmap
    и в docstring модуля (находка внешнего ревью 04.09.2026). Проверка одного
    места ничего не говорит про остальные — сторож смотрит на все файлы этапа.

    Чего он не делает, чтобы это не пришлось выяснять по его молчанию: это не
    гарантия по всему репозиторию и не защита от намеренного обхода —
    склеенная из кусков строка или base64 пройдут мимо. Он ловит то, чем эта
    ошибка и была на самом деле: копипаст живого адреса в текст.
    """
    leaks: list[str] = []
    for name, text in _stage_texts().items():
        for candidate in _LOOKS_LIKE_A_HOST.findall(text.lower()):
            if any(candidate == ours or candidate.endswith(f".{ours}") for ours in _OURS):
                continue
            if any(
                candidate == known or candidate.endswith(f".{known}")
                for known in _KNOWN_PUBLIC
            ):
                continue
            leaks.append(f"{name}: {candidate}")

    assert not leaks, (
        "в открытый репозиторий попал чужой адрес — место ему в `.env` на "
        f"сервере: {leaks}"
    )


# ── Неполная цепочка сертификата называется словами ──────────────────────────


def _connect_error_from_broken_chain() -> httpx.ConnectError:
    cause = ssl.SSLCertVerificationError("unable to get local issuer certificate")
    error = httpx.ConnectError("certificate verify failed")
    error.__cause__ = cause
    return error


def test_a_broken_certificate_chain_is_not_just_a_connection_error() -> None:
    assert classify_transport_error(_connect_error_from_broken_chain()) == "tls_verification_failed"


def test_an_ordinary_connection_error_keeps_its_old_class() -> None:
    assert classify_transport_error(httpx.ConnectError("dns or connection")) == "connect_error"


def test_the_clinic_is_told_what_to_fix_in_its_certificate() -> None:
    from exceptions import VetmanagerTlsError
    from web_routes_account import _integration_error_text

    text = _integration_error_text(VetmanagerTlsError("TLS verification failed"))

    assert "цепочк" in text.lower(), text
    assert "не отвечает" not in text, "поломка клиники не должна выглядеть как поломка Ветменеджера"


# ── Правки по внешнему ревью 04.09.2026 ──────────────────────────────────────


@pytest.mark.parametrize(
    "configured_value",
    [
        f"https://{CLINIC_HOST}:443/",
        f"{CLINIC_HOST}:443",
        f"operator@{CLINIC_HOST}",
    ],
)
def test_a_port_or_userinfo_in_the_env_entry_does_not_break_the_match(
    monkeypatch: pytest.MonkeyPatch, configured_value: str
) -> None:
    """Находка ревью: адрес из `.env` сравнивался с `urlparse(...).hostname`,
    который порт уже отбросил. Оператор копирует адрес из браузера вместе с
    `:443` — и клиника молча остаётся неподключённой, хотя запись выглядит
    правильной."""
    monkeypatch.setenv(CUSTOM_CLINIC_HOSTS_ENV, f"{CLINIC_KEY}={configured_value}")

    assert custom_clinic_hosts() == {CLINIC_KEY: CLINIC_HOST}
    assert (
        validate_resolved_vetmanager_origin(f"https://{CLINIC_HOST}", domain=CLINIC_KEY)
        == f"https://{CLINIC_HOST}"
    )


def test_a_tls_failure_that_is_not_about_the_chain_keeps_its_old_class() -> None:
    """Находка ревью: под `tls_verification_failed` попадала любая ошибка SSL,
    и человека отправляли чинить цепочку сертификата там, где дело в другом —
    например, сервер отвечает не тем протоколом."""
    cause = ssl.SSLError("[SSL: WRONG_VERSION_NUMBER] wrong version number")
    error = httpx.ConnectError("ssl error")
    error.__cause__ = cause

    assert classify_transport_error(error) == "connect_error"
