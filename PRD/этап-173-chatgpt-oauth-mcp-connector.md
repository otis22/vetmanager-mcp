# Этап 173. ChatGPT Apps OAuth-compatible MCP connector

## Контекст

Пользователь хочет подключать `vetmanager-mcp` к ChatGPT Apps/Connectors
через OAuth, а не через ручную вставку service bearer token.

Текущая архитектура уже имеет:

- web account/session login;
- active `vetmanager_connection` на account;
- service bearer tokens с hash-at-rest, scopes, revoke/expiry и usage audit;
- runtime resolver `Authorization: Bearer <service_token>` ->
  `BearerAuthContext`;
- `TOOL_REQUIRED_SCOPES` и preflight scope enforcement.

Stage 173 добавляет второй bearer-token вход для ChatGPT OAuth access tokens,
но не меняет существующий service bearer contract.

## Проверенные факты

- OpenAI Apps SDK Authentication docs требуют protected resource metadata,
  OAuth authorization-server metadata, echo/validation `resource` parameter,
  authorization-code flow with PKCE `S256`, token endpoint auth methods и
  OAuth client identity через CIMD, DCR или predefined client.
- OpenAI docs теперь называют CIMD preferred when supported; DCR still
  supported и используется, если connector creator выбирает DCR или CIMD
  недоступен.
- ChatGPT sends OAuth access token in `Authorization: Bearer <token>` to the
  MCP endpoint after linking.
- ChatGPT linking UI depends on OAuth metadata and runtime auth challenges
  (`WWW-Authenticate` and/or MCP `_meta["mcp/www_authenticate"]` behavior).
- `Authlib` is a vetted OAuth library, but its server integration docs are
  primarily Flask/Django/RFC endpoint primitives. It is not a drop-in async
  Starlette/FastMCP authorization server for this codebase. Stage 173 keeps
  protocol-critical behavior small, explicit and heavily tested.

Sources:

- `https://developers.openai.com/apps-sdk/build/auth`
- `https://developers.openai.com/apps-sdk/guides/security-privacy`
- `https://developers.openai.com/apps-sdk/deploy/testing`
- Context7 `/authlib/authlib` docs query for OAuth2 authorization server,
  PKCE, DCR and custom storage primitives.

## Цель

Добавить ChatGPT-compatible OAuth 2.1 authorization-code + PKCE path поверх
существующей account/bearer архитектуры:

- existing MCP clients keep using existing service bearer tokens;
- ChatGPT can discover OAuth metadata, register or identify a client, authorize
  through account login/consent, exchange code for access/refresh tokens and
  call `/mcp`;
- OAuth access token resolution returns the same runtime Vetmanager credentials
  and scope semantics as service bearer resolution;
- OAuth grants are bound to a concrete `vetmanager_connection_id`.

## Scope

In scope:

- PRD/architecture decision and architecture critique gate;
- OAuth metadata:
  - `/.well-known/oauth-protected-resource`;
  - `/.well-known/oauth-protected-resource/mcp`;
  - `/.well-known/oauth-authorization-server`;
  - `/.well-known/openid-configuration` as compatibility alias if cheap;
- DCR endpoint `POST /oauth/register`;
- DCR public-client path for v1. CIMD is explicitly out of v1 scope even
  though OpenAI recommends it when supported; authorization-server metadata
  must set `client_id_metadata_document_supported=false` so ChatGPT does not
  probe an unsupported CIMD path;
- early DCR-only private linking spike before storage-heavy implementation:
  confirm ChatGPT Developer Mode accepts DCR when
  `client_id_metadata_document_supported=false`;
- storage models and migration for OAuth clients, grants, authorization codes,
  access tokens and refresh tokens;
- authorization endpoint `GET /oauth/authorize`;
- consent submit endpoint if needed;
- token endpoint `POST /oauth/token` for `authorization_code` and
  `refresh_token`;
- refresh token rotation and reuse detection;
- OAuth access token runtime resolver routed by token prefix;
- account UI block for ChatGPT grants with revoke/disconnect;
- MCP auth challenge helper for OAuth-capable failures;
- per-tool OAuth `securitySchemes`/scope metadata for `tools/list` output if
  FastMCP exposes a supported metadata extension path; if current FastMCP
  cannot emit this safely, add a stable `tools/list` compatibility shim or stop
  Stage 173 before rollout with an explicit unsupported-version decision;
