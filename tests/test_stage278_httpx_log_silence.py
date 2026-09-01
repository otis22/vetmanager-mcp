"""Stage 278 — the address we download from must not land in our log file.

Stage 276 kept our own signed export path out of the access log and out of
Sentry. The live run on 01.09.2026 showed what it missed: the address on the
other side is logged by `httpx` itself, at INFO, and production runs at INFO
with a persistent log file on disk.

That address is a public link to the *unsanitized* export — the file with every
name and phone number in it, served to anyone who has the link.
"""

from __future__ import annotations

import logging

from structured_logging import configure_logging


def test_httpx_does_not_write_request_addresses_into_our_log():
    configure_logging()

    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)


def test_a_transport_failure_is_still_visible():
    configure_logging()

    assert logging.getLogger("httpx").isEnabledFor(logging.WARNING)


def test_the_address_of_an_export_never_reaches_a_record(caplog):
    """The guard the stage exists for: an INFO line from httpx carrying a
    locator produces no record at all."""
    configure_logging()

    with caplog.at_level(logging.DEBUG):
        logging.getLogger("httpx").info(
            'HTTP Request: GET https://cdn.example/vetmanager-public-user-files/'
            'clinic/export.csv "HTTP/1.1 200 OK"'
        )

    assert "vetmanager-public-user-files" not in caplog.text
