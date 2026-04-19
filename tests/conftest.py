"""Shared pytest fixtures for browser-level tests."""

import asyncio
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
import threading
import time

import httpx
import pytest
import pytest_asyncio
from playwright.sync_api import Page, sync_playwright
import respx
import storage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
import uvicorn
from request_cache import REQUEST_CACHE
from server import mcp
from storage import Base, create_database_engine, get_session_factory
from storage_models import Account, ServiceBearerToken, TokenUsageLog, TokenUsageStat, VetmanagerConnection
from web_security import reset_web_security_state


@pytest.fixture(autouse=True)
def _clear_request_cache():
    """Clear the global request cache before each test to prevent cross-test contamination."""
    REQUEST_CACHE._entries.clear()
    REQUEST_CACHE._tag_index.clear()
    yield
    REQUEST_CACHE._entries.clear()
    REQUEST_CACHE._tag_index.clear()


@pytest.fixture(autouse=True)
def _reset_service_metrics_state():
    """Stage 115.3: clear process-global service_metrics counters before
    each test to prevent leakage (business_events_total, auth_failures,
    upstream requests etc.). Stage 110 tests called this manually; this
    autouse fixture makes it impossible to forget.
    """
    from service_metrics import reset_service_metrics
    reset_service_metrics()
    yield
    reset_service_metrics()


@pytest_asyncio.fixture(autouse=True)
async def _reset_billing_resolver_state():
    """Stage 113.F7: drop billing-api resolver cache + shared client between
    tests. Without this, the first test to successfully resolve a domain
    poisons subsequent tests expecting respx mocks to be hit.
    """
    from host_resolver import reset_billing_resolver
    await reset_billing_resolver()
    yield
    await reset_billing_resolver()


@pytest.fixture(autouse=True)
def _reset_vm_client_state():
    """Reset shared httpx.AsyncClient and per-domain circuit breakers between tests.

    Stage 91 introduced module-level shared state (singleton client + breaker
    registry). respx patches httpx globally, but shared client state carries
    open-breaker flags or keep-alive connections across tests unless reset.

    We drop references synchronously instead of awaiting close() — the default
    test suite runs with `-W error`, which would promote any ResourceWarning
    from asyncio bookkeeping into a test failure. Dropping the ref lets GC
    handle the cleanup and avoids creating an extra event loop here.
    """
    import vetmanager_client as _vm_client

    def _drop() -> None:
        # Stage 99.4: per-loop client dict — clear all entries.
        # Stage 106.7: `_shared_http_client` sentinel removed; dict clear is
        # the only state reset needed.
        _vm_client._shared_http_clients.clear()
        _vm_client._breakers.clear()

    _drop()
    yield
    _drop()

TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


@dataclass
class DeterministicUpstreamMock:
    """State holder for deterministic Vetmanager upstream auth mocks."""

    domain: str
    resolved_host: str
    api_key: str | None = None
    user_token: str | None = None
    app_name: str = "vetmanager-mcp"
    login: str | None = None
    password: str | None = None
    billing_route: object | None = None
    token_auth_route: object | None = None
    validation_route: object | None = None
    token_exchange_requests: list[httpx.Request] = field(default_factory=list)
    validation_requests: list[httpx.Request] = field(default_factory=list)


@dataclass
class BrowserCleanupReport:
    """Snapshot of browser-test database residue before and after cleanup."""

    deleted_accounts: int
    before: dict[str, int]
    after: dict[str, int]