- tests for metadata, DCR, authorize, token exchange, refresh rotation/reuse,
  runtime resolver, service bearer no-regression, UI revoke and smoke.

Out of scope:

- public ChatGPT app submission;
- `private_key_jwt`;
- CIMD validation/fetching of ChatGPT client metadata documents;
- full OpenID Connect identity claims / ID token issuance;
- mTLS verification of ChatGPT managed client certificate;
- public RFC 7009-style `/oauth/revoke` endpoint; v1 revocation is via account
  UI grant disconnect unless private ChatGPT validation proves the public
  endpoint is mandatory;
- changing Vetmanager auth modes;
- changing existing service bearer token format or account token UI defaults.

## Архитектурное решение

### Проблема

ChatGPT needs OAuth user linking, while existing MCP clients already use
service bearer tokens. Both token kinds arrive in the same HTTP header:
`Authorization: Bearer ...`. We need to accept ChatGPT OAuth without breaking
service bearer clients, without cross-clinic data leakage, and without turning
Vetmanager credentials into ChatGPT-facing secrets.

### Контекст и ограничения

- Current runtime assumes `BearerAuthContext.bearer_token_id: int`.
- `runtime_auth.RuntimeCredentials` already allows nullable `bearer_token_id`,
  so it can carry OAuth subject metadata with a small extension.
- Account session cookie is `SameSite=Strict`; ChatGPT-initiated auth may show
  login screen. That is acceptable for v1.
- CSP `frame-ancestors 'none'` should remain: OAuth pages are top-level
  redirects, not embedded widgets.
- Existing tools should not accept credentials as params.
- Service bearer tokens must continue to work byte-for-byte for existing MCP
  clients.
- OAuth tokens must be hash-at-rest and raw tokens must be returned only once.
- OAuth grants must be bound to `vetmanager_connection_id`, not “currently
  active connection”.

### Рассмотренные варианты

1. Reuse service bearer tokens for ChatGPT.
   - Плюсы: минимальный код.
   - Минусы: не OAuth, нет PKCE/refresh/ChatGPT linking UI, ручной secret UX,
     высокий риск scope/owner confusion. Rejected.

2. External OAuth provider / JWT/JWKS.
   - Плюсы: стандартный OAuth/OIDC provider, signed tokens.
   - Минусы: новый внешний dependency/ops surface, JWKS rotation, instant
     revoke сложнее, нужно мапить external identity к internal account. Rejected
     for v1.

3. Full Authlib authorization server integration.
   - Плюсы: vetted protocol library.
   - Минусы: available docs target Flask/Django or low-level RFC primitives,
     not a simple async Starlette/FastMCP drop-in; adapting it may be more code
     and risk than a small explicit v1. Rejected for v1, can be revisited if
     custom module grows.

4. Small internal OAuth module with opaque DB tokens.
   - Плюсы: matches existing bearer architecture, instant revoke, direct
     account/session integration, minimal moving parts, testable.
   - Минусы: project owns protocol validation; requires strong tests and
     architecture critique.

### Выбранное решение

Use a small internal OAuth module for v1:

- opaque random codes/access tokens/refresh tokens;
- prefixes:
  - existing service bearer keeps current prefix;
  - OAuth access token: `vm_oat_...`;
  - OAuth refresh token: `vm_ort_...`;
  - authorization code: `vm_oac_...`;
- DB stores only hashes + prefixes + metadata;
- DCR public clients with `token_endpoint_auth_method=none`;
- metadata sets `client_id_metadata_document_supported=false` in v1. CIMD is
  kept as a follow-up after DCR private validation succeeds and after we can
  safely fetch/validate the ChatGPT client metadata document and redirect URI;
- DCR-only support is a go/no-go gate before storage-heavy implementation:
  private ChatGPT Developer Mode must be able to call DCR and enter the
  authorize flow with CIMD disabled, otherwise the architecture switches to
  CIMD/predefined client before 173.3 proceeds;
- OAuth grant binds `account_id`, `vetmanager_connection_id`, `client_id`,
  scopes and status;
- runtime token resolver routes by prefix:
  - service bearer path stays existing;
  - OAuth access path resolves grant/account/connection and returns compatible
    `RuntimeCredentials` with `source="oauth"`;
- OAuth resolver validates `grant.status == active`,
  `access_token.status == active`, access token expiry and the request
  resource/audience on every request;
- refresh token rotation revokes grant family on reuse.

