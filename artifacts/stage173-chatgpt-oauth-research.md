# Stage 173 Research: ChatGPT Apps OAuth-compatible MCP connector

Дата: 2026-06-18

## Источник и цель

Пользователь хочет использовать текущий `vetmanager-mcp` из веб-агентов ChatGPT как ChatGPT Apps/Connectors MCP app, а не через ручную вставку service bearer token.

Цель Stage 173: добавить ChatGPT-compatible OAuth 2.1 authorization layer поверх существующей account/bearer архитектуры:

- текущие MCP-клиенты (`Cursor`, `Claude`, `Codex`) продолжают использовать `Authorization: Bearer <service_token>`;
- ChatGPT проходит OAuth authorization-code + PKCE, получает OAuth access token и вызывает тот же `/mcp`;
- runtime мапит оба вида токенов в единый `BearerAuthContext`;
- Vetmanager auth modes (`domain + api_key`, `login/password -> user token`) остаются account integration detail и не становятся ChatGPT-facing credentials.

## Проверенные external facts

Основано на OpenAI Apps SDK docs:

- ChatGPT custom apps/connectors подключаются к публичному HTTPS MCP endpoint (`/mcp`) через ChatGPT `Settings -> Apps & Connectors -> Create`.
- Для private data ChatGPT использует OAuth authorization-code flow with PKCE; после flow ChatGPT прикладывает `Authorization: Bearer <token>` к MCP requests.
- ChatGPT не поддерживает machine-to-machine grants, service accounts, JWT bearer assertions или custom API keys как user auth mechanism для connector linking.
- ChatGPT linking UI требует OAuth metadata/resource metadata, per-tool auth/security metadata и runtime `WWW-Authenticate` / `_meta["mcp/www_authenticate"]` behavior.
- ChatGPT может использовать DCR или CIMD для client identity; для v1 этого проекта DCR безопаснее как практический baseline.
- Resource/audience должен быть проверяемым: ChatGPT передаёт `resource`, а сервер должен проверять issuer/audience/expiry/scopes.

Review: план дополнительно передан в Claude Opus review-only 2026-06-18. Приняты только actionable замечания: DCR endpoint, refresh token rotation, path-suffixed protected-resource metadata, connection binding, opaque token decision, не hand-roll OAuth grant machinery.

Reference URLs:

- `https://developers.openai.com/apps-sdk/deploy/connect-chatgpt`
- `https://developers.openai.com/apps-sdk/build/auth`
- `https://developers.openai.com/apps-sdk/deploy/testing`

## Current architecture fit

В проекте уже есть:

- web account registration/login/session cookie;
- active `vetmanager_connection` на account;
- service bearer tokens: hash-at-rest, prefix, scopes, revoke/expiry, usage logs/stats;
- runtime bearer resolver: `Authorization: Bearer <service_token>` -> account context;
- `TOOL_REQUIRED_SCOPES` и tool-level scope preflight;
- account UI для Vetmanager integration и service bearer token issuance.

Stage 173 не должен переписывать эту архитектуру. Новый OAuth path должен быть отдельным входом, который сходится в существующий runtime context.

## Current code friction points to resolve before implementation

- `pyproject.toml` currently has no OAuth library dependency. Stage 173 should add and package a vetted OAuth implementation dependency (for example `authlib`) deliberately, with packaging tests updated if needed.
- `runtime_auth.RuntimeCredentials` currently stores `bearer_token_id: int | None` and `source="bearer"`. OAuth runtime needs either nullable token identity fields or separate `auth_subject_type/auth_subject_id` fields, so audit/metrics can distinguish `service_bearer` from `chatgpt_oauth` without overloading `bearer_token_id`.
- `auth.bearer.BearerAuthContext` currently requires `bearer_token_id: int`. Do not force OAuth tokens into `service_bearer_tokens`; add an OAuth-aware context shape or a shared resolved-auth DTO.
- `tools/__init__.py` catches `AuthError` and converts it to generic `ToolError("Runtime authentication failed.")`. ChatGPT linking requires a precise auth challenge. Stage 173 must decide whether this is emitted at HTTP/MCP middleware level, FastMCP tool error `_meta`, or a new auth-specific exception type.
- `auth.request.get_bearer_token()` error messages mention `<service_token>`. Stage 173 should make missing/invalid authorization messages generic enough for both service bearer and OAuth tokens while preserving no-regression tests for existing clients.
- Existing web session cookie defaults to `SameSite=Strict`. ChatGPT-initiated top-level navigation to `/oauth/authorize` may not carry an existing account session. Treat a login prompt as acceptable v1 behavior; do not weaken all web cookies unless browser testing proves it is required.
- Existing CSP uses `frame-ancestors 'none'`. OAuth authorize/consent pages should be top-level redirect pages, not embedded widgets. Keep this unless ChatGPT documentation requires a different embedding mode.

