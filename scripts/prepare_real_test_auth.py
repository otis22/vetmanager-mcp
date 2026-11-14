"""Prepare missing user-token test settings without printing credentials."""

import asyncio
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host_resolver import resolve_vetmanager_host
from tests.live_test_lifecycle import close_loop_http_clients
from vetmanager_connection_service import exchange_user_token


async def prepare(path, require_all=False):
    values = {}
    try:
        required = ("TEST_DOMAIN", "TEST_API_KEY", "TEST_USER_LOGIN", "TEST_USER_PASSWORD")
        missing = [key for key in required if not os.environ.get(key)]
        if require_all and missing:
            print("Required real test settings missing: " + ", ".join(missing), file=sys.stderr)
            raise ValueError("Incomplete real test contour")
        if os.environ.get("TEST_USER_LOGIN") and os.environ.get("TEST_USER_PASSWORD"):
            if not os.environ.get("TEST_USER_TOKEN"):
                host, token = await exchange_user_token(
                    os.environ["TEST_DOMAIN"], login=os.environ["TEST_USER_LOGIN"],
                    password=os.environ["TEST_USER_PASSWORD"])
                values["TEST_USER_TOKEN"] = token
            else:
                host = await resolve_vetmanager_host(os.environ["TEST_DOMAIN"])
            values["TEST_USER_TOKEN_BASE_URL"] = host
        if any("\n" in value or "\r" in value for value in values.values()):
            raise ValueError("Unexpected credential format")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
    finally:
        await close_loop_http_clients()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(prepare(sys.argv[1], require_all="--require-all" in sys.argv[2:]))
    except Exception as exc:
        print(f"Test auth preparation failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