Security-critical custom pieces and required substitute hardening:

- PKCE S256 verification is implemented locally because it is a small
  deterministic `BASE64URL(SHA256(code_verifier))` comparison. Tests must cover
  valid verifier, wrong verifier, unsupported method and malformed verifier.
- DCR validation is implemented locally because v1 supports only public clients
  with exact HTTPS redirect URI allowlist and no client secret/JWT auth. Tests
  must cover JSON-only input, unsafe redirect rejection, exact redirect
  matching, duplicate/stale registration caps and trusted-proxy-aware rate
  limits.
- Authorization-code consume and refresh-token rotation are implemented as DB
  state transitions because they are tied to hash-at-rest opaque tokens and
  grant-family revocation. Tests must cover concurrent double-spend attempts,
  replay, refresh reuse and immediate invalidation of outstanding access
  tokens.
- If these local pieces grow beyond the v1 public-client/OAuth-code/PKCE shape,
  revisit Authlib or another vetted OAuth server library before extending the
  protocol surface.

### Почему не выбран альтернативный вариант

The fastest safe v1 is not “use service bearer” and not “bolt in a framework
adapter”. The project already has account/session/storage/scope machinery; the
least risky path is to add OAuth protocol edges around it and reuse existing
runtime enforcement.

### Инварианты

- Existing service bearer tokens continue to authenticate existing clients.
- `resolve_runtime_credentials()` exposes one `RuntimeCredentials` output shape
  to downstream tools for both service bearer and OAuth; tools must not branch
  on auth mode to read Vetmanager credentials or scopes.
- The existing service bearer `vm_st_` internal resolver keeps the current
  `BearerAuthContext` type/shape and token prefix behavior.
- Raw OAuth tokens/codes are never persisted or logged.
- OAuth grants never resolve through mutable active connection.
- OAuth token with wrong/expired/revoked grant cannot call tools.
- OAuth token for the wrong resource/audience cannot call tools, even if the
  token was otherwise valid at issuance time.
- OAuth token bound to a missing or inactive Vetmanager connection fails as
  `invalid_token`/401, not as a Vetmanager downstream error or 500.
- Refresh token reuse revokes the grant family.
- Scope enforcement continues to use `TOOL_REQUIRED_SCOPES`.
- Account UI can revoke ChatGPT grants without affecting service bearer tokens.

### Rollback / fallback

- Disable OAuth by removing/ignoring OAuth routes and using existing service
  bearer tokens; DB tables can remain dormant.
- Revoke all OAuth grants by status update if connector behavior is unsafe.
- If CIMD is not compatible in private ChatGPT validation, use DCR path for v1.
- If ChatGPT linking UI requires different challenge shape, adjust challenge
  response without changing storage/token model.

### Architecture Critique

Required: yes. Stage 173 touches auth, storage, public API/MCP contract,
production behavior and cross-module boundaries.

The Architecture Critique prompt must cover architecture and PRD completeness
and can count as the strong PRD-review gate under workflow rule.

## Storage contract

Add tables:

- `oauth_clients`
  - `id`;
  - `client_id` unique;
  - `client_name`;
  - `redirect_uris_json`;
  - `token_endpoint_auth_method`;
  - `grant_types_json`;
  - `response_types_json`;
  - `scope`;
  - `status`;
  - `created_at`, `updated_at`, `last_seen_at`.
- `oauth_grants`
  - `id`;
  - `account_id`;
  - `vetmanager_connection_id`;
  - `client_id`;
  - `scopes_json`;
  - `status`;
  - `created_at`, `last_used_at`, `revoked_at`, `revocation_reason`.
- `oauth_authorization_codes`
  - `id`;
  - `code_prefix`, `code_hash`;
  - `client_id`;
  - `redirect_uri`;
  - `resource`;
  - `scope`;
  - `code_challenge`;
  - `code_challenge_method`;
  - `account_id`;
  - `vetmanager_connection_id`;
  - `expires_at`, `consumed_at`, `created_at`.
- `oauth_access_tokens`
  - `id`;
  - `grant_id`;
  - `token_prefix`, `token_hash`;
  - `scope`;
  - `resource`;
  - `status`;
  - `expires_at`, `revoked_at`, `last_used_at`, `created_at`.
- `oauth_refresh_tokens`
  - `id`;
  - `grant_id`;
  - `token_prefix`, `token_hash`;
  - `scope`;
  - `resource`;
  - `status`;
  - `expires_at`, `revoked_at`, `used_at`, `replaced_by_token_id`,
    `created_at`.

