"""Stage 440 real HTTP probe on the isolated devtr6-configured web stand."""

import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bearer_token_manager import build_token_prefix, hash_bearer_token
from storage_models import Account, OAuthClient, OAuthGrant, OAuthRefreshToken, VetmanagerConnection


pytestmark = pytest.mark.real_api


def _counter(body: str, prefix: str) -> int:
    values = [int(line.rsplit(" ", 1)[1]) for line in body.splitlines()
              if line.startswith(prefix)]
    assert len(values) <= 1
    return values[0] if values else 0


@pytest.mark.skipif(not os.environ.get("TEST_API_KEY") or
                    os.environ.get("TEST_DOMAIN") != "devtr6",
                    reason="devtr6 contour absent")
def test_http_token_denial_and_stale_marker_on_isolated_stand(
        prepared_web_db, live_server_url, caplog):
    assert "pytest" in str(prepared_web_db)
    engine = create_engine(f"sqlite:///{prepared_web_db}")
    old_token = "vm_ort_stage440_live_revoked"
    client_id = "vm_oc_stage440_live"
    with Session(engine) as session:
        account = Account(email="stage440-live@example.test", status="active")
        session.add(account)
        session.flush()
        connection = VetmanagerConnection(
            account_id=account.id, auth_mode="domain_api_key",
            status="active", domain=os.environ["TEST_DOMAIN"])
        session.add(connection)
        session.flush()
        session.add(OAuthClient(
            client_id=client_id, client_name="Stage 440 live", status="active",
            redirect_uris_json='["https://example.com/callback"]',
            token_endpoint_auth_method="none",
            grant_types_json='["authorization_code","refresh_token"]',
            response_types_json='["code"]', scope="clients.read offline_access"))
        old = OAuthGrant(account_id=account.id, vetmanager_connection_id=connection.id,
                         client_id=client_id, scopes_json='["clients.read"]', status="revoked")
        session.add(old)
        session.flush()
        session.add(OAuthGrant(account_id=account.id, vetmanager_connection_id=connection.id,
                               client_id=client_id, scopes_json='["clients.read"]', status="active"))
        session.add(OAuthRefreshToken(
            grant_id=old.id, token_prefix=build_token_prefix(old_token),
            token_hash=hash_bearer_token(old_token), scope="clients.read offline_access",
            resource="https://test.example.com/mcp", status="revoked",
            expires_at=datetime.now(timezone.utc) + timedelta(days=10)))
        session.commit()
        old_id = old.id

    with httpx.Client(base_url=live_server_url, timeout=30) as client:
        before = client.get("/metrics")
        with caplog.at_level("INFO", logger="vetmanager.runtime"):
            bad = client.post("/oauth/token", data={
                "grant_type": "refresh_token", "refresh_token": "vm_ort_stage440_unknown",
                "client_id": client_id, "resource": "https://test.example.com/mcp"})
            stale = client.post("/oauth/token", data={
                "grant_type": "refresh_token", "refresh_token": old_token,
                "client_id": client_id, "resource": "https://test.example.com/mcp"})
        metrics = client.get("/metrics")

    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    assert stale.status_code == 400 and stale.json()["error"] == "invalid_grant"
    assert before.status_code == metrics.status_code == 200
    error_line = 'vetmanager_oauth_token_errors_total{error="invalid_grant",grant_type="refresh_token"}'
    stale_line = "vetmanager_oauth_stale_grant_refresh_total "
    assert _counter(metrics.text, error_line) - _counter(before.text, error_line) == 2
    assert _counter(metrics.text, stale_line) - _counter(before.text, stale_line) == 1
    assert any(getattr(record, "event_name", None) == "oauth_token_rejected"
               and record.error == "invalid_grant" for record in caplog.records)
    assert any(getattr(record, "event_name", None) == "oauth_stale_grant_refresh"
               and record.grant_id == old_id for record in caplog.records)
    print("STAGE440_LIVE bad_http=400 body=invalid_grant stale_http=400 body=invalid_grant"
          " token_errors=2 stale_marker=1 log=oauth_stale_grant_refresh")
    engine.dispose()
