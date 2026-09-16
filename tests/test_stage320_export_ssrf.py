"""Stage 320.1 — export locators cannot choose an internal destination."""

from __future__ import annotations

import importlib
from pathlib import Path

import httpcore
import httpx
import pytest


PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
ORIGIN = "https://files.example"
LOCATOR = f"{ORIGIN}/private/report.csv?signature=not-for-output"


def _subject():
    return importlib.import_module("report_export_transport")


async def _resolve(*addresses: str):
    return addresses


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "locator",
    [
        "http://files.example/report.csv",
        "https://user@files.example/report.csv",
        "https://user:pass@files.example/report.csv",
        "https://files.example:444/report.csv",
    ],
)
async def test_locator_rejects_invalid_scheme_userinfo_and_port(locator, monkeypatch):
    monkeypatch.delenv("REPORT_EXPORT_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(Exception, match="security policy") as error:
        await _subject().resolve_export_target(locator, resolver=lambda _: _resolve(PUBLIC_V4))

    assert "report.csv" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.2.3.4",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "fd00::1",
        "fe80::1",
        "ff02::1",
        "::",
        "100.64.0.1",
        "192.0.2.1",
    ],
)
async def test_locator_rejects_every_non_global_dns_answer(address, monkeypatch):
    monkeypatch.delenv("REPORT_EXPORT_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(Exception, match="security policy") as error:
        await _subject().resolve_export_target(LOCATOR, resolver=lambda _: _resolve(address))

    assert "signature" not in str(error.value)
    assert address not in str(error.value)


@pytest.mark.asyncio
async def test_locator_rejects_mixed_public_and_private_dns_answers(monkeypatch):
    monkeypatch.delenv("REPORT_EXPORT_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(Exception, match="security policy"):
        await _subject().resolve_export_target(
            LOCATOR,
            resolver=lambda _: _resolve(PUBLIC_V4, "10.0.0.8", PUBLIC_V6),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [None, "", "   "])
async def test_unset_or_blank_allowlist_blocks_nothing(configured, monkeypatch):
    if configured is None:
        monkeypatch.delenv("REPORT_EXPORT_ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("REPORT_EXPORT_ALLOWED_ORIGINS", configured)

    target = await _subject().resolve_export_target(
        LOCATOR, resolver=lambda _: _resolve(PUBLIC_V4, PUBLIC_V6)
    )

    assert target.origin == ORIGIN
    assert target.addresses == (PUBLIC_V4, PUBLIC_V6)


@pytest.mark.asyncio
async def test_explicit_allowlist_is_exact_but_default_port_is_canonical(monkeypatch):
    monkeypatch.setenv(
        "REPORT_EXPORT_ALLOWED_ORIGINS",
        "https://FILES.example:443,https://other.example",
    )

    target = await _subject().resolve_export_target(
        LOCATOR, resolver=lambda _: _resolve(PUBLIC_V4)
    )

    assert target.origin == ORIGIN


@pytest.mark.asyncio
async def test_foreign_origin_is_rejected_without_echoing_locator(monkeypatch):
    monkeypatch.setenv("REPORT_EXPORT_ALLOWED_ORIGINS", "https://allowed.example")

    with pytest.raises(Exception) as error:
        await _subject().resolve_export_target(
            LOCATOR, resolver=lambda _: _resolve(PUBLIC_V4)
        )

    message = str(error.value)
    assert message == "Export origin is not in allowlist: https://files.example."
    assert "/private/" not in message
    assert "signature" not in message


@pytest.mark.parametrize(
    "configured",
    [
        "http://files.example",
        "https://user@files.example",
        "https://files.example:444",
        "https://files.example/path",
        "https://*.example",
        "https://files.example?x=1",
    ],
)
def test_nonempty_malformed_allowlist_fails_closed(configured):
    with pytest.raises(Exception, match="REPORT_EXPORT_ALLOWED_ORIGINS"):
        _subject().parse_allowed_origins(configured)


class _RecordingStream(httpcore.AsyncNetworkStream):
    def __init__(self):
        self.server_hostname = None
        self.writes: list[bytes] = []
        self._answered = False

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if self._answered:
            return b""
        self._answered = True
        return b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.writes.append(buffer)

    async def aclose(self) -> None:
        return None

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.server_hostname = server_hostname
        return self

    def get_extra_info(self, info: str):
        return None


class _RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self.connect_hosts: list[str] = []
        self.stream = _RecordingStream()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connect_hosts.append(host)
        return self.stream

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise AssertionError("unix sockets are not used")

    async def sleep(self, seconds):
        return None


@pytest.mark.asyncio
async def test_transport_pins_tcp_but_preserves_host_and_tls_sni(monkeypatch):
    monkeypatch.delenv("REPORT_EXPORT_ALLOWED_ORIGINS", raising=False)
    subject = _subject()
    target = await subject.resolve_export_target(
        LOCATOR, resolver=lambda _: _resolve(PUBLIC_V4)
    )
    backend = _RecordingBackend()
    transport = subject.PinnedExportTransport(target, network_backend=backend)

    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get(LOCATOR)

    assert response.status_code == 200
    assert backend.connect_hosts == [PUBLIC_V4]
    assert backend.stream.server_hostname == "files.example"
    request_bytes = b"".join(backend.stream.writes)
    assert b"Host: files.example" in request_bytes
    assert b"signature=not-for-output" in request_bytes


def test_origin_allowlist_env_is_wired_without_a_default_value():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    example = Path(".env.example").read_text(encoding="utf-8")

    assert "- REPORT_EXPORT_ALLOWED_ORIGINS" in compose
    assert "# REPORT_EXPORT_ALLOWED_ORIGINS=" in example
    assert "REPORT_EXPORT_ALLOWED_ORIGINS=https://" not in compose
    assert "REPORT_EXPORT_ALLOWED_ORIGINS=https://" not in example


def test_httpcore_is_a_direct_bounded_dependency():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert '"httpcore>=1.0.9,<2"' in pyproject
    assert '"httpcore>=1.0.9,<2"' in dockerfile
