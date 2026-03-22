# Operations Readiness: vetmanager-mcp

Дата: 2026-03-22

## 1. Backup / Restore

### SQLite runtime

Что бэкапить:
- файл БД из `DATABASE_URL` / локально по умолчанию `./data/vetmanager.db`
- `.env`
- deployment scripts и nginx config, если они были локально изменены

Минимальная стратегия:
- ежедневный snapshot файла БД
- перед deploy и перед rotation секретов — отдельный ad-hoc backup
- хранить минимум 7 daily + 4 weekly snapshot’а

Restore:
1. остановить сервис `docker compose down`
2. восстановить файл БД
3. убедиться, что `.env` и secrets соответствуют состоянию БД
4. поднять сервис `docker compose up -d`
5. прогнать `scripts/post_deploy_smoke_checks.sh`

### PostgreSQL runtime

Что бэкапить:
- logical dump (`pg_dump`) или managed snapshot
- `.env`

Минимальная стратегия:
- ежедневный logical backup
- retention минимум 7 daily + 4 weekly
- отдельный pre-release dump перед schema changes

Restore:
1. восстановить dump/snapshot
2. проверить `DATABASE_URL`
3. поднять сервис
4. прогнать smoke checks

## 2. Secret Rotation Policy

### `WEB_SESSION_SECRET`

- rotation требует coordinated deploy на всех instance
- после rotation все существующие web sessions становятся невалидны
- выполнять в planned maintenance window

### `STORAGE_ENCRYPTION_KEY`

- не ротировать без отдельной процедуры re-encryption
- пока baseline policy: treat as high-stability secret
- если компрометация подтверждена:
  - перевыпустить secret
  - потребовать повторную настройку Vetmanager integration
  - перевыпустить service bearer tokens

### `ERROR_TRACKING_DSN`

- rotation low-risk
- достаточно обновить env и перезапустить сервис

### Service bearer tokens

- rotation supported at product level через web account console
- при подозрении на компрометацию: revoke + issue new token

## 3. Migration / Rollback Policy

- schema changes проходят только через Alembic migrations
- перед release со schema changes обязателен backup
- rollback допустим только если migration обратима и это явно проверено
- если migration необратима, rollback делается restore из backup + redeploy старой версии

Рекомендуемый порядок:
1. backup
2. deploy code
3. run migrations
4. run smoke checks
5. открыть traffic

## 4. Release / Deploy SLO baseline

Минимальный operational baseline:
- `/healthz` availability: 99.9%
- `/readyz` steady-state success: 99.5%
- p95 web request latency для `/login`, `/register`, `/account`: < 1.0s
- `vetmanager_upstream_failures_total` не должен иметь sustained growth без инцидента/maintenance

## 5. Alerting Thresholds

Базовые thresholds:
- `/healthz` failed 2 раза подряд: critical
- `/readyz` failed 2 раза подряд: high
- любой sustained рост `billing_api` или `vetmanager_api` failures > 5/min 5 минут подряд: high
- заметный рост `auth_failures_total{source="web_rate_limit",...}`: investigate brute-force/abuse
- заметный рост `auth_failures_total{source="bearer_header",...}`: investigate client config drift

## 6. Deploy Procedure

- использовать `scripts/deploy_server.sh`
- для private repo path использовать `scripts/sync_and_deploy_server.sh`
- после restart обязательно:
  - `/healthz`
  - `/readyz`
  - `/metrics`
  - `/mcp`
  проходят через `scripts/post_deploy_smoke_checks.sh`
