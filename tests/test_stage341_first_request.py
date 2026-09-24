"""Stage 341: the first useful question after issuing a key."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from alembic import command

import storage
from landing_page import render_landing_page
from storage_models import ActivationEvent, VetmanagerConnection
from tests.test_stage197_token_quick_issue import _account_page, _app_client, _login_client, _token_view
from tests.test_web_auth import _extract_csrf_token, _post_with_csrf, _prepare_web_db, register_account
from tests.test_migrations import _make_alembic_config


def test_landing_has_six_answer_pairs_from_pilot_and_no_payment_promotion() -> None:
    html = render_landing_page()
    examples = html.split('id="examples"', 1)[1].split('id="faq"', 1)[0]
    assert examples.count('data-example-pair=') == 6
    assert "Кто из врачей работает сегодня?" in examples
    assert "У всех ли принятых сегодня пациентов заполнены медкарты?" in examples
    assert "пример оформления, цифры вымышленные" in examples
    assert "spoteeq.ru" not in html
    assert "@vromanichev24" not in html


def test_issued_token_keeps_key_first_and_limits_examples_to_two() -> None:
    html = _account_page(issued_raw_token="vm_st_fresh_secret")
    panel = html.split('id="issued-token-panel"', 1)[1].split('</section>', 1)[0]
    assert panel.count('data-example-pair=') == 2
    assert panel.count('data-copy-kind="example"') == 2
    assert 'data-motivator="issued"' in panel
    assert "Остался один шаг" in panel
    assert "пример оформления, цифры вымышленные" in panel
    assert panel.index('id="issued-token-value"') < panel.index("Остался один шаг")
    assert panel.index("Остался один шаг") < panel.index('id="issued-token-config"')


def test_needs_token_has_visible_jump_to_issue_form() -> None:
    html = _account_page()
    status = html.split('data-testid="activation-status"', 1)[1].split('</section>', 1)[0]
    assert 'href="#token-quick"' in status
    assert status.index('href="#token-quick"') < status.index('<ul>')


def test_waiting_and_oauth_guides_show_one_concrete_pilot_question() -> None:
    html = _account_page(bearer_tokens=[_token_view()])
    assert "Осталось немного: ждём первый запрос" in html
    assert "Кто из врачей работает сегодня?" in html
    assert 'data-poll-activation="needs_client_use"' in html
    assert "Не получается подключить?" in html
    assert "spoteeq.ru" in html
    assert "@vromanichev24" in html
    oauth_html = _account_page(oauth_grants=[{
        "id": 1, "status": "active", "client_name": "ChatGPT",
        "created_at": "сегодня", "last_used_at": "никогда",
    }])
    status = oauth_html.split('data-testid="activation-status"', 1)[1].split('</section>', 1)[0]
    assert "Кто из врачей работает сегодня?" in status
    assert "Покажи записи на сегодня" not in status


@pytest.mark.asyncio
async def test_activation_events_record_copy_and_auth_mode_without_question_or_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    async with storage.get_session_factory()() as session:
        await register_account(session, email="stage341@example.com", password="Integration-Pass-123")
    async with _app_client() as client:
        await _login_client(client, "stage341@example.com")
        for path, kind in (("/account/telemetry/token-copied", "token"), ("/account/telemetry/motivator-shown", ""), ("/account/telemetry/example-copied", "")):
            response = await _post_with_csrf(client, path, data={"kind": kind, "question": "PRIVATE_SHOULD_BE_IGNORED"}, page_path="/account")
            assert response.status_code == 204
        assert (await client.post("/account/telemetry/example-copied", data={})).status_code == 403
    async with _app_client() as anonymous:
        assert (await anonymous.post("/account/telemetry/motivator-shown", data={})).status_code == 401
    async with storage.get_session_factory()() as session:
        events = list((await session.execute(select(ActivationEvent).order_by(ActivationEvent.id))).scalars())
    assert [(event.event_name, event.auth_mode) for event in events] == [
        ("token_copied", "unknown"), ("motivator_shown", "unknown"), ("example_copied", "unknown")
    ]
    assert all(event.copy_kind in (None, "unknown", "token") for event in events)
    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_copy_auth_mode_comes_from_active_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    async with storage.get_session_factory()() as session:
        account = await register_account(session, email="stage341-mode@example.com", password="Integration-Pass-123")
        account_id = account.id
    async with _app_client() as client:
        await _login_client(client, "stage341-mode@example.com")
        csrf = _extract_csrf_token((await client.get("/account")).text)
        async with storage.get_session_factory()() as session:
            session.add(VetmanagerConnection(account_id=account_id, auth_mode="user_token", status="active", domain="fictional"))
            await session.commit()
        response = await client.post("/account/telemetry/token-copied", data={"csrf_token": csrf, "kind": "config"})
        assert response.status_code == 204
    async with storage.get_session_factory()() as session:
        event = await session.scalar(select(ActivationEvent))
        assert event is not None and event.auth_mode == "user_token"
    await engine.dispose()
    storage.reset_storage_state()


def test_activation_event_name_migration_round_trip(tmp_path: Path) -> None:
    config = _make_alembic_config(tmp_path)
    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO accounts (email, status) VALUES ('stage341-migration@example.test', 'active')"))
        conn.execute(text("INSERT INTO activation_events (account_id, event_name, auth_mode, device_class) VALUES (1, 'motivator_shown', 'unknown', 'desktop')"))
        conn.execute(text("INSERT INTO activation_events (account_id, event_name, auth_mode, device_class) VALUES (1, 'example_copied', 'unknown', 'desktop')"))
    command.downgrade(config, "20260917_000024")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM activation_events")).scalar_one() == 0
