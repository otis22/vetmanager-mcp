# PRD Этап 5: CI/CD и политика секретов

## Цель
GitHub Actions: unit + mock e2e на каждый push/PR без реальных ключей.
Real API тесты — только вручную или по расписанию с CI secrets.
Ключи никогда не попадают в репозиторий.

## Задачи

### 5.1 GitHub Actions: unit + mock тесты
- Workflow `.github/workflows/test.yml`
- Trigger: push, pull_request на main
- Запуск через `docker build` + `docker run` (не python на хосте)
- Ограничение: ≤ 40 строк

### 5.2-5.3 Политика секретов
- `.env` в `.gitignore` (уже есть)
- TEST_API_KEY только в GitHub Secrets
- `.env.example` без реальных значений (уже готово)

### 5.4 Real API в CI (опционально)
- Отдельный workflow `test-real.yml` — ручной запуск
- Принимает TEST_API_KEY из GitHub Secrets

## Критерии готовности
- `docker build` + `docker run pytest` проходит в CI без секретов
- Real API тесты пропускаются в основном workflow (нет TEST_API_KEY)