## Design decisions

### Token model

Use opaque DB-backed OAuth tokens for v1:

- access tokens and refresh tokens are random opaque values;
- raw tokens are shown/returned only at issuance to ChatGPT token endpoint;
- storage keeps hash + prefix/metadata only;
- revocation is instant through DB state;
- no JWKS/JWT in v1.

Rationale: this matches existing service bearer architecture and avoids key rotation/JWT revocation complexity.

Suggested token prefixes:

- service bearer tokens keep existing `vm_st_...` format;
- OAuth access tokens use a new prefix such as `vm_oat_...`;
- OAuth refresh tokens use a new prefix such as `vm_ort_...`;
- token lookup should route by prefix and never query all token tables sequentially.

### Grant binding

Bind OAuth grant to concrete `vetmanager_connection_id` at consent time.

Do not resolve OAuth grants through "current active connection" at tool-call time.

Rationale: if the account later changes active integration, an already-linked ChatGPT connector must not silently start reading/writing another clinic.

### Registration

Implement DCR as v1 requirement:

- `POST /oauth/register`;
- exact redirect URI storage/validation;
- public-client mode (`token_endpoint_auth_method=none`);
- rate limits and registration caps.

CIMD can be a follow-up after DCR works.

Minimum DCR behavior:

- accept public clients with `token_endpoint_auth_method=none`;
- require at least one HTTPS `redirect_uri`;
- exact-match stored redirect URIs during `/oauth/authorize` and `/oauth/token`;
- store client metadata needed for audit/debug (`client_name`, `redirect_uris`, `grant_types`, `response_types`, `scope`, `created_at`, `last_seen_at`);
- cap client registrations per source/client metadata window to avoid storage spam;
- never trust DCR `client_name`, logo, URI, or policy text as safe HTML.

### Refresh tokens

Refresh tokens are required for useful ChatGPT UX:

- short-lived access tokens;
- refresh token rotation;
- reuse detection;
- replayed refresh token revokes the grant family.

Without refresh tokens, ChatGPT will require frequent re-link and the connector will look unreliable.

### OAuth library

Do not hand-roll OAuth grant mechanics. Use a vetted library such as Authlib for protocol-critical pieces. Project custom code should own:

- account session integration;
- consent screen;
- Vetmanager connection binding;
- scope mapping;
- storage model integration;
- runtime context resolution.

Before implementation, run a short spike to confirm the chosen library supports async Starlette/FastMCP integration, PKCE S256, DCR or enough primitives to implement DCR safely, refresh rotation hooks, and custom opaque token storage.

## Metadata payload details to predefine

Protected resource metadata should use a canonical resource value. For this deployment, prefer:

```json
{
  "resource": "https://vetmanager-mcp.vromanichev.ru/mcp",
  "authorization_servers": ["https://vetmanager-mcp.vromanichev.ru"],
  "scopes_supported": ["clients.read", "pets.read", "finance.read", "analytics.read"],
  "resource_documentation": "https://vetmanager-mcp.vromanichev.ru/"
}
```

Serve both:

- `/.well-known/oauth-protected-resource`
- `/.well-known/oauth-protected-resource/mcp`

The path-suffixed variant must use the exact `/mcp` resource. Test both `.../mcp` and accidental `.../mcp/` mismatch; choose one canonical value and reject the other with a clear `invalid_target`/`invalid_resource` style error.

Authorization server metadata should explicitly include:

