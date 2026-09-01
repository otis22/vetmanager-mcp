"""Stage 276 — the public route that hands out a cleaned export.

The link is the key: anyone holding it downloads the file. So the route checks
three things before it gives anything away — the path is one it could have
signed, the file is younger than three days, and the access it was issued to is
still alive. Every refusal looks the same from outside.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import json

import httpx
import pytest
import pytest_asyncio

import report_export
from privacy_utils import REPORT_EXPORT_ROUTE_TEMPLATE
import web_routes_export
from server import mcp
from storage_models import (
    Account,
    OAuthAccessToken,
    OAuthGrant,
    ServiceBearerToken,
    VetmanagerConnection,
)


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="
DOMAIN = "route-clinic"
BODY = "﻿Владелец;Приёмов\r\n[redacted-name];3\r\n"


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "report-export-route.db")


@pytest.fixture(autouse=True)
def export_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "report-exports"
    monkeypatch.setenv("REPORT_EXPORT_DIR", str(root))
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage-276-route-secret")
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    report_export.reset_link_key_cache()
    return root


async def _make_token(session_factory, *, status: str = "active", expires_in_days: int | None = 30):
    async with session_factory() as session:
        account = Account(email="route@example.com", status="active")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain=DOMAIN,
        )
        connection.set_credentials(
            {"domain": DOMAIN, "api_key": "route-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Route", status=status)
        token.set_raw_token("vm_sbt_route_token_value")
        if expires_in_days is not None:
            token.expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        session.add_all([connection, token])
        await session.commit()
        return token.id


def _store(*, subject_type: str = "service_bearer", subject_id: int) -> str:
    owner = report_export.owner_segment(
        domain=DOMAIN, subject_type=subject_type, subject_id=subject_id
    )
    filename = report_export.new_export_filename(report_file_id=5)
    return report_export.store_export(
        csv_text=BODY,
        owner=owner,
        filename=filename,
        subject_type=subject_type,
        subject_id=subject_id,
        download_name="report-5.csv",
    )


async def _get(url_path: str, session_factory):
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    with patch.object(web_routes_export, "get_session_factory", return_value=session_factory):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(url_path)


@pytest.mark.asyncio
async def test_a_live_link_hands_over_the_cleaned_file(session_factory):
    token_id = await _make_token(session_factory)
    url_path = _store(subject_id=token_id)

    response = await _get(url_path, session_factory)

    assert response.status_code == 200
    assert response.text == BODY
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="report-5.csv"' in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_a_revoked_token_stops_handing_out_its_files(session_factory):
    token_id = await _make_token(session_factory, status="revoked")
    url_path = _store(subject_id=token_id)

    response = await _get(url_path, session_factory)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_an_expired_token_stops_handing_out_its_files(session_factory):
    token_id = await _make_token(session_factory, expires_in_days=-1)
    url_path = _store(subject_id=token_id)

    response = await _get(url_path, session_factory)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_token_that_no_longer_exists_stops_handing_out_its_files(session_factory):
    await _make_token(session_factory)
    url_path = _store(subject_id=9999)

    response = await _get(url_path, session_factory)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_broken_database_refuses_rather_than_guesses(session_factory):
    token_id = await _make_token(session_factory)
    url_path = _store(subject_id=token_id)

    def _explode():
        raise RuntimeError("storage is down")

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    with patch.object(web_routes_export, "get_session_factory", side_effect=_explode):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(url_path)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_every_refusal_looks_the_same_from_outside(session_factory):
    token_id = await _make_token(session_factory)
    url_path = _store(subject_id=token_id)
    unknown = f"/report-export/{'0' * 32}/{'0' * 32}.csv"

    served = await _get(url_path, session_factory)
    missing = await _get(unknown, session_factory)
    malformed = await _get("/report-export/short/also-short.csv", session_factory)

    assert served.status_code == 200
    assert missing.status_code == malformed.status_code == 404
    assert missing.text == malformed.text


@pytest.mark.asyncio
async def test_an_oauth_grant_that_was_revoked_stops_handing_out_its_files(session_factory):
    async with session_factory() as session:
        account = Account(email="oauth-route@example.com", status="active")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain=DOMAIN,
        )
        connection.set_credentials(
            {"domain": DOMAIN, "api_key": "route-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        session.add(connection)
        await session.flush()
        grant = OAuthGrant(
            account_id=account.id,
            vetmanager_connection_id=connection.id,
            client_id="client-1",
            scopes_json=json.dumps(["analytics.read"]),
            status="revoked",
        )
        session.add(grant)
        await session.flush()
        access_token = OAuthAccessToken(
            grant_id=grant.id,
            token_prefix="vm_oat_x",
            token_hash="hash-value",
            scope="analytics.read",
            resource="https://mcp.example/mcp",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        session.add(access_token)
        await session.commit()
        access_token_id = access_token.id

    url_path = _store(subject_type="oauth_access_token", subject_id=access_token_id)

    response = await _get(url_path, session_factory)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_access_line_the_route_writes_carries_no_key(session_factory, export_root: Path):
    """The metrics label is the template, so the signed path never lands there."""
    import service_metrics

    token_id = await _make_token(session_factory)
    url_path = _store(subject_id=token_id)

    await _get(url_path, session_factory)

    rendered = service_metrics.render_prometheus_metrics()
    assert REPORT_EXPORT_ROUTE_TEMPLATE in rendered
    assert url_path not in rendered
