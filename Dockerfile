ARG BASE_IMAGE=ghcr.io/otis22/python:3.12-slim@sha256:139b146ecf6cadf1960a88887c83846bd030bf1bc0a478fae48215c49917c075
FROM ${BASE_IMAGE} AS base

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

COPY requirements/production.txt /tmp/production-requirements.txt
RUN pip install --require-hashes --timeout 120 --no-cache-dir -r /tmp/production-requirements.txt

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

COPY requirements/test.txt /tmp/test-requirements.txt
RUN pip install --require-hashes --timeout 120 --no-cache-dir -r /tmp/test-requirements.txt

# Node из Playwright требует libatomic ещё до установки зависимостей браузера.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libatomic1 && \
    rm -rf /var/lib/apt/lists/* && \
    python -m playwright install --with-deps chromium && \
    chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"

COPY . .

USER app

CMD ["python", "scripts/run_default_test_suite.py"]