- `issuer`
- `authorization_endpoint`
- `token_endpoint`
- `registration_endpoint`
- `revocation_endpoint` if implemented
- `response_types_supported: ["code"]`
- `grant_types_supported: ["authorization_code", "refresh_token"]`
- `code_challenge_methods_supported: ["S256"]`
- `token_endpoint_auth_methods_supported: ["none"]`
- `scopes_supported`

No `jwks_uri` is required for opaque tokens unless ID tokens or private-key client auth are introduced later.

## OAuth request/response contract details

### `/oauth/authorize`

Required request validation:

- `response_type=code`;
- known `client_id`;
- exact `redirect_uri`;
- `code_challenge` present;
- `code_challenge_method=S256`;
- `resource` equals the canonical MCP resource;
- requested scopes are known and allowed for this connector/account policy.

Authorization code storage should include:

- code hash/prefix, never raw code;
- `client_id`;
- exact `redirect_uri`;
- `resource`;
- `scope`;
- `code_challenge`;
- `code_challenge_method`;
- `account_id`;
- bound `vetmanager_connection_id`;
- expiration timestamp;
- consumed timestamp.

### `/oauth/token`

Authorization-code exchange must:

- validate `grant_type=authorization_code`;
- validate code exists, not expired, not consumed;
- validate exact `client_id`, `redirect_uri`, and `resource`;
- validate PKCE verifier against stored S256 challenge;
- mark code consumed before or atomically with token issuance;
- issue access + refresh token pair.

Refresh-token exchange must:

- validate `grant_type=refresh_token`;
- hash-lookup refresh token;
- check status, expiry, grant status, account status and bound connection status;
- rotate refresh token on every use;
- revoke the grant family on refresh token reuse.

Token endpoint should return standard OAuth JSON errors such as `invalid_request`, `invalid_client`, `invalid_grant`, `invalid_scope`, and should never include raw tokens, code values, Vetmanager credentials, account email, or upstream payloads in logs/errors.

## Storage model details

Recommended tables/fields:

- `oauth_clients`: `client_id`, `redirect_uris_json`, `client_name`, `token_endpoint_auth_method`, `created_at`, `last_seen_at`, `status`.
- `oauth_grants`: `account_id`, `vetmanager_connection_id`, `client_id`, `scopes_json`, `status`, `created_at`, `last_used_at`, `revoked_at`, `revocation_reason`.
- `oauth_authorization_codes`: code hash/prefix, `grant_id` or pending account/connection binding fields, PKCE fields, `redirect_uri`, `resource`, `expires_at`, `consumed_at`.
- `oauth_access_tokens`: token hash/prefix, `grant_id`, `scopes_json`, `resource`, `expires_at`, `revoked_at`, `last_used_at`.
- `oauth_refresh_tokens`: token hash/prefix, `grant_id`, `family_id`, `rotation_counter`, `expires_at`, `used_at`, `replaced_by_token_id`, `revoked_at`, `reuse_detected_at`.

Add indexes for token hash lookup, grant/account listing, cleanup by expiry, and audit queries by account/client.

## Required endpoints

Discovery/metadata:

- `/.well-known/oauth-authorization-server`
- `/.well-known/oauth-protected-resource`
- `/.well-known/oauth-protected-resource/mcp`

OAuth:

- `POST /oauth/register`
- `GET /oauth/authorize`
- `POST /oauth/token`
- optional but recommended: `POST /oauth/revoke`

MCP:

- existing `/mcp`, with OAuth-aware `WWW-Authenticate` challenge and per-tool security metadata.

## Safe implementation sequence

1. PRD and compatibility research.
2. Metadata endpoints and FastMCP capability check.
3. Storage + DCR.
4. Authorization endpoint and consent UX.
5. Token endpoint with refresh rotation.
6. Runtime resolver extension.
7. MCP `securitySchemes` and auth challenge behavior.
8. Account UI for ChatGPT grants.
9. Regression/negative tests.
10. Private ChatGPT Developer Mode rollout.

Do not start with public submission.

## Scope mapping

OAuth scopes must map to existing `TOOL_REQUIRED_SCOPES`. Enforcement must stay single-source and fail-closed.

Initial recommendation:

