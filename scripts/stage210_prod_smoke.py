#!/usr/bin/env python3
"""Stage 210 production smoke check for the landing page and account cabinet.

Verifies what the stage actually changed, on the deployed site:
public pages answer 200, the landing states the service is free and carries a
single <h1>, and the cabinet — reached with the smoke account — no longer shows
English UI strings to a Russian-speaking clinic.

Read-only: it logs in, reads two pages and logs out. It never registers an
account, issues or revokes a key, disconnects an assistant, or prints secrets.

Usage:
    STAGE208_SMOKE_EMAIL=... STAGE208_SMOKE_PASSWORD=... \\
        python scripts/stage210_prod_smoke.py [BASE_URL]
"""

from __future__ import annotations

import os
import re
import sys
from html.parser import HTMLParser

import httpx

DEFAULT_BASE_URL = "https://vetmanager-mcp.vromanichev.ru"

PUBLIC_PATHS = ("/", "/register", "/login", "/healthz", "/readyz")

# Strings the cabinet used to show a clinic admin in English.
FORBIDDEN_CABINET_TEXT = (
    "ChatGPT connections",
    "Full access",
    "Read only",
    "Legacy/custom",
    "Custom/legacy",
    "Revoke",
    "Disconnect",
    "Actions",
    "Details",
    "Never",
    "No expiry",
    "Depersonalized",
    "Privacy и auth transparency",
)

# Wording that would promise a tariff later; the service is free, full stop.
FORBIDDEN_LANDING_TEXT = ("тариф", "пробный", "триал", "подписк", "пока бесплатно", "без карты")


class _VisibleText(HTMLParser):
    """Collect what a person reads: text nodes outside script and style."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chunks.append(data)


def visible_text(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return " ".join(" ".join(parser.chunks).split())


class SmokeReport:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.checks = 0

    def check(self, condition: bool, description: str) -> None:
        self.checks += 1
        status = "ok  " if condition else "FAIL"
        print(f"  [{status}] {description}")
        if not condition:
            self.failures.append(description)


def main() -> int:
    base_url = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL).rstrip("/")
    email = os.environ.get("STAGE208_SMOKE_EMAIL", "").strip().strip("'\"")
    password = os.environ.get("STAGE208_SMOKE_PASSWORD", "").strip().strip("'\"")
    if not email or not password:
        print("Missing STAGE208_SMOKE_EMAIL / STAGE208_SMOKE_PASSWORD.", file=sys.stderr)
        return 2

    report = SmokeReport()
    print(f"Stage 210 production smoke against {base_url}\n")

    print("Public pages")
    with httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=True) as client:
        for path in PUBLIC_PATHS:
            try:
                response = client.get(path)
                report.check(response.status_code == 200, f"GET {path} -> {response.status_code}")
            except httpx.HTTPError as exc:
                report.check(False, f"GET {path} raised {type(exc).__name__}")

        landing = client.get("/").text
        landing_text = visible_text(landing)

        print("\nLanding")
        report.check(landing.count("<h1") == 1, "exactly one <h1>")
        report.check("Бесплатно" in landing_text, "states the service is free")
        report.check('id="developer-onboarding"' in landing, "technical block present")
        block = landing[landing.find('id="developer-onboarding"') :]
        block = block[: block.find("</details>")]
        report.check('class="chev"' in block, "technical block has a chevron")
        report.check('class="ic-pre"' in block, "technical block has a leading icon")
        report.check("Как начать работу" not in landing, "duplicated start section removed")
        report.check("Примеры задач по ролям" not in landing, "duplicated role cards removed")
        report.check(landing.count("mcpServers") == 1, "connection config appears once")
        report.check('class="flow-map"' in landing, "flow diagram is public")
        for word in FORBIDDEN_LANDING_TEXT:
            report.check(word not in landing_text.lower(), f"no billing hint {word!r}")

        print("\nCabinet")
        login_page = client.get("/login")
        csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text)
        payload = {"email": email, "password": password}
        if csrf:
            payload["csrf_token"] = csrf.group(1)
        account = client.post("/login", data=payload)
        report.check(account.status_code == 200, f"login -> {account.status_code}")
        report.check(str(account.url).endswith("/account"), f"landed on {account.url.path}")

        if str(account.url).endswith("/account"):
            cabinet_text = visible_text(account.text)
            for phrase in FORBIDDEN_CABINET_TEXT:
                report.check(phrase not in cabinet_text, f"cabinet does not show {phrase!r}")
            report.check("Мой помощник" in cabinet_text, "cabinet heading rendered")
            report.check('class="account-topbar"' in account.text, "cabinet has a header")
            report.check("data-local-time" in account.text, "timestamps are localisable")
            report.check(
                'class="danger"' in account.text or "Ключей пока нет" in cabinet_text,
                "destructive actions use the danger style",
            )

        client.post("/logout", data={"csrf_token": csrf.group(1)} if csrf else {})

    print(f"\n{report.checks - len(report.failures)}/{report.checks} checks passed")
    if report.failures:
        print("\nFailed:")
        for failure in report.failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
