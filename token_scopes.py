"""Scope registry and helpers for bearer-token access policies."""

from __future__ import annotations

import json
from collections.abc import Iterable

TOKEN_ACCESS_POLICY_VERSION = 1

SCOPE_CLIENTS_READ = "clients.read"
SCOPE_CLIENTS_WRITE = "clients.write"
SCOPE_PETS_READ = "pets.read"
SCOPE_PETS_WRITE = "pets.write"
SCOPE_ADMISSIONS_READ = "admissions.read"
SCOPE_ADMISSIONS_WRITE = "admissions.write"
SCOPE_MEDICAL_CARDS_READ = "medical_cards.read"
SCOPE_MEDICAL_CARDS_WRITE = "medical_cards.write"
SCOPE_FINANCE_READ = "finance.read"
SCOPE_FINANCE_WRITE = "finance.write"
SCOPE_INVENTORY_READ = "inventory.read"
SCOPE_INVENTORY_WRITE = "inventory.write"
SCOPE_USERS_READ = "users.read"
SCOPE_MESSAGING_READ = "messaging.read"
SCOPE_MESSAGING_WRITE = "messaging.write"
SCOPE_REFERENCE_READ = "reference.read"
SCOPE_ANALYTICS_READ = "analytics.read"

SUPPORTED_TOKEN_SCOPES = (
    SCOPE_ADMISSIONS_READ,
    SCOPE_ADMISSIONS_WRITE,
    SCOPE_ANALYTICS_READ,
    SCOPE_CLIENTS_READ,
    SCOPE_CLIENTS_WRITE,
    SCOPE_FINANCE_READ,
    SCOPE_FINANCE_WRITE,
    SCOPE_INVENTORY_READ,
    SCOPE_INVENTORY_WRITE,
    SCOPE_MEDICAL_CARDS_READ,
    SCOPE_MEDICAL_CARDS_WRITE,
    SCOPE_MESSAGING_READ,
    SCOPE_MESSAGING_WRITE,
    SCOPE_PETS_READ,
    SCOPE_PETS_WRITE,
    SCOPE_REFERENCE_READ,
    SCOPE_USERS_READ,
)

_READ_SCOPE_BY_ENTITY = {
    "admission": SCOPE_ADMISSIONS_READ,
    "breed": SCOPE_REFERENCE_READ,
    "cassa": SCOPE_FINANCE_READ,
    "cassaclose": SCOPE_FINANCE_READ,
    "city": SCOPE_REFERENCE_READ,
    "citytype": SCOPE_REFERENCE_READ,
    "client": SCOPE_CLIENTS_READ,
    "clinics": SCOPE_REFERENCE_READ,
    "closingofinvoices": SCOPE_FINANCE_READ,
    "combomanualitem": SCOPE_REFERENCE_READ,
    "combomanualname": SCOPE_REFERENCE_READ,
    "good": SCOPE_INVENTORY_READ,
    "goodgroup": SCOPE_INVENTORY_READ,
    "goodsaleparam": SCOPE_INVENTORY_READ,
    "hospital": SCOPE_MEDICAL_CARDS_READ,
    "hospitalblock": SCOPE_MEDICAL_CARDS_READ,
    "invoicedocument": SCOPE_FINANCE_READ,
    "invoice": SCOPE_FINANCE_READ,
    "medicalcards": SCOPE_MEDICAL_CARDS_READ,
    "messages": SCOPE_MESSAGING_READ,
    "partyaccount": SCOPE_INVENTORY_READ,
    "partyaccountdoc": SCOPE_INVENTORY_READ,
    "payment": SCOPE_FINANCE_READ,
    "pet": SCOPE_PETS_READ,
    "pettype": SCOPE_REFERENCE_READ,
    "properties": SCOPE_REFERENCE_READ,
    "role": SCOPE_REFERENCE_READ,
    "storedocument": SCOPE_INVENTORY_READ,
    "stores": SCOPE_INVENTORY_READ,
    "street": SCOPE_REFERENCE_READ,
    "suppliers": SCOPE_INVENTORY_READ,
    "timesheet": SCOPE_ANALYTICS_READ,
    "unit": SCOPE_REFERENCE_READ,
    "user": SCOPE_USERS_READ,
    "userposition": SCOPE_REFERENCE_READ,
}

_WRITE_SCOPE_BY_ENTITY = {
    "admission": SCOPE_ADMISSIONS_WRITE,
    "client": SCOPE_CLIENTS_WRITE,
    "good": SCOPE_INVENTORY_WRITE,
    "hospital": SCOPE_MEDICAL_CARDS_WRITE,
    "invoicedocument": SCOPE_FINANCE_WRITE,
    "invoice": SCOPE_FINANCE_WRITE,
    "medicalcards": SCOPE_MEDICAL_CARDS_WRITE,
    "messages": SCOPE_MESSAGING_WRITE,
    "payment": SCOPE_FINANCE_WRITE,
    "pet": SCOPE_PETS_WRITE,
}


def normalize_token_scopes(scopes: Iterable[str] | None) -> list[str]:
    """Return stable validated scopes list for storage and comparisons."""
    if scopes is None:
        scopes = SUPPORTED_TOKEN_SCOPES

    normalized: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for scope in scopes:
        value = scope.strip()
        if not value:
            continue
        if value not in SUPPORTED_TOKEN_SCOPES:
            unknown.append(value)
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    if unknown:
        raise ValueError(f"Unknown token scopes: {', '.join(sorted(unknown))}")

    return sorted(normalized)


def serialize_token_scopes(scopes: Iterable[str] | None) -> str:
    """Serialize validated scopes to stable JSON."""
    return json.dumps(normalize_token_scopes(scopes), ensure_ascii=True, sort_keys=False)


def deserialize_token_scopes(raw_value: str | None) -> list[str]:
    """Return stored scopes or legacy full-access defaults when absent."""
    if not raw_value:
        return normalize_token_scopes(None)
    loaded = json.loads(raw_value)
    if not isinstance(loaded, list):
        raise ValueError("Token scopes payload must be a JSON list.")
    return normalize_token_scopes(
        [value for value in loaded if isinstance(value, str)]
    )


def required_scope_for_request(method: str, path: str) -> str | None:
    """Return required coarse-grained scope for one REST request, if known."""
    normalized_method = method.strip().upper()
    normalized_path = path.split("?", 1)[0].strip("/")
    parts = [part.lower() for part in normalized_path.split("/") if part]
    if len(parts) < 3 or parts[0] != "rest" or parts[1] != "api":
        return None

    entity = parts[2]
    if normalized_method == "GET":
        return _READ_SCOPE_BY_ENTITY.get(entity)
    if normalized_method in {"POST", "PUT", "DELETE"}:
        return _WRITE_SCOPE_BY_ENTITY.get(entity)
    return None