- publish a conservative read-first/default scope set;
- do not expose broad full-access as the default ChatGPT consent;
- write tools remain scope-gated and require normal ChatGPT confirmation behavior;
- per-tool scope picker is out of v1 unless concrete UX need appears.

Do not publish every internal scope blindly on day one. Recommended initial ChatGPT consent profile:

- read/search clinical and client context: `clients.read`, `pets.read`, `admissions.read`, `medical_cards.read`, `reference.read`;
- analytics/reporting: `finance.read`, `inventory.read`, `analytics.read`;
- exclude broad write scopes by default;
- add `report_ai.write` only behind an explicit "Report AI save" consent/preset if Stage 172.2 is complete.

If ChatGPT requests no scopes, issue a conservative default instead of full access.

## Risks and mitigations

### Existing service bearer clients break

Risk: changing `Authorization` parsing or resolver path can break existing Cursor/Claude/Codex clients.

Mitigation:

- distinct token prefixes;
- prefix-routed resolver;
- separate OAuth tables;
- no change to service bearer token issuance/validation;
- regression tests for existing service bearer clients and scope preflight.

### Scope bypass or over-broad ChatGPT access

Risk: OAuth scopes diverge from `TOOL_REQUIRED_SCOPES` and ChatGPT gets too much or too little access.

Mitigation:

- one mapping table;
- tests for every tool scope;
- fail closed for unknown tool/scope;
- conservative default consent.

### ChatGPT linking UI does not appear

Risk: metadata URL, path-suffixed protected resource, `WWW-Authenticate`, `securitySchemes` or `_meta["mcp/www_authenticate"]` are wrong.

Mitigation:

- test exact well-known paths;
- test exact challenge header including `resource_metadata`;
- verify through API Playground before ChatGPT UI;
- add FastMCP compatibility check before implementation.

Current project-specific risk: the tool wrapper currently converts `AuthError` into generic `ToolError`. If FastMCP does not expose response `_meta` or HTTP headers at that point, challenge emission must move closer to the HTTP route/middleware layer.

### Cross-clinic data leak

Risk: OAuth token follows account's current active integration and silently switches clinic.

Mitigation:

- bind grant to `vetmanager_connection_id`;
- revoke or mark grant invalid if bound connection is removed/disabled;
- account UI must show which integration a grant is bound to.

### New public attack surface

Risk: `/oauth/register`, `/oauth/authorize`, `/oauth/token` introduce DCR spam, brute force, token probing, redirect attacks.

Mitigation:

- existing shared rate-limit backend;
- exact redirect URI validation;
- PKCE S256 only;
- short auth-code TTL;
- single-use code;
- CSRF on local login/consent forms;
- DCR storage caps and cleanup;
- structured security logging without token leaks.

### Refresh token compromise

Risk: long-lived refresh token theft can maintain ChatGPT access.

Mitigation:

- hash-at-rest;
- rotation on every use;
- reuse detection and grant-family revocation;
- account UI disconnect/revoke;
- usage logs and audit trail.

### Multi-instance instability

Risk: OAuth state stored process-local breaks after restart or across instances.

Mitigation:

- all OAuth client/code/token/grant state stored in DB;
- Redis-backed rate limits in production/multi-instance;
- cleanup jobs idempotent.

### Web auth regression

Risk: OAuth authorize flow interferes with existing `/login`, `/register`, `/account`.

Mitigation:

- separate OAuth return/session state;
- do not use OAuth `state` as CSRF token;
- tests for normal login/account flow and OAuth login-return flow.

### Service metrics and audit blind spots

Risk: OAuth tokens do not appear in existing `service_bearer_tokens` usage counters, so product metrics and security runbooks miss ChatGPT usage/failures.

Mitigation:

- add OAuth-specific auth events or generalize token usage logs with subject type;
- track `chatgpt_oauth_auth_succeeded`, `chatgpt_oauth_auth_failed_*`, token refresh success/failure, grant revoke/disconnect;
- update product metrics to include ChatGPT connector usage without raw account email or token values;
- keep existing service bearer metrics unchanged.

### Dependency and packaging drift

Risk: adding Authlib or another OAuth library works in tests but is missing from Docker/wheel packaging or pinned differently in runtime.

Mitigation:

