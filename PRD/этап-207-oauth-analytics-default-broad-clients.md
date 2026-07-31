# PRD — Этап 207: OAuth Analytics default for broad-scope clients

## Контекст

Production user reported that Claude OAuth consent preselects `Full access`.
`select_default_oauth_access_preset()` maps requested tool scopes outside the
Analytics preset to Front desk or Full access. Claude's DCR can request a broad
scope set, so the current UI treats a client request as a user authorization
choice. This conflicts with Stage 194/202 policy: Analytics is the safe default;
broader access must be chosen explicitly by the account owner.

## Цель

For every OAuth client, including Claude, preselect Analytics on consent. Keep
explicit Read only, Front desk and Full access choices; Full access still needs
its existing confirmation. The selected preset, not broad requested scopes,
continues to determine granted tool scopes. A validation error on consent must
retain the submitted preset and privacy mode.

## Архитектурное решение

### Проблема и ограничения

OAuth DCR/client scopes express client capability, not informed user consent.
The existing consent submit path already narrows issued scopes to the selected
preset and preserves `offline_access` separately. OAuth, privacy and public MCP
contracts must remain backward compatible; existing grants must not be changed.

### Варианты

1. Keep scope-derived selector — unsafe because broad clients preselect Full.
2. Special-case Claude by client name/redirect URI — brittle and leaves future
   clients unsafe.
3. Always preselect Analytics — one policy for all OAuth clients; explicit UI
   selection remains available.

### Выбор и инварианты

Choose option 3. New consent pages use a dedicated UI-default helper returning
`PRESET_REPORT_AI`, regardless of requested scopes. Explicit selected presets
retain their current grant behavior; Full still requires confirmation; no
existing OAuth grant/token is migrated. Requested scopes remain visibly labelled
as the client's technical request, while the existing preset table describes
what each owner-selected level grants.

### Rollback

Revert the selector-only change. Previously issued grants remain unaffected.

## Декомпозиция

| Подзадача | Оценка | Файлы |
| --- | ---: | --- |
| 207.1 PRD and reviews | ≤2h | Roadmap, PRD, artifacts |
| 207.2 Consent UI default and error state | ≤2h | `oauth_service.py`, `web_routes_oauth.py` |
| 207.3 Regression tests | ≤2h | `tests/test_stage173_oauth_metadata.py` |
| 207.4 Checks and rollout | ≤2h | workflow artifacts |

## Acceptance criteria

- A broad Claude-style requested scope renders Analytics selected on consent.
- Blank and narrow scope requests keep Analytics selected.
- Explicit Front desk/Read only/Full choices retain current grant behavior; Full
  needs confirmation.
- A Full access confirmation error retains the submitted Full access selection
  and privacy mode; a successful broad request's token response returns the
  selected Analytics scopes.
- No existing OAuth grant is changed.
- Full Docker suite, review gates and production OAuth smoke pass.

## Review gates

- Architecture Critique required: OAuth/public auth behavior.
- Spark then Claude Opus PRD and committed-diff reviews.