class BrowserAccountCleanup:
    """Track browser-created accounts and remove all related records via ORM cascades."""

    def __init__(self) -> None:
        self._tracked_emails: set[str] = set()
        self.last_report: BrowserCleanupReport | None = None

    def track_account_email(self, email: str) -> None:
        normalized_email = email.strip().lower()
        if normalized_email:
            self._tracked_emails.add(normalized_email)

    async def _count_entities(self) -> dict[str, int]:
        async with get_session_factory()() as session:
            return {
                "accounts": int(
                    (await session.scalar(select(func.count()).select_from(Account))) or 0
                ),
                "vetmanager_connections": int(
                    (await session.scalar(select(func.count()).select_from(VetmanagerConnection))) or 0
                ),
                "service_bearer_tokens": int(
                    (await session.scalar(select(func.count()).select_from(ServiceBearerToken))) or 0
                ),
                "token_usage_stats": int(
                    (await session.scalar(select(func.count()).select_from(TokenUsageStat))) or 0
                ),
                "token_usage_logs": int(
                    (await session.scalar(select(func.count()).select_from(TokenUsageLog))) or 0
                ),
            }

    async def _cleanup_async(self) -> BrowserCleanupReport:
        before = await self._count_entities()
        deleted_accounts = 0

        if self._tracked_emails:
            async with get_session_factory()() as session:
                accounts = (
                    await session.execute(
                        select(Account).where(Account.email.in_(sorted(self._tracked_emails)))
                    )
                ).scalars().all()
                for account in accounts:
                    await session.delete(account)
                    deleted_accounts += 1
                await session.commit()
            self._tracked_emails.clear()

        after = await self._count_entities()
        report = BrowserCleanupReport(
            deleted_accounts=deleted_accounts,
            before=before,
            after=after,
        )
        self.last_report = report
        return report

    def cleanup_now(self) -> BrowserCleanupReport:
        report = _run_coro_in_thread(self._cleanup_async())
        assert isinstance(report, BrowserCleanupReport)
        return report


def _build_http_app():
    return mcp.http_app(path="/mcp", transport="streamable-http")


def _dispose_engine_sync(engine) -> None:
    _run_coro_in_thread(engine.dispose())


def _run_coro_in_thread(coro):
    error: list[BaseException] = []
    result: list[object] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # pragma: no cover - escalated back to fixture caller
            error.append(exc)

    worker = threading.Thread(target=_runner, name="pytest-async-fixture-worker", daemon=True)
    worker.start()
    worker.join()
    if error:
        raise error[0]
    if result:
        return result[0]
    return None


