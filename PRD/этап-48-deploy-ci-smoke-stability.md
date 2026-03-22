# PRD: Этап 48 — стабилизация production deploy CI smoke checks

## Контекст

После закрытия этапа 47 workflow `Tests` на `main` остаётся зелёным, но
downstream workflow `Deploy Prod` падает уже после успешного деплоя.
По логам GitHub Actions отказ происходит в `scripts/post_deploy_smoke_checks.sh`
при первом HTTP-запросе к локальному сервису сразу после рестарта контейнера:
`curl: (56) Recv failure: Connection reset by peer`.

Цель этапа — сделать post-deploy smoke contract устойчивым к короткому startup
окну после `docker compose up -d` и добавить диагностический контекст, который
позволяет быстро различать race старта и реальный crash приложения.

## Цель

- убрать ложноположительные падения `Deploy Prod` из-за раннего smoke-запроса;
- сохранить жёсткую проверку `/healthz`, `/readyz`, `/metrics` и `/mcp`;
- сделать логи deploy-пайплайна пригодными для triage без ручного SSH на сервер.

## Ограничения

- менять бизнес-логику приложения не требуется;
- правки должны ограничиться deploy/smoke scripts, документацией и тестами;
- подзадачи остаются небольшими: не более ~150 строк на инкремент.

## Декомпозиция

### 48.1 Локализация причины падения

- зафиксировать конкретные run id и шаг отказа в `AssumptionLog.md`;
- подтвердить, что проблема возникает после успешного container/TLS smoke и
  выглядит как startup race для первого HTTP-запроса.

### 48.2 Retry/grace для post-deploy smoke checks

- добавить в `scripts/post_deploy_smoke_checks.sh` ограниченный retry loop;
- ретраить network-level сбои и временно неготовые HTTP-ответы;
- дать управляемые env knobs для количества попыток и паузы между ними.

### 48.3 Deploy diagnostics

- при падении app smoke checks печатать полезный контекст:
  - `docker compose ps`;
  - свежие container logs;
  - причина провала последней HTTP-попытки.

### 48.4 Проверки

- добавить pytest regression tests для smoke script:
  - сервис поднимается с задержкой, smoke script в итоге проходит;
  - при исчерпании попыток ошибка содержит endpoint и curl/http контекст.
- прогнать shell syntax checks и targeted pytest.

### 48.5 Doc sync

- обновить `README.md` под новый retryable smoke contract;
- после успешного push перепроверить GitHub Actions и зафиксировать outcome в
  `Roadmap.md` и `AssumptionLog.md`.
