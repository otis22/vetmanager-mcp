# Operator runbook — IP mask management

After Stage 155, every `service_bearer_tokens.allowed_ip_mask` is a non-NULL string. Wildcard `*.*.*.*` is stored explicitly when the token is intentionally unrestricted; specific masks like `1.2.3.4`, `1.2.3.*`, `10.0.0.*` are stored as written.

This runbook covers operator-side maintenance through `psql` only — none of the recipes need access to application secrets or raw bearer tokens. Operator interacts with metadata (`allowed_ip_mask`, `status`, `expires_at`) via standard SQL `SELECT` / `UPDATE`.

## View the current mask of a token

```sql
SELECT id, account_id, name, allowed_ip_mask, status, expires_at
FROM service_bearer_tokens
WHERE id = :token_id;
```

Filter by account if you don't know the token id:

```sql
SELECT t.id, t.name, t.allowed_ip_mask, t.status
FROM service_bearer_tokens AS t
JOIN accounts AS a ON a.id = t.account_id
WHERE a.email = 'user@example.com';
```

## Update mask after a legitimate IP change

A user moved offices, switched ISP, or rotated a NAT — their existing token still works but the mask now rejects them. Update in place:

```sql
-- Single new IP
UPDATE service_bearer_tokens
SET allowed_ip_mask = '203.0.113.42'
WHERE id = :token_id;

-- /24 subnet (e.g. office network)
UPDATE service_bearer_tokens
SET allowed_ip_mask = '203.0.113.*'
WHERE id = :token_id;
```

Glob notation only: `*` per octet (no CIDR `1.2.3.0/24`). See `domain_validation.validate_ip_mask` for accepted shape.

After update, the next request from the new IP succeeds. There is no cache to invalidate; mask is read fresh from the DB on every auth check.

## Investigate denied events

Find recent rejections for a specific token:

```sql
SELECT event_at, details_json
FROM token_usage_logs
WHERE event_type = 'token_auth_failed_ip_denied'
  AND bearer_token_id = :token_id
ORDER BY id DESC
LIMIT 20;
```

Each `details_json` row contains:

- `account_email_masked` — `al***@ex***.com` form (per `privacy_utils.mask_email`).
- `client_ip_last_segment` — last octet (IPv4) or last hextet (IPv6) of the rejected request's source IP. Full IP is intentionally not stored.
- `expected_mask` — the mask the token has at the moment of rejection.
- `account_id`, `token_prefix`, `reason` ("ip_denied"), and request correlation fields from the standard audit envelope.

If `client_ip_last_segment` cycles through several values for one token, the user's IP is dynamic — consider issuing them a wildcard token through the web UI (with the explicit "allow from any IP" confirm checkbox).

## When to issue a new wildcard token instead of updating the mask

Use a wildcard mask if:

- the user works from mobile / hotspot — IP changes constantly;
- they rotate VPNs or proxies;
- you cannot get a stable subnet from them within the next 24 hours.

Issuance flow (web UI):

1. Open `/account` as the account owner.
2. Issue a new token with `ip_mask = *.*.*.*` and tick "I confirm: allow from any IP".
3. Revoke the old IP-restricted token after the user successfully authenticates with the new one.

Wildcard issuance writes a `RUNTIME_LOGGER.warning("token_created_with_wildcard_ip", ...)` row, so the operator team has central-log visibility into how many unrestricted tokens exist without parsing the audit DB.

## Bulk audit

Count tokens by mask shape:

```sql
SELECT allowed_ip_mask, count(*)
FROM service_bearer_tokens
WHERE status = 'active'
GROUP BY 1
ORDER BY 2 DESC;
```

Wildcards (`*.*.*.*`) and `*` patterns will surface at the top — useful for periodic review of "how many tokens are unrestricted" without operator-toil through web UI.

## Anti-patterns

- **DO NOT** set `allowed_ip_mask = NULL` — column is NOT NULL since Stage 155, the UPDATE will fail. Use `*.*.*.*` instead.
- **DO NOT** delete `service_bearer_tokens` rows directly to "force re-issue" — revoke through web UI (`status = 'revoked'`) so audit chain stays intact.
- **DO NOT** copy `token_hash` or `token_prefix` between tokens — they are unique constraints and reuse will violate them.
