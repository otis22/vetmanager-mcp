# Этап 54. Инфраструктура: production hardening

**Цель:** подготовить инфраструктуру к production-деплою и устранить пробелы в контейнеризации.

---

## 54.1 Docker — `done`

- 54.1.1 Multi-stage build: `base` → `production` (без test deps) и `test` (с Playwright, pytest) — `done`
- 54.1.2 Добавить `HEALTHCHECK` инструкцию в Dockerfile (production stage) — `done`
- 54.1.3 Добавить resource limits (1 CPU, 512M memory) в docker-compose.yml — `done`
- 54.1.4 Добавить явный named volume `mcp-data` для SQLite data directory — `done`

## 54.2 Distributed state (Redis) — отложен

- 54.2.1 Redis-backed rate limiter для multi-worker — `todo` (single-process достаточно)
- 54.2.2 Request cache на Redis — `todo`
- 54.2.3 account_id в ключе кэша — `todo`

---

## Решения и допущения

- Multi-stage Docker: base (общие deps) → production (COPY + CMD server.py) → test (+ Playwright/pytest)
- HEALTHCHECK: `curl -f http://localhost:8000/healthz`, interval 30s, start-period 10s
- Resource limits консервативные для single-process Python
- Named volume `mcp-data` заменяет bind mount `./data`
- Redis отложен — текущая нагрузка single-process
