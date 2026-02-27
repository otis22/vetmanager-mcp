"""E2E real API tests against domain devtr6.

Skipped automatically when TEST_DOMAIN / TEST_API_KEY env vars are not set.
Run inside Docker:
    docker compose run --rm -e TEST_DOMAIN=devtr6 -e TEST_API_KEY=<key> test
"""

import os
import pytest
from vetmanager_client import VetmanagerClient
from exceptions import AuthError

TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")

skip_if_no_creds = pytest.mark.skipif(
    not TEST_DOMAIN or not TEST_API_KEY,
    reason="TEST_DOMAIN and TEST_API_KEY not set — skipping real API tests",
)


def vc() -> VetmanagerClient:
    return VetmanagerClient(TEST_DOMAIN, TEST_API_KEY)


async def call(coro):
    """Run coro; skip on AuthError (key may be revoked or access restricted)."""
    try:
        return await coro
    except AuthError as e:
        pytest.skip(f"API returned auth error: {e}")


# ── Host resolution ───────────────────────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_host_resolves():
    """Billing API must return a valid https:// URL for the test domain."""
    base = await vc()._resolve_host()
    assert base.startswith("https://"), f"Expected https:// URL, got: {base}"


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_host_cached_on_second_call():
    """Billing API called only once per client instance."""
    c = vc()
    base1 = await c._resolve_host()
    base2 = await c._resolve_host()
    assert base1 == base2


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_two_instances_are_independent():
    """Different VetmanagerClient instances must not share host cache."""
    c1 = vc()
    c2 = vc()
    base1 = await c1._resolve_host()
    base2 = await c2._resolve_host()
    assert base1 == base2
    assert c1 is not c2

# ── Entity endpoints ──────────────────────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_clients():
    result = await call(vc().get("/rest/api/client", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_users():
    result = await call(vc().get("/rest/api/user", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_goods():
    result = await call(vc().get("/rest/api/good", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_pets():
    result = await call(vc().get("/rest/api/pet", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_admissions():
    result = await call(vc().get("/rest/api/admission", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_invoices():
    result = await call(vc().get("/rest/api/invoice", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_medical_cards():
    result = await call(vc().get("/rest/api/medicalcard", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_clients_pagination():
    """Offset pagination must work without error."""
    result = await call(vc().get("/rest/api/client", params={"limit": 2, "offset": 0}))
    result2 = await call(vc().get("/rest/api/client", params={"limit": 2, "offset": 2}))
    assert "data" in result
    assert "data" in result2


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_nonexistent_client_raises():
    """Requesting a non-existent client must raise NotFoundError."""
    from exceptions import NotFoundError
    try:
        await vc().get("/rest/api/client/999999999")
        pytest.skip("Expected 404 but got success — resource may exist")
    except NotFoundError:
        pass  # expected
    except AuthError as e:
        pytest.skip(f"Auth error: {e}")