Statuses:

- clients: `active`, `disabled`;
- grants/tokens/codes: `active`, `revoked`, `expired`, `consumed`.

## HTTP contract

### Protected resource metadata

`GET /.well-known/oauth-protected-resource` and
`GET /.well-known/oauth-protected-resource/mcp` return JSON with:

- `resource = https://vetmanager-mcp.vromanichev.ru/mcp` by default, derived
  from `SITE_BASE_URL` + `MCP_PATH`;
- `authorization_servers = [https://vetmanager-mcp.vromanichev.ru]`;
- `scopes_supported` from supported token scopes;
- `resource_documentation`.

### Authorization server metadata

`GET /.well-known/oauth-authorization-server` returns:

- `issuer`;
- `authorization_endpoint`;
- `token_endpoint`;
- `registration_endpoint`;
- `revocation_endpoint` if implemented;
- `response_types_supported = ["code"]`;
- `grant_types_supported = ["authorization_code", "refresh_token"]`;
- `code_challenge_methods_supported = ["S256"]`;
- `token_endpoint_auth_methods_supported = ["none"]`;
- `client_id_metadata_document_supported = false` in v1;
- `scopes_supported`.

### DCR

`POST /oauth/register`:

- accepts JSON only;
- public client only: `token_endpoint_auth_method=none`;
- requires at least one HTTPS redirect URI;
- rejects non-HTTPS redirect URIs except localhost in tests if explicitly
  allowed by helper;
- stores exact redirect URIs;
- applies unauthenticated abuse controls:
  - request body size cap via existing form/body policy or route-local JSON cap;
  - rate limit by real client IP using the deployment's trusted-proxy /
    `X-Forwarded-For` policy, never by a spoofable header alone;
  - do not cap solely by redirect URI because ChatGPT may reuse a shared
    redirect URI for many users; after the DCR-only spike confirms ChatGPT's
    registration cardinality, cap only stale duplicate registrations for
    equivalent client metadata within a time window;
  - cleanup/expiry policy for stale disabled clients and expired codes/tokens;
- returns `client_id`, `client_id_issued_at`, `redirect_uris`,
  `token_endpoint_auth_method`, `grant_types`, `response_types`, `scope`.

### Authorization endpoint

`GET /oauth/authorize`:

- validates `response_type=code`;
- validates known client and exact `redirect_uri`;
- validates `resource` equals canonical MCP resource;
- validates `code_challenge_method=S256`;
- validates requested scopes are known and non-empty;
- if account session missing: redirect to `/login?next=<encoded full authorize url>`;
- if account has no active Vetmanager connection: show safe error;
- if account has exactly one active Vetmanager connection: preselect it;
- if account has multiple active Vetmanager connections: consent screen must
  require explicit clinic/connection selection and bind the grant to the
  selected `vetmanager_connection_id`;
- original OAuth request parameters (`state`, `code_challenge`,
  `code_challenge_method`, `redirect_uri`, `resource`, `scope`, `client_id`)
  are preserved through login/consent via an opaque server-side authorization
  request record or a signed nonce-bound payload; URL `next` alone is not the
  source of truth;
- if valid: show consent page or directly issue code after consent submit.

`POST /oauth/authorize/consent`:

- CSRF-protected;
- revalidates original request fields;
- creates code bound to account and active connection;
- redirects to exact `redirect_uri?code=...&state=...`.

### Token endpoint

`POST /oauth/token`:

- form-encoded;
- rate limited by client IP and `client_id` for all failed requests; repeated
  invalid grants should not provide token/code enumeration signal;
- `grant_type=authorization_code`:
  - validates code hash, not expired, not consumed;
  - exact `client_id`, `redirect_uri`, `resource`;
  - validates PKCE S256;
  - marks code consumed with a single-row conditional update so concurrent
    exchanges cannot double-spend one authorization code;
  - replay of an already-consumed code returns `invalid_grant`; v1 does not
    create a grant before successful first exchange, so there is no grant family
    to revoke on code replay;
  - creates/updates grant;
  - issues access + refresh token.
- `grant_type=refresh_token`:
  - validates refresh token hash, status, expiry and grant;
  - if already used/revoked reuse is detected, revoke grant family;
  - otherwise rotates refresh token with a single-row conditional update and
    issues a new access token so concurrent refreshes cannot produce two valid
    successors.
