FROM python:3.12-slim AS base

# Build args so files created in the container are owned by the host user,
# preventing permission issues with bind-mounted source code.
ARG UID=1000
ARG GID=1000
ARG ERROR_TRACKING_RELEASE=unknown

ENV ERROR_TRACKING_RELEASE=${ERROR_TRACKING_RELEASE}

RUN groupadd -g "${GID}" app && \
    useradd -u "${UID}" -g "${GID}" -m -s /bin/bash app

WORKDIR /app

# No apt step on purpose. `curl` was here only for the healthcheck below, and
# the image already carries a Python that can make the same request. Reaching
# deb.debian.org costs a build-time dependency on a network path this host does
# not have: 27.08.2026 the deploy failed twice because Fastly's IPv4 addresses
# time out from this VDS — the host itself only gets through over IPv6, which
# containers do not have.

# Production dependencies only
RUN pip install --no-cache-dir \
    "alembic>=1.13.0,<2" \
    "cryptography>=46.0.0,<47" \
    "fastmcp>=3.1.0,<4" \
    "httpx>=0.27.0,<1" \
    "sentry-sdk>=2.0.0,<3" \
    "sqlalchemy>=2.0.0,<3" \
    "aiosqlite>=0.20.0,<1" \
    "asyncpg>=0.29.0,<1" \
    "psycopg2-binary>=2.9.0,<3" \
    "redis>=5.0.0,<6"

# ── Production image ─────────────────────────────────────────────────────────
FROM base AS production

COPY . .

RUN mkdir -p /app/data /var/log/vetmanager-mcp && \
    chown app:app /app/data /var/log/vetmanager-mcp

USER app

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:%s/healthz' % os.environ.get('PORT','8000'), timeout=5).status == 200 else 1)" || exit 1

CMD ["python", "server.py"]

# ── Test image (includes Playwright, pytest, respx) ──────────────────────────
FROM base AS test

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN pip install --no-cache-dir \
    "playwright>=1.54.0,<2" \
    "pytest>=8.0.0,<9" \
    "pytest-asyncio>=0.23.0,<0.24" \
    "coverage>=7.6.0,<8" \
    "pytest-cov>=5.0.0,<6" \
    "respx>=0.21.0" \
    "fakeredis>=2.20.0,<3" \
    "ruff>=0.6.0,<1"

RUN python -m playwright install --with-deps chromium && \
    chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"

COPY . .

USER app

CMD ["python", "scripts/run_default_test_suite.py"]
