# Этап 100. Security hardening II

## Scope

- 100.1 Sentry sanitizer — breadcrumbs, stacktrace vars, contexts, user, tags
- 100.2 correlation_id normalization (ASCII token, регекс валидация)
- 100.3 authenticate_account timing-attack mitigation (dummy hash на None path)
- 100.4 `_SENSITIVE_KEY_PATTERNS` — добавить `dpop`, `signed`
- 100.5 SITE_BASE_URL URL-scheme validation + length cap
- 100.6 web_html.py `html.escape(site_base_url)`
- 100.7 Legacy session token path deprecation warning
