# Этап 229. Post-deploy MCP tool smoke

## Цель

После production deploy подтвердить публичным MCP протоколом один read-only
tool call, не печатая и не изменяя никаких clinic data или secret.

## Декомпозиция

1. Скрипт JSON-RPC initialize → tools/list → get_users(limit=1) (≤150 строк).
2. Workflow step после remote deploy, static tests и gates (≤100 строк).

## Архитектурное решение

Workflow получает только repository secret `PROD_SMOKE_BEARER_TOKEN`; script
передаёт его лишь в Authorization header. `get_users(limit=1)` — read-only
cheap call, tools/list подтверждает его contract. Errors содержат лишь class,
не response body/header/token; workflow не включает debug/trace и GitHub masks
repository secret. Токен уже создан с preset `read_only`, хранится только в
GitHub Secrets и ротируется оператором при компрометации. Никаких
create/update/delete/revoke запросов.

Альтернатива — health-only smoke — не проверяет tool runtime. Выбран protocol
smoke через public HTTPS. Инварианты: step падает при любой protocol/tool
ошибке после bounded retry (10 attempts, 3s; около 30s); token, response body и headers не
попадают в output; deploy only remains restricted to main.
Rollback: smoke failure останавливает deploy workflow и фиксирует непроверенный
release; автоматический rollback не выполняется, чтобы не рестартовать живой
prod вторично. Оператор откатывает на предыдущий vetted git ref существующей
deploy-процедурой, затем повторяет smoke. Application data не менялась.

Architecture Critique: required — public MCP/auth and production deploy behavior.

## Acceptance criteria

1. Script performs initialize, tools/list and exactly one read-only tools/call.
2. Workflow runs after remote deploy and failure fails deploy.
3. Static tests prohibit secret output and mutations.
4. Script retries transient public readiness failures with a bounded timeout.
