"""Stage 329: broaden token redaction without masking Russian toggles."""

from __future__ import annotations

import pytest

from property_privacy import is_secret_property_name_or_title, looks_like_secret_value


@pytest.mark.parametrize(
    "value",
    [
        "sk" + "_live_4eC39HqLyjWDarjtT1zdp7dc",
        "AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY",
        "ghp_16C7e42F292c6912E7710c838347Ae178B4a",
        "xoxp-1234567890-abcdefghijkl",
        "ya29.a0AfH6SMBx7vExampleOAuthToken",
        "glpat-ExampleGitLabToken1234567890",
        "hf_ExampleHuggingFaceToken1234567890",
        "Bearer ExampleAccessToken1234567890",
        "k8m2p9q4w7e3r6t5y0u2i9o1p3a5s7d9",
        "ABCD1234EFGH5678IJKL9012MNOPQRST",
    ],
)
def test_common_credential_forms_are_secrets(value):
    assert looks_like_secret_value(value)


@pytest.mark.parametrize(
    "value",
    [
        "10:00-19:00",
        "Europe/Moscow",
        "smtp.yandex.ru",
        "operator@example.test",
        "+79990000000",
        "550e8400-e29b-41d4-a716-446655440000",
        "/api/v1/clinic/settings/export",
        "/api/v1/clinic/ABCDEFGHIJKL1234567890ABCDEFGHIJKL/export",
        "v6.0.1",
        "длинноесловодляобычнойнастройки",
        '{"enabled":true}',
    ],
)
def test_ordinary_values_remain_safe(value):
    assert not looks_like_secret_value(value)


@pytest.mark.parametrize(
    "title",
    [
        "Включить SMS-уведомления",
        "Отключить SMS-уведомления",
        "Подключение к сервису",
        "Исключить из выгрузки",
        "Переключить режим",
    ],
)
def test_russian_toggle_titles_are_not_secrets(title):
    assert not is_secret_property_name_or_title({"property_title": title})


def test_russian_api_key_title_remains_secret():
    assert is_secret_property_name_or_title({"property_title": "Ключ API Idexx"})
