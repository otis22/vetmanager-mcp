"""OAuth Bearer challenge helpers for ChatGPT Apps linking."""

from __future__ import annotations

from oauth_metadata import get_protected_resource_metadata_url


def build_oauth_bearer_challenge(
    *,
    scope: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> str:
    parts = [
        "Bearer",
        f'resource_metadata="{get_protected_resource_metadata_url()}"',
    ]
    if scope:
        parts.append(f'scope="{scope}"')
    if error:
        parts.append(f'error="{error}"')
    if error_description:
        safe_description = error_description.replace('"', "'")
        parts.append(f'error_description="{safe_description}"')
    return " ".join(parts)


def oauth_challenge_details(
    *,
    scope: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> dict[str, str | list[str]]:
    challenge = build_oauth_bearer_challenge(
        scope=scope,
        error=error,
        error_description=error_description,
    )
    return {
        "www_authenticate": challenge,
        "mcp/www_authenticate": [challenge],
    }
