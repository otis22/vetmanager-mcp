"""Этап 284 — вход поддержки: issues публично, почта только за логином.

Адрес `support@vetmanager.cloud` прожил на боевом лендинге месяцы потому, что
тест сторожил его **наличие**, а не уместность. Здесь правило перевёрнуто:
публичная страница не должна содержать `mailto:` вообще, ни при каких значениях
окружения, а почта показывается только вошедшему и только если оператор её задал.

Отдельно проверяется, что адрес не живёт в коде: без `SUPPORT_EMAIL` в кабинете
нет ни ссылки, ни пустого `mailto:`.
"""

from __future__ import annotations

import pytest

from landing_page import render_landing_page
from storage_models import Account
from web_html import render_account_page

ISSUES_URL = "https://github.com/otis22/vetmanager-mcp/issues"


def _render_cabinet() -> str:
    account = Account(id=1, email="ops@example.com", status="active")
    return render_account_page(
        account,
        csrf_token="csrf-token",
        script_nonce="nonce",
        active_connection_count=1,
        bearer_token_count=0,
        active_connection=None,
        integration_health_status="active",
        integration_health_reason="ok",
        bearer_tokens=[],
        oauth_grants=[],
    )


def test_landing_support_entry_is_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPPORT_EMAIL", raising=False)
    html = render_landing_page()

    assert "mailto:" not in html
    assert html.count(ISSUES_URL) >= 2


def test_landing_never_shows_the_address_even_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Самое важное свойство: публичная страница не подхватывает адрес.

    Иначе переменная окружения становится способом случайно опубликовать личную
    почту — ровно то, ради чего адрес и убрали из кода.
    """
    monkeypatch.setenv("SUPPORT_EMAIL", "owner@example.org")
    html = render_landing_page()

    assert "mailto:" not in html
    assert "owner@example.org" not in html


def test_cabinet_shows_issues_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPPORT_EMAIL", raising=False)
    html = _render_cabinet()

    assert ISSUES_URL in html


def test_cabinet_has_no_mailto_when_address_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUPPORT_EMAIL", raising=False)
    html = _render_cabinet()

    assert "mailto:" not in html


def test_cabinet_shows_the_address_once_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPPORT_EMAIL", "owner@example.org")
    html = _render_cabinet()

    assert "mailto:owner@example.org" in html


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not-an-address",
        "owner@example.org, evil@example.net",
        'owner@example.org" onmouseover="alert(1)',
        "owner@example.org<script>",
        "owner @example.org",
        "owner@example.org\nBcc: evil@example.net",
        "a" * 250 + "@example.org",
    ],
)
def test_malformed_address_is_ignored_rather_than_rendered(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """Значение приходит от оператора и уезжает в атрибут href.

    Мусор здесь должен превращаться в отсутствие ссылки, а не в сломанную
    разметку: иначе `.env` становится точкой инъекции в страницу кабинета.
    """
    monkeypatch.setenv("SUPPORT_EMAIL", raw)
    html = _render_cabinet()

    assert "mailto:" not in html