- errors use OAuth JSON codes and never include raw secrets.

### Public revocation endpoint

`POST /oauth/revoke` is deferred in v1 and is not advertised in metadata unless
private ChatGPT validation proves the connector requires it. Account UI grant
disconnect remains in scope and revokes the grant family server-side.

## Runtime contract

- `request_auth.get_bearer_token()` message becomes generic enough for both
  service bearer and OAuth bearer.
- `runtime_auth.resolve_runtime_credentials()` routes by token prefix:
  - service bearer -> existing `resolve_bearer_auth_context`;
  - `vm_oat_` -> new OAuth resolver.
- unknown, malformed or truncated token prefixes return the same generic
  401 Bearer challenge as an invalid service bearer token and do not reveal
  which prefixes are supported.
- `RuntimeCredentials` gets optional `auth_subject_type` and
  `auth_subject_id`, or equivalent, for audit/debug without overloading
  `bearer_token_id`.
- OAuth and service bearer paths both return the same `RuntimeCredentials`
  dataclass/interface from `resolve_runtime_credentials()`; auth-specific fields
  may be nullable, but downstream tool wrappers continue to consume
  `vetmanager_auth`, `scopes`, `account_id`, `connection_id` and
  `is_depersonalized` from one shape.
- OAuth resolver loads the bound connection by `grant.vetmanager_connection_id`
  and checks access token status, grant status, account/connection status,
  expiry and resource/audience. Missing or inactive bound connection returns
  401 with `error="invalid_token"` and never falls through to a Vetmanager API
  call.
- Tool scope enforcement remains unchanged: it receives `credentials.scopes`.

## MCP auth metadata and challenge contract

Per-tool security metadata:

- Tools requiring scopes should advertise OAuth bearer auth with required
  scopes derived from `TOOL_REQUIRED_SCOPES`.
- Scope-free authenticated tools should advertise OAuth bearer auth with an
  empty/default scope list rather than anonymous access.
- OpenAI Apps SDK docs say ChatGPT's tool-level OAuth UI needs both:
  `securitySchemes` metadata and runtime `_meta["mcp/www_authenticate"]`.
  Therefore Stage 173 must add a stable shim/post-processing path if FastMCP
  cannot emit `securitySchemes` directly. Runtime challenge fallback alone is
  not sufficient for completion unless the 173.2 private ChatGPT compatibility
  spike proves resource-level metadata plus `WWW-Authenticate`/`_meta`
  challenge is accepted by ChatGPT without per-tool metadata. Otherwise Stage
  173 must use a stable `tools/list` shim or stop before rollout.

Runtime challenge behavior:

- Missing/invalid OAuth token on HTTP/MCP request should produce a Bearer
  challenge with `resource_metadata` pointing to
  `/.well-known/oauth-protected-resource/mcp`.
- Header shape follows OpenAI Apps SDK docs, for example:
  `WWW-Authenticate: Bearer resource_metadata="https://vetmanager-mcp.vromanichev.ru/.well-known/oauth-protected-resource/mcp", scope="clients.read"`.
- Expired/revoked OAuth token should use `error="invalid_token"`.
- Valid OAuth token with insufficient tool scope should use
  `error="insufficient_scope"` and include required scope when available.
- Tool-level auth errors must include `_meta["mcp/www_authenticate"]` with a
  Bearer challenge string containing `resource_metadata`, `error` and
  `error_description`; this is what triggers ChatGPT's OAuth UI after
  `securitySchemes` has declared the tool auth policy.
- Challenge payloads must not include raw token values, account email,
  Vetmanager credentials or upstream payloads.

## Account UI contract

`/account` shows a compact `ChatGPT connections` block:

- list OAuth grants by client name, status, created/last used;
- revoke/disconnect button;
- no raw OAuth tokens shown;
- no service bearer token required for ChatGPT flow.

## Tests

Add focused tests:

- early ChatGPT Developer Mode DCR-only linking spike confirms that metadata
  with `client_id_metadata_document_supported=false` still reaches
  `POST /oauth/register` and the authorize flow; if not, stop before 173.3 and
  update architecture;
- FastMCP `securitySchemes` capability spike confirms native metadata support
  or the exact compatibility shim needed for `tools/list`;
- metadata endpoints return expected OAuth documents and canonical resource;
- DCR accepts valid public client and rejects unsafe redirect URI;
- DCR rate limits abuse and caps duplicate/stale registrations;
- authorization-server metadata explicitly sets
  `client_id_metadata_document_supported=false` in v1;
