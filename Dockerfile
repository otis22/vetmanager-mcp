FROM python:3.12-slim

# Build args so files created in the container are owned by the host user,
# preventing permission issues with bind-mounted source code.
ARG UID=1000
ARG GID=1000

RUN groupadd -g "${GID}" app && \
    useradd -u "${UID}" -g "${GID}" -m -s /bin/bash app

WORKDIR /app

COPY pyproject.toml ./

# Install all dependencies (prod + dev) via pip — no uv needed on the host.
RUN pip install --no-cache-dir \
    "fastmcp>=2.0.0" \
    "httpx>=0.27.0" \
    "sqlalchemy>=2.0.0" \
    "aiosqlite>=0.20.0" \
    "asyncpg>=0.29.0" \
    "pytest>=8.0.0" \
    "pytest-asyncio>=0.23.0" \
    "respx>=0.21.0"

COPY . .

USER app

CMD ["python", "server.py"]
