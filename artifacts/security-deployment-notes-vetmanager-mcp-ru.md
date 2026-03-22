# Security Deployment Notes: Vetmanager MCP

## Обязательные production secrets

- `WEB_SESSION_SECRET`
  - отдельный секрет подписи web session и CSRF token;
  - не должен переиспользовать `STORAGE_ENCRYPTION_KEY`.
- `STORAGE_ENCRYPTION_KEY`
  - отдельный ключ шифрования сохранённых Vetmanager credentials.

## Reverse proxy / forwarded headers

- По умолчанию сервис не доверяет `X-Forwarded-For`.
- Если сервис стоит за доверенным reverse proxy, перечислите его IP/host в
  `WEB_TRUSTED_PROXY_IPS`.
- Только в этом случае limiter и audit metadata начнут использовать forwarded
  client IP вместо direct socket peer.

## Host resolution policy

- Billing-resolved clinic host должен быть bare HTTPS origin:
  - без `userinfo`;
  - без custom port;
  - без path/query/fragment;
  - только в allowlisted suffix
    (`vetmanager.cloud`, `vetmanager2.ru`).

## Security regression subset

- Ключевые security regressions можно запускать отдельно:

```bash
docker compose run --rm test sh -c "python -m pytest -m security -q"
```

Этот subset покрывает:
- session secret boundary;
- scope enforcement;
- safe auth errors;
- audit redaction;
- trusted proxy policy;
- host validation invariants.
