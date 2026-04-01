FROM python:3.12-slim AS base

# Build args so files created in the container are owned by the host user,
# preventing permission issues with bind-mounted source code.
ARG UID=1000
ARG GID=1000

RUN groupadd -g "${GID}" app && \
    useradd -u "${UID}" -g "${GID}" -m -s /bin/bash app

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Production dependencies only
RUN pip install --no-cache-dir \
    "alembic>=1.13.0" \
    "cryptography>=46.0.0" \
    "fastmcp>=2.0.0" \
    "httpx>=0.27.0" \
    "sentry-sdk>=2.0.0" \
    "sqlalchemy>=2.0.0" \
    "aiosqlite>=0.20.0" \
    "asyncpg>=0.29.0" \
    "psycopg2-binary>=2.9.0"

# ── Production image ─────────────────────────────────────────────────────────
FROM base AS production

COPY . .

RUN mkdir -p /app/data && chown app:app /app/data

USER app

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/healthz || exit 1

CMD ["python", "server.py"]

# ── Test image (includes Playwright, pytest, respx) ──────────────────────────
FROM base AS test

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN pip install --no-cache-dir \
    "playwright>=1.54.0,<2" \
    "pytest>=8.0.0,<9" \
    "pytest-asyncio>=0.23.0,<0.24" \
    "respx>=0.21.0"

RUN python -m playwright install --with-deps chromium && \
    chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"

COPY . .

USER app

CMD ["python", "scripts/run_default_test_suite.py"]
