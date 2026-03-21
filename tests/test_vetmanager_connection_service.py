"""Unit tests for stage 23.2 Vetmanager connection save/validation service."""

from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from exceptions import AuthError
from storage import Base, create_database_engine
from storage_models import VetmanagerConnection
from vetmanager_connection_service import save_domain_api_key_connection


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


async def _make_session_factory(tmp_path: Path) -> async_sessionmaker:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'connection-service.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
@respx.mock
async def test_save_domain_api_key_connection_persists_validated_active_connection(tmp_path: Path):
    """Saving connection should validate host/key and persist encrypted active record."""
    session_factory = await _make_session_factory(tmp_path)
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-a").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-a.vetmanager.cloud"}})
    )
    respx.get("https://clinic-a.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async with session_factory() as session:
        connection = await save_domain_api_key_connection(
            session,
            account_id=1,
            domain="clinic-a",
            api_key="secret-key",
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        stored = await session.get(VetmanagerConnection, connection.id)

    assert stored is not None
    assert stored.status == "active"
    assert stored.auth_mode == "domain_api_key"
    assert stored.domain == "clinic-a"
    assert stored.encrypted_credentials is not None
    assert "secret-key" not in stored.encrypted_credentials


@pytest.mark.asyncio
@respx.mock
async def test_save_domain_api_key_connection_disables_previous_active_connection(tmp_path: Path):
    """Account should keep only one active Vetmanager connection after save."""
    session_factory = await _make_session_factory(tmp_path)
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-b").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-b.vetmanager.cloud"}})
    )
    respx.get("https://clinic-b.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async with session_factory() as session:
        old = VetmanagerConnection(
            account_id=1,
            auth_mode="domain_api_key",
            status="active",
            domain="old-clinic",
        )
        old.set_credentials(
            {"domain": "old-clinic", "api_key": "old-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        session.add(old)
        await session.commit()

    async with session_factory() as session:
        new = await save_domain_api_key_connection(
            session,
            account_id=1,
            domain="clinic-b",
            api_key="new-key",
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(VetmanagerConnection)
                .where(VetmanagerConnection.account_id == 1)
                .order_by(VetmanagerConnection.id.asc())
            )
        ).scalars().all()

    assert rows[0].status == "disabled"
    assert rows[1].id == new.id
    assert rows[1].status == "active"


@pytest.mark.asyncio
@respx.mock
async def test_save_domain_api_key_connection_rejects_invalid_api_key(tmp_path: Path):
    """Connection save should fail safely when API key is invalid."""
    session_factory = await _make_session_factory(tmp_path)
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-c").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-c.vetmanager.cloud"}})
    )
    respx.get("https://clinic-c.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    async with session_factory() as session:
        with pytest.raises(AuthError, match="Invalid Vetmanager API key"):
            await save_domain_api_key_connection(
                session,
                account_id=1,
                domain="clinic-c",
                api_key="bad-key",
                encryption_key=TEST_ENCRYPTION_KEY,
            )
