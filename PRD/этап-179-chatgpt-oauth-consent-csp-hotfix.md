# Stage 179. ChatGPT OAuth consent redirect CSP hotfix

## Context

Production report 2026-06-24: after ChatGPT opens `/oauth/authorize`, the user
logs in, sees the consent page, selects `Analytics`, clicks `Allow`, and the
page appears to do nothing.

Production logs show:

- `GET /oauth/authorize` renders the consent page successfully.
- Each `POST /oauth/authorize/consent` returns `303 See Other`.
- New rows are created in `oauth_authorization_codes`.
- Those codes remain unconsumed (`consumed_at` is empty).
- ChatGPT does not call `POST /oauth/token` after the redirect.

The likely cause is CSP `form-action 'self'`: the form posts to a same-origin
endpoint, but browser enforcement can also block a cross-origin redirect in the
form submission chain. ChatGPT's current callback host is `chatgpt.com`; older
tests and clients may use `chat.openai.com`.

## Goal

Allow OAuth consent redirect back to ChatGPT while keeping the default web CSP
strict for all non-OAuth pages.

## Non-goals

- Do not change OAuth token issuance, scopes, privacy mode, DCR, PKCE, or grant
  storage.
- Do not allow arbitrary external form actions.
- Do not relax `frame-ancestors`, `default-src`, or script policy.

## Requirements

1. OAuth authorize/consent pages and the consent redirect response must include
   `form-action 'self' https://chatgpt.com https://chat.openai.com`.
2. Other pages must keep the default `form-action 'self'` behavior.
3. Existing ChatGPT OAuth callback redirects must still use exact registered
   `redirect_uri` validation.
4. Regression tests must cover the consent page CSP and post-consent redirect
   CSP.

## Acceptance

- Targeted OAuth regression passes.
- Default Docker test suite passes.
- Production deploy succeeds.
- Re-running ChatGPT consent reaches `/oauth/token` and consumes the
  authorization code.