- update `pyproject.toml`, Docker/test install path, and packaging metadata tests in the same stage;
- add a startup import/version check if the OAuth layer is enabled;
- document env flags so OAuth can be disabled during rollback without removing service bearer runtime.

### OAuth cleanup and storage growth

Risk: DCR clients, expired codes and rotated tokens accumulate indefinitely.

Mitigation:

- scheduled/idempotent cleanup for expired auth codes, expired access tokens, old rotated refresh tokens and stale unlinked clients;
- keep active/revoked grant records long enough for audit, but prune raw operational token rows after policy-defined retention;
- expose aggregate cleanup metrics/logs.

## Feature flags and rollback

Stage 173 should include an operational kill switch:

- `CHATGPT_OAUTH_ENABLED=0/1` gates OAuth metadata/register/authorize/token routes;
- service bearer `/mcp` runtime must continue working when OAuth is disabled;
- if OAuth is disabled, metadata endpoints should either be absent/404 or return a clear disabled response, but must not advertise a half-working auth server;
- rollback playbook: disable OAuth, restart, verify service bearer smoke, keep grants in DB for later investigation.

## Browser/API validation checklist

Before ChatGPT UI testing:

1. `GET /.well-known/oauth-protected-resource` returns JSON with canonical resource.
2. `GET /.well-known/oauth-protected-resource/mcp` returns JSON with resource ending in `/mcp`.
3. `GET /.well-known/oauth-authorization-server` includes registration/token/authorize endpoints and `S256`.
4. `POST /oauth/register` returns a usable `client_id` and stores exact redirect URIs.
5. `GET /oauth/authorize` rejects missing PKCE, unknown scope, mismatched resource, and bad redirect URI.
6. Login + consent creates a single-use code.
7. `POST /oauth/token` rejects wrong `code_verifier`, wrong `redirect_uri`, wrong `resource`, reused code.
8. Refresh rotates token and replaying old refresh revokes the family.
9. OAuth access token can call one read tool.
10. Revoked/expired OAuth token returns a ChatGPT-compatible reauth challenge.
11. Existing `vm_st_...` service bearer token still passes the existing happy path.
12. Product metrics/audit identify OAuth usage without leaking tokens or Vetmanager secrets.

## Open questions for PRD 173

- Exact FastMCP mechanism for per-tool `securitySchemes` and `_meta["mcp/www_authenticate"]`.
- Whether ChatGPT Developer Mode accepts DCR-only for this connector in the current workspace, or whether a predefined client/CIMD option is needed for local testing.
- Whether to issue OIDC ID tokens for better reauthorization UX (`id_token_hint`) or keep v1 OAuth-only. Default: OAuth-only unless ChatGPT linking requires OIDC.
- Exact OAuth access token TTL and refresh token lifetime. Starting point: access 10-15 minutes, refresh 30 days, subject to security review.
- Whether OAuth grants should inherit depersonalized mode from a preset or always return full structured payload within granted scopes. Default: same sanitizer policy as the selected account/preset; define explicitly in PRD.

## Explicit non-goals for v1

- Public ChatGPT app submission.
- JWT/JWKS OAuth tokens.
- CIMD-first implementation.
- Machine-to-machine auth or custom API key path for ChatGPT.
- Per-tool manual scope picker in UI.
- Changing Vetmanager integration auth modes.
- Replacing current service bearer token support.
- Weakening global web session cookie settings solely to optimize OAuth reauthorization UX.
- Building ChatGPT iframe widgets or custom UI components; Stage 173 is auth/connectivity first.

## Minimum acceptance criteria

- Existing service bearer MCP clients continue to work unchanged.
- ChatGPT Developer Mode can create connector against `https://vetmanager-mcp.vromanichev.ru/mcp`.
- ChatGPT can complete login/consent and receive OAuth tokens.
- OAuth access token can call at least one read tool through `/mcp`.
- Revoked/expired OAuth token triggers correct re-auth challenge.
- Scope denial is enforced before tool body execution.
- Changing active account integration does not move an existing OAuth grant to another clinic.
- Refresh token rotation and reuse detection are covered by tests.
- Product metrics/audit show OAuth usage and failures as aggregate safe signals.
- OAuth can be disabled by config without breaking service bearer MCP runtime.
