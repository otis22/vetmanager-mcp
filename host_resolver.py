"""Billing API host resolution for Vetmanager domains.

Resolves a clinic subdomain (e.g. "myclinic") to a validated HTTPS origin
(e.g. "https://myclinic.vetmanager.cloud") by querying the Vetmanager billing API.
"""

import asyncio
import time

import httpx

from exceptions import HostResolutionError, VetmanagerError, VetmanagerTimeoutError
from host_validation import validate_resolved_vetmanager_origin
from observability_logging import RUNTIME_LOGGER
from service_metrics import record_upstream_failure, record_upstream_request

BILLING_API = "https://billing-api.vetmanager.cloud/host/{domain}"
REQUEST_TIMEOUT = 30.0
_DEFAULT_MAX_RETRIES = 1


async def resolve_vetmanager_host(
    domain: str,
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> str:
    """Resolve clinic domain to validated HTTPS origin via billing API.

    Args:
        domain: Clinic subdomain (already validated).
        max_retries: Number of retry attempts on transient errors. 0 = no retry.

    Returns:
        Validated HTTPS origin string, e.g. ``"https://myclinic.vetmanager.cloud"``.

    Raises:
        HostResolutionError: Billing API returned unexpected response or HTTP error.
        VetmanagerTimeoutError: All attempts timed out.
        VetmanagerError: Network error after all retries.
    """
    url = BILLING_API.format(domain=domain)

    for attempt in range(max_retries + 1):
        started = time.monotonic()
        try:
            timeout = httpx.Timeout(REQUEST_TIMEOUT)
            async with httpx.AsyncClient(timeout=timeout) as http:
                response = await http.get(url)
                # Stage 107.7: latency metric for billing_api — previously
                # only failure counters recorded. Now SRE can see slow
                # host-resolution via `upstream_request_latency_seconds{target="billing_api"}`.
                elapsed = time.monotonic() - started
                record_upstream_request(
                    target="billing_api",
                    status=f"http_{response.status_code}",
                    duration_seconds=elapsed,
                )
                response.raise_for_status()
                data = response.json()
                host = data.get("data", {}).get("url") or data.get("url")
                if not host:
                    raise HostResolutionError(
                        f"Unexpected billing API response for domain '{domain}'."
                    )
                host = host.rstrip("/")
                if not host.startswith("http"):
                    host = f"https://{host}"
                validated = validate_resolved_vetmanager_origin(host, domain=domain)
                RUNTIME_LOGGER.debug(
                    "Resolved billing host.",
                    extra={
                        "event_name": "billing_host_resolved",
                        "domain": domain,
                        "resolved_host": validated,
                    },
                )
                return validated
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - started
            if attempt < max_retries:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            record_upstream_failure(target="billing_api", reason="timeout")
            record_upstream_request(
                target="billing_api", status="timeout", duration_seconds=elapsed,
            )
            raise VetmanagerTimeoutError(
                f"Timeout resolving host for domain '{domain}'"
            ) from exc
        except httpx.HTTPStatusError as exc:
            record_upstream_failure(
                target="billing_api",
                reason=f"http_{exc.response.status_code}",
            )
            raise HostResolutionError(
                f"Billing API returned {exc.response.status_code} for domain '{domain}'."
            ) from exc
        except httpx.RequestError as exc:
            elapsed = time.monotonic() - started
            if attempt < max_retries:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            record_upstream_failure(target="billing_api", reason="network_error")
            record_upstream_request(
                target="billing_api", status="network_error", duration_seconds=elapsed,
            )
            raise VetmanagerError(
                f"Network error resolving host for domain '{domain}': {exc}"
            ) from exc

    raise VetmanagerError(f"Failed to resolve host for domain '{domain}' after {max_retries + 1} attempts.")