- authorize rejects bad client, bad redirect, bad PKCE method, bad resource;
- authorize without session redirects to login with next param;
- login -> consent flow preserves OAuth `state` and PKCE params through the
  server-side/signed authorization request state, not only a mutable `next` URL;
- consent creates code and binds concrete selected connection; multi-connection
  accounts must bind the user-selected connection;
- token exchange validates PKCE and exact redirect/resource;
- authorization code replay returns `invalid_grant`;
- concurrent authorization-code exchanges cannot both succeed;
- refresh token rotates and old refresh token reuse revokes grant;
- concurrent refresh-token exchanges cannot both produce valid successors;
- account UI disconnect revokes the grant family and immediately invalidates
  outstanding access tokens;
- OAuth access token resolves runtime credentials and scopes;
- changing active Vetmanager connection after grant does not change OAuth
  runtime connection;
- inactive/missing bound connection returns 401 `invalid_token`;
- revoked grant, revoked access token or wrong resource/audience returns 401
  `invalid_token`;
- unknown/malformed bearer token prefix returns generic 401 without prefix
  enumeration;
- regression with a historically issued service token format confirms existing
  `vm_st_` tokens still route only to `resolve_bearer_auth_context`;
- missing/expired/revoked/insufficient-scope OAuth failures expose safe
  `WWW-Authenticate` / `_meta["mcp/www_authenticate"]` challenge metadata;
- tools/list exposes per-tool OAuth `securitySchemes`/scopes based on
  `TOOL_REQUIRED_SCOPES`;
- metadata and token tests pin `SITE_BASE_URL=https://test.example.com` so the
  canonical resource is explicitly `https://test.example.com/mcp`;
- service bearer auth tests still pass;
- account UI lists/revokes OAuth grants;
- migration creates OAuth tables and downgrade removes them.

## Acceptance criteria

1. Existing service bearer tokens continue passing existing tests.
2. Before storage-heavy implementation, private ChatGPT Developer Mode
   DCR-only validation reaches registration/authorize with
   `client_id_metadata_document_supported=false`; if it fails, Stage 173 stops
   and updates architecture instead of continuing on an unvalidated DCR-only
   assumption.
3. FastMCP/tools-list spike proves per-tool `securitySchemes` emission or a
   stable compatibility shim before rollout.
4. OAuth metadata endpoints are public, no-store JSON and include correct
   canonical MCP resource.
5. DCR creates a public client with exact redirect URI allowlist and has
   rate-limit/storage-cap/cleanup tests for unauthenticated abuse controls.
6. Authorization code flow with PKCE S256 issues access + refresh tokens.
7. Authorization-code consumption and refresh-token rotation are atomic under
   concurrent requests.
8. Refresh token exchange rotates refresh tokens.
9. Refresh token reuse revokes the grant family and invalidates outstanding
   access tokens.
10. OAuth access token can call MCP tools through existing runtime credential
   path and scope enforcement.
11. OAuth grant is bound to the Vetmanager connection selected at consent time.
12. OAuth auth challenges and per-tool auth metadata are emitted with tested
   `securitySchemes`/scope fields and `_meta["mcp/www_authenticate"]`.
13. Account UI can revoke OAuth grant.
14. Tests, review gates, full suite, deploy and smoke pass.

## Rollout

1. Run early DCR-only ChatGPT Developer Mode spike and FastMCP
   `securitySchemes` spike before storage-heavy implementation.
2. Ship server support.
3. Deploy production.
4. Run public health/readiness smoke.
5. Private ChatGPT Developer Mode/API Playground connector validation against
   `https://vetmanager-mcp.vromanichev.ru/mcp`.
6. Public submission remains a separate decision.

## Риски

- ChatGPT connector behavior around CIMD/DCR can change; keep DCR path and
  metadata explicit and set CIMD support false until implemented.
- OAuth auth challenge shape may need iteration after real ChatGPT validation.
- Custom protocol code can be wrong; mitigate with narrow, adversarial tests.
- New unauthenticated endpoints increase attack surface; validate inputs,
  rate-limit DCR/authorize/token, cap registrations, cleanup expired artifacts
  and avoid secret-bearing logs.
- Full Stage 173 is large; implementation must stay modular and avoid
  refactoring existing bearer code beyond the prefix-routing boundary.
