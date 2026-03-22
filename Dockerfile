FROM python:3.12-slim

# Build args so files created in the container are owned by the host user,
# preventing permission issues with bind-mounted source code.
ARG UID=1000
ARG GID=1000

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN groupadd -g "${GID}" app && \
    useradd -u "${UID}" -g "${GID}" -m -s /bin/bash app

WORKDIR /app

COPY pyproject.toml ./

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install all dependencies (prod + dev) via pip — no uv needed on the host.
RUN pip install --no-cache-dir \
    "alembic>=1.13.0" \
    "cryptography>=46.0.0" \
    "fastmcp>=2.0.0" \
    "httpx>=0.27.0" \
    "sentry-sdk>=2.0.0" \
    "sqlalchemy>=2.0.0" \
    "aiosqlite>=0.20.0" \
    "asyncpg>=0.29.0" \
    "playwright>=1.54.0,<2" \
    "pytest>=8.0.0,<9" \
    "pytest-asyncio>=0.23.0,<0.24" \
    "respx>=0.21.0"

RUN python -m playwright install --with-deps chromium && \
    chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"

COPY . .

USER app

CMD ["python", "server.py"]
