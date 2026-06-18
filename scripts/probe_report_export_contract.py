"""Opt-in real API probe for Vetmanager report export endpoints.

Requires TEST_DOMAIN, TEST_API_KEY, and REPORT_EXPORT_PROBE_REPORT_ID.
Optionally accepts REPORT_EXPORT_PROBE_FILE_ID to probe reportFile directly.
The script does not print secrets or file locator values.
"""

from __future__ import annotations

import os
import sys
import time

import httpx


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for report export probe.")
    return value


def _host(domain: str) -> str:
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/")
    if "." in domain:
        return f"https://{domain.strip('/')}"
    response = httpx.get(f"https://billing-api.vetmanager.cloud/host/{domain}", timeout=15.0)
    response.raise_for_status()
    payload = response.json()
    url = payload.get("data", {}).get("url") if isinstance(payload.get("data"), dict) else None
    url = url or payload.get("url")
    if not isinstance(url, str) or not url:
        raise RuntimeError("Billing host resolver did not return data.url.")
    if not url.startswith("http"):
        url = f"https://{url}"
    return url.rstrip("/")


def _get(client: httpx.Client, path: str, params: dict[str, object]) -> dict:
    response = client.get(path, params=params)
    try:
        payload = response.json()
    except ValueError:
        payload = {"success": False, "message": "<non-json response>"}
    if response.status_code >= 400:
        message = payload.get("message") if isinstance(payload, dict) else None
        raise RuntimeError(f"{path} returned HTTP {response.status_code}: {message or '<no message>'}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} returned non-object JSON.")
    return payload


def main() -> int:
    domain = _required_env("TEST_DOMAIN")
    api_key = _required_env("TEST_API_KEY")
    report_id = int(_required_env("REPORT_EXPORT_PROBE_REPORT_ID"))
    file_id_env = os.environ.get("REPORT_EXPORT_PROBE_FILE_ID", "").strip()

    headers = {"X-REST-API-KEY": api_key}
    with httpx.Client(base_url=_host(domain), headers=headers, timeout=30.0) as client:
        started = _get(client, "/rest/api/report/StartReport", {"report_id": report_id})
        report = started.get("data", {}).get("report") if isinstance(started.get("data"), dict) else None
        report_file_id = None
        if isinstance(report, dict):
            report_file_id = report.get("report_file_id")
        if not report_file_id:
            raise RuntimeError("StartReport response did not include data.report.report_file_id.")
        print("StartReport: ok, data.report.report_file_id present")

        file_id = int(file_id_env or report_file_id)
        file_payload = None
        for attempt in range(1, 7):
            try:
                file_payload = _get(client, "/rest/api/report/reportFile", {"file_id": file_id})
                break
            except RuntimeError as exc:
                text = str(exc).lower()
                if "build in progress" not in text and "not started" not in text:
                    raise
                if attempt == 1:
                    print("reportFile: not ready yet, transient response confirmed")
                if attempt == 6:
                    print("reportFile: still not ready after polling; file fields not confirmed")
                    return 0
                time.sleep(5)
        if file_payload is None:
            raise RuntimeError("reportFile probe did not produce a response.")
        file_report = (
            file_payload.get("data", {}).get("report")
            if isinstance(file_payload.get("data"), dict)
            else None
        )
        if not isinstance(file_report, dict):
            raise RuntimeError("reportFile response did not include data.report object.")
        present = [
            name
            for name in ("html_file", "csv_file", "csv_semicolon_file", "xlsx_file")
            if file_report.get(name)
        ]
        if not present:
            raise RuntimeError("reportFile response did not include export file fields.")
        print("reportFile: ok, export file fields present: " + ", ".join(present))
        print("Privacy: file locator values intentionally not printed; treat as sensitive.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
