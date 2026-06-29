# Этап 181. GitHub Actions Node.js 20 deprecation warnings

## Контекст

GitHub Actions runs от 2026-06-25 (`Tests` и `Deploy Prod`) показывают
annotation:

```text
Node.js 20 is deprecated. The following actions target Node.js 20 but are being
forced to run on Node.js 24: actions/checkout@v4.
```

Runtime сервиса не падает, но warning загрязняет CI/deploy signal и будет
повторяться на каждом запуске, пока workflow использует action, объявленный под
Node.js 20.

## Проверенные факты

- В репозитории `actions/checkout@v4` используется в:
  - `.github/workflows/test.yml` — 2 раза;
  - `.github/workflows/deploy-prod.yml` — 1 раз;
  - `.github/workflows/test-real.yml` — 1 раз;
  - `.github/workflows/shellcheck.yml` — 1 раз.
- Других `actions/*@...` в workflow нет.
- Upstream `actions/checkout` README на 2026-06-29 указывает `Checkout v7` как
  актуальный usage example.
- `actions/checkout` v5 впервые перешёл на Node 24 runtime; текущий v7 также
  Node 24-compatible и документирует latest release `v7.0.0` от 2026-06-18.
- В затронутых workflow нет `pull_request_target` checkout пользовательского
  кода, поэтому новое security-поведение v7 про unsafe fork checkout не меняет
  текущий runtime path.

## Цель

Убрать GitHub Actions Node.js 20 deprecation annotation без изменения runtime
поведения сервиса, deploy-процесса и test contours.

## Scope

### In scope

- Обновить все occurrences `actions/checkout@v4` в `.github/workflows/*.yml`
  до текущего Node 24-compatible major `actions/checkout@v7`.
- Не менять параметры checkout, permissions, build/test/deploy команды и
  triggers.
- Зафиксировать решение в `Roadmap.md` и `AssumptionLog.md`.
- Добавить локальные проверки, что `checkout@v4` больше не встречается.

### Out of scope

- Перестройка CI/CD.
- Pinning actions по commit SHA.
- Изменение Docker build, test commands, deploy secrets или server runtime.
- Добавление новых GitHub Actions.
- Выполнение opt-in real API tests без явного запроса и secrets.

## Архитектурное решение

### Проблема

`actions/checkout@v4` объявлен как JavaScript action на Node 20. GitHub runner
уже может принудительно запускать его на Node 24, но всё равно выводит warning,
потому что metadata action остаётся Node 20.

### Выбранное решение

Заменить `actions/checkout@v4` на `actions/checkout@v7` во всех workflow.
Это минимальная правка: checkout action остаётся тем же официальным action,
inputs не меняются, а workflow получают Node 24-compatible metadata.

### Инварианты

- Workflow names и triggers не меняются.
- Docker image build args `UID=1001`, `GID=1001` не меняются.
- Test contours (`fast`, `default`, `test-real`) не меняются.
- Deploy secrets validation, SSH setup, rsync и remote deploy не меняются.
- ShellCheck workflow продолжает запускаться только на изменениях
  `scripts/**/*.sh`.

### Rollback/fallback

Если `actions/checkout@v7` неожиданно ломает GitHub-hosted runner workflow,
операционный rollback — вернуть `actions/checkout@v4` или временно откатиться
на `actions/checkout@v5` как первый Node 24-compatible major. Но v7 является
актуальным upstream usage на дату PRD и предпочтителен.

## Acceptance

- `rg "actions/checkout@v4" .github/workflows` ничего не находит.
- `rg "actions/checkout@v7" .github/workflows` находит все 5 checkout steps.
- `.github/workflows/test.yml`, `deploy-prod.yml`, `test-real.yml`,
  `shellcheck.yml` сохраняют прежние команды и triggers.
- `git diff --check` проходит.
- Workflow YAML parse/basic syntax check проходит локально.
- `Roadmap.md` stage 181 переведён в `done`.
- `AssumptionLog.md` содержит итог stage 181.
- После push ожидаемый критерий: GitHub Actions `Tests` и `Deploy Prod` больше
  не показывают warning про `actions/checkout@v4` / Node.js 20.

## Тесты и проверки

- `rg "actions/checkout@v4" .github/workflows`
- `rg "actions/checkout@v7" .github/workflows`
- `docker compose --profile test run --rm test python - <<'PY' ...
  yaml.safe_load(...) ... PY` для `.github/workflows/*.yml`
- `git diff --check`
- `scripts/check_stage_completion.sh 181` после обновления artifacts.