@pytest.fixture
def prepared_web_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Prepare isolated SQLite storage and web security state for live web tests."""
    database_path = tmp_path / "browser-live.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("WEB_SESSION_SECRET", "browser-live-session-secret")
    monkeypatch.setenv("WEB_SESSION_SECURE", "0")
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)

    storage.reset_storage_state()
    reset_web_security_state()

    engine = create_database_engine(f"sqlite:///{database_path}")
    async def _bootstrap() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    _run_coro_in_thread(_bootstrap())

    try:
        yield database_path
    finally:
        _dispose_engine_sync(engine)
        storage.reset_storage_state()
        reset_web_security_state()


@pytest.fixture
def upstream_mock_router():
    """Patch httpx process-wide so live server requests also hit deterministic mocks."""
    router = respx.mock(assert_all_mocked=True, assert_all_called=False)
    router.route(host="127.0.0.1").pass_through()
    router.route(host="localhost").pass_through()
    router.start()
    try:
        yield router
    finally:
        router.stop()
        router.reset()


@pytest.fixture
def mock_domain_api_key_upstream(upstream_mock_router):
    """Create deterministic billing + API-key validation mocks for one clinic."""

    def _factory(
        *,
        domain: str = "browser-api-key-clinic",
        resolved_host: str | None = None,
        api_key: str = "browser-api-key-secret",
    ) -> DeterministicUpstreamMock:
        host = resolved_host or f"https://{domain}.vetmanager.cloud"
        state = DeterministicUpstreamMock(
            domain=domain,
            resolved_host=host.rstrip("/"),
            api_key=api_key,
        )

        def _capture_validation(request: httpx.Request) -> httpx.Response:
            state.validation_requests.append(request)
            return httpx.Response(200, json={"data": []})

        state.billing_route = upstream_mock_router.get(
            f"https://billing-api.vetmanager.cloud/host/{domain}"
        ).mock(return_value=httpx.Response(200, json={"data": {"url": state.resolved_host}}))
        state.validation_route = upstream_mock_router.get(
            f"{state.resolved_host}/rest/api/client"
        ).mock(side_effect=_capture_validation)
        return state

    return _factory


@pytest.fixture
def mock_user_token_upstream(upstream_mock_router):
    """Create deterministic billing + token exchange + token validation mocks."""

    def _factory(
        *,
        domain: str = "browser-user-token-clinic",
        resolved_host: str | None = None,
        login: str = "browser-doctor",
        password: str = "browser-password-123",
        user_token: str = "browser-issued-user-token",
        app_name: str = "vetmanager-mcp",
    ) -> DeterministicUpstreamMock:
        host = resolved_host or f"https://{domain}.vetmanager.cloud"
        state = DeterministicUpstreamMock(
            domain=domain,
            resolved_host=host.rstrip("/"),
            login=login,
            password=password,
            user_token=user_token,
            app_name=app_name,
        )

        def _capture_token_exchange(request: httpx.Request) -> httpx.Response:
            state.token_exchange_requests.append(request)
            return httpx.Response(200, json={"data": {"token": state.user_token}})

        def _capture_validation(request: httpx.Request) -> httpx.Response:
            state.validation_requests.append(request)
            return httpx.Response(200, json={"data": []})

        state.billing_route = upstream_mock_router.get(
            f"https://billing-api.vetmanager.cloud/host/{domain}"
        ).mock(return_value=httpx.Response(200, json={"data": {"url": state.resolved_host}}))
        state.token_auth_route = upstream_mock_router.post(
            f"{state.resolved_host}/token_auth.php"
        ).mock(side_effect=_capture_token_exchange)
        state.validation_route = upstream_mock_router.get(
            f"{state.resolved_host}/rest/api/user"
        ).mock(side_effect=_capture_validation)
        return state

    return _factory


@pytest.fixture
def live_server_url(prepared_web_db, free_tcp_port: int) -> Generator[str, None, None]:
    """Run the app on a real localhost HTTP port for browser-level navigation."""
    app = _build_http_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=free_tcp_port,
        log_level="warning",
        access_log=False,
        ws="none",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="pytest-live-http-server", daemon=True)
    thread.start()

    deadline = time.time() + 10.0
    while not getattr(server, "started", False):
        if not thread.is_alive():
            raise RuntimeError("Live HTTP test server stopped before startup completed.")
        if time.time() >= deadline:
            raise RuntimeError("Timed out waiting for live HTTP test server startup.")
        time.sleep(0.05)

    try:
        yield f"http://127.0.0.1:{free_tcp_port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)
        if thread.is_alive():
            raise RuntimeError("Live HTTP test server did not stop cleanly.")


@pytest.fixture
def browser_account_cleanup(prepared_web_db) -> Generator[BrowserAccountCleanup, None, None]:
    """Cleanup helper for browser tests that create real account-linked rows."""
    helper = BrowserAccountCleanup()
    try:
        yield helper
    finally:
        helper.cleanup_now()


@pytest_asyncio.fixture
async def sqlite_session_factory_builder():
    """Build disposable SQLite session factories for async tests."""
    engines = []

    async def _build(database_path: Path) -> async_sessionmaker:
        engine = create_database_engine(f"sqlite:///{database_path}")
        engines.append(engine)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    try:
        yield _build
    finally:
        for engine in reversed(engines):
            await engine.dispose()


@pytest.fixture
def run_async():
    """Run async project calls safely from sync browser/live tests."""
    return _run_coro_in_thread


@pytest.fixture
def browser_name() -> str:
    """Return the default browser used by the project browser stack."""
    return "chromium"


@pytest.fixture
def page(browser_name: str) -> Generator[Page, None, None]:
    """Provide an isolated Playwright page without loading external plugins."""
    with sync_playwright() as playwright:
        browser_launcher = getattr(playwright, browser_name)
        browser = browser_launcher.launch()
        context = browser.new_context()
        current_page = context.new_page()
        try:
            yield current_page
        finally:
            context.close()
            browser.close()
