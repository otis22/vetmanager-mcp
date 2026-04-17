#!/usr/bin/env python3
"""Field-mapping + phantom-enum lint for VM API call sites (stage 104.3/104.4).

Scans tools/*.py and prompts.py for:
1. Filter dicts: {"property": "X", "value": Y, "operator": "Z"} where X must
   be a known field name for the entity referenced by the enclosing URL path.
2. Payload dicts: {"field_name": value, ...} being passed to crud_create /
   crud_update on /rest/api/<entity>. Every key must be in the canonical
   field list for that entity.
3. Status filter value literals (phantom enum detection): e.g.
   {"property": "status", "value": "active", ...} where "active" is not a
   valid admission status.

Authoritative sources:
- artifacts/api-research-notes-ru.md "Поля и их реальные имена" checklist
- artifacts/api_entity_reference-ru.md

Exit codes:
  0 — no findings
  1 — high-severity findings present

Output: YAML findings identical to review_workflow_check.sh so super-review
can aggregate.

Usage:
  ./scripts/lint_api_contracts.py [--files path1.py,path2.py]
  ./scripts/lint_api_contracts.py  # scans all tools/*.py + prompts.py
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Canonical field dictionaries ────────────────────────────────────────────
# Sources: vetmanager-extjs Entity classes + api-research-notes-ru.md

ADMISSION_FIELDS = {
    "id", "user_id", "admission_date", "patient_id", "client_id", "status",
    "reason", "clinic_id", "type", "create_date", "edit_date",
    # Note: pet_id/doctor_id/date are INVALID — hot tip from baseline F1.
}

PET_FIELDS = {
    "id", "owner_id", "alias", "type_id", "breed_id", "sex", "birthday",
    "color_id", "chip_number", "weight", "status", "note", "old_id",
    "date_register", "create_date", "edit_date",
    # Note: client_id is INVALID per stage 77.4.
}

CLIENT_FIELDS = {
    "id", "last_name", "first_name", "middle_name", "address", "home_phone",
    "work_phone", "cell_phone", "email", "balance", "discount", "how_find",
    "type_id", "city_id", "street_id", "status", "last_visit_date",
    "registration_index", "norobot", "phone_prefix", "unsubscribe",
    "in_blacklist", "number_of_journal", "zip_code", "node_id", "flat",
    "passport_series", "vk_user_id", "date_register", "create_date",
    "edit_date", "office", "age",
}

INVOICE_FIELDS = {
    "id", "client_id", "pet_id", "create_date", "edit_date", "doctor_id",
    "description", "status", "paid_sum", "not_paid_sum", "discount",
    "discount_sum", "amount", "clinic_id", "payment_status", "cassa_id",
    "closed_by_user", "is_for_statistic",
}

MEDICAL_CARDS_FIELDS = {
    "id", "patient_id", "doctor_id", "clinic_id", "date_create",
    "description", "diagnos", "recommendations", "is_primary",
    "admission_id", "is_hospital", "prescriptions", "research_data",
    "meta_data",
    # Note: pet_id is INVALID for filter — use patient_id per stage 82.
}

TIMESHEET_FIELDS = {
    "id", "doctor_id", "begin_datetime", "end_datetime", "clinic_id",
    "title", "type", "cabinet_id", "service_id",
    # Note: user_id is INVALID — timesheet FK is doctor_id per stage 80.
}

# Entity → canonical field set mapping, keyed by lowercase REST path component.
ENTITY_FIELDS: dict[str, set[str]] = {
    "admission": ADMISSION_FIELDS,
    "pet": PET_FIELDS,
    "client": CLIENT_FIELDS,
    "invoice": INVOICE_FIELDS,
    "medicalcards": MEDICAL_CARDS_FIELDS,
    "timesheet": TIMESHEET_FIELDS,
}

# Known phantom/legacy field names per entity — flagged if seen as filter
# property or payload key. Reason shown in the finding.
PHANTOM_FIELDS: dict[str, dict[str, str]] = {
    "admission": {
        "pet_id": "admission.patient_id — stage 82 / F1 hot-fix",
        "doctor_id": "admission.user_id — stage 86 / F1 hot-fix",
        "date": "admission.admission_date — stage 86 / F1 hot-fix",
    },
    "pet": {
        "client_id": "pet.owner_id — stage 77.4 migration",
    },
    "medicalcards": {
        "pet_id": "MedicalCards.patient_id for CRUD filter (pet_id only valid on specialized action endpoints)",
    },
    "timesheet": {
        "user_id": "timesheet.doctor_id — stage 80 PRD canonical name",
    },
}

# Authoritative enum values per entity.status. If status filter or payload
# uses a value not in this set, flag as phantom enum.
STATUS_ENUMS: dict[str, set[str]] = {
    "admission": {
        "save", "directed", "accepted", "deleted", "delayed",
        "not_approved", "in_treatment", "not_confirmed",
    },
    "pet": {"alive", "not_alive", "archive"},
    "client": {"ACTIVE", "DELETED", "BLACKLIST"},
    "invoice": {"active", "deleted", "draft"},
}


# ── Finding emitter ─────────────────────────────────────────────────────────

_findings: list[dict] = []


def add_finding(
    severity: str,
    category: str,
    file: str,
    lines: str,
    problem: str,
    why: str,
    fix: str,
    confidence: float,
) -> None:
    _findings.append({
        "severity": severity,
        "category": category,
        "file": file,
        "lines": lines,
        "problem": problem,
        "why": why,
        "fix": fix,
        "confidence": confidence,
    })


def emit_yaml() -> None:
    for f in _findings:
        print("- severity:", f["severity"])
        print("  reviewer: lint-api-contracts")
        print("  category:", f["category"])
        print(f"  file: {f['file']}")
        print(f'  lines: "{f["lines"]}"')
        # YAML-escape problem by quoting double-quotes
        print(f'  problem: "{f["problem"].replace(chr(34), chr(92) + chr(34))}"')
        print(f'  why_it_matters: "{f["why"].replace(chr(34), chr(92) + chr(34))}"')
        print(f'  suggested_fix: "{f["fix"].replace(chr(34), chr(92) + chr(34))}"')
        print(f"  confidence: {f['confidence']}")
        print("  codex_verdict: null")


# ── AST scanner ─────────────────────────────────────────────────────────────


def resolve_entity_from_path(path_str: str) -> str | None:
    """Normalize '/rest/api/admission/42' → 'admission' (lowercase).

    Returns None if path doesn't match REST pattern.
    """
    if not path_str:
        return None
    parts = [p for p in path_str.lstrip("/").split("/") if p and not p.startswith("{")]
    if len(parts) >= 3 and parts[0].lower() == "rest" and parts[1].lower() == "api":
        return parts[2].lower()
    return None


def is_filter_dict(node: ast.expr) -> tuple[str, str] | None:
    """If node is a dict literal with 'property' and 'value' keys, return
    (property_value, value_value) as strings if literal, else None.

    Returns None if this is not a filter-shaped dict.
    """
    if not isinstance(node, ast.Dict):
        return None
    prop = None
    val = None
    for k, v in zip(node.keys, node.values):
        if not isinstance(k, ast.Constant):
            continue
        if k.value == "property":
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                prop = v.value
        elif k.value == "value":
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                val = v.value
    if prop is None:
        return None
    return (prop, val if val is not None else "")


def extract_path_from_call(call: ast.Call) -> str | None:
    """From vc.get('/rest/api/X', ...) or crud_list('/rest/api/X', ...)
    return the URL string literal if first arg is a constant."""
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def is_crud_call(call: ast.Call) -> str | None:
    """If call is vc.get/post/put/delete or crud_list/create/update/delete,
    return the CRUD operation name or None."""
    func = call.func
    name = None
    if isinstance(func, ast.Attribute):
        name = func.attr
    elif isinstance(func, ast.Name):
        name = func.id
    if name is None:
        return None
    if name in {"get", "post", "put", "delete"}:
        return name
    if name in {"crud_list", "crud_get_by_id", "crud_create", "crud_update", "crud_delete", "paginate_all"}:
        return name
    return None


def find_call_params_dict(call: ast.Call) -> ast.Dict | None:
    """For vc.get('/path', params={...}) — return the params dict if present."""
    for kw in call.keywords:
        if kw.arg == "params" and isinstance(kw.value, ast.Dict):
            return kw.value
    return None


def find_call_payload_dict(call: ast.Call, op: str) -> ast.Dict | None:
    """Return the payload dict literal based on the CRUD op signature.

    - crud_create(endpoint, payload) → args[1]
    - crud_update(endpoint, entity_id, payload) → args[2]
    - vc.post(path, json=payload) / vc.put(..., json=payload) → kw 'json'
    """
    if op == "crud_update":
        if len(call.args) >= 3 and isinstance(call.args[2], ast.Dict):
            return call.args[2]
    elif op == "crud_create":
        if len(call.args) >= 2 and isinstance(call.args[1], ast.Dict):
            return call.args[1]
    # json= keyword (vc.post / vc.put)
    for kw in call.keywords:
        if kw.arg == "json" and isinstance(kw.value, ast.Dict):
            return kw.value
    return None


def scan_filter_list(node: ast.expr, entity: str, file: str) -> None:
    """Walk a filter-list expression (list of dict literals) and flag phantom fields/values."""
    if not isinstance(node, ast.List):
        return
    for elt in node.elts:
        extracted = is_filter_dict(elt)
        if not extracted:
            continue
        prop, value = extracted
        line = elt.lineno

        # Phantom field
        phantom = PHANTOM_FIELDS.get(entity, {})
        if prop in phantom:
            add_finding(
                "high", "phantom_field", file, str(line),
                f'Filter property "{prop}" is not valid for /rest/api/{entity}',
                phantom[prop],
                f"Use the correct field name per artifacts/api-research-notes-ru.md checklist",
                0.92,
            )
            continue

        # Unknown field (only if we have canonical list for this entity)
        known = ENTITY_FIELDS.get(entity)
        if known and prop not in known:
            add_finding(
                "medium", "unknown_field", file, str(line),
                f'Filter property "{prop}" not in canonical {entity} field list',
                "May be valid field missing from this lint's canonical list, or a typo",
                f"Verify against vetmanager-extjs/rest/protected/models/{entity.capitalize()}.php; if valid, add to scripts/lint_api_contracts.py ENTITY_FIELDS",
                0.55,
            )

        # Phantom status enum
        if prop == "status" and entity in STATUS_ENUMS and value:
            valid = STATUS_ENUMS[entity]
            if value not in valid:
                # Check if it's an IN list (e.g. value list literal elsewhere)
                add_finding(
                    "high", "phantom_enum", file, str(line),
                    f'status="{value}" is not in valid {entity} enum',
                    f"Valid values: {sorted(valid)}",
                    f'Use IN operator with ACTIVE_ADMISSION_STATUSES tuple, or one of {sorted(valid)}',
                    0.88,
                )


def scan_payload_dict(payload: ast.Dict, entity: str, file: str) -> None:
    """Walk a payload dict (crud_create/crud_update 2nd arg) and flag phantom keys."""
    phantom = PHANTOM_FIELDS.get(entity, {})
    known = ENTITY_FIELDS.get(entity)
    for k in payload.keys:
        if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
            continue
        key = k.value
        line = k.lineno
        if key in phantom:
            add_finding(
                "blocker" if entity == "admission" else "high",
                "phantom_field_payload", file, str(line),
                f'Payload key "{key}" is not accepted by POST/PUT /rest/api/{entity}',
                phantom[key],
                f"Map at the API boundary: external MCP param name stays, payload key becomes the canonical one per checklist",
                0.95,
            )
        elif known and key not in known:
            add_finding(
                "medium", "unknown_payload_key", file, str(line),
                f'Payload key "{key}" not in canonical {entity} field list',
                "May be a typo or missing field from lint's canonical list",
                f"Verify against ExtJS entity class; add to lint if valid",
                0.55,
            )


def scan_file(path: Path) -> None:
    try:
        file_rel = str(path.relative_to(REPO_ROOT))
    except ValueError:
        file_rel = str(path)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=file_rel)
    except (OSError, SyntaxError):
        return

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        op = is_crud_call(node)
        if op is None:
            continue

        url_path = extract_path_from_call(node)
        entity = resolve_entity_from_path(url_path) if url_path else None
        if entity is None:
            continue

        # 1. Scan params={'filter': json.dumps([...])} — need to find the filter list
        params_dict = find_call_params_dict(node)
        if params_dict is not None:
            # Look for 'filter' key pointing to a json.dumps([...]) or direct list
            for k, v in zip(params_dict.keys, params_dict.values):
                if not (isinstance(k, ast.Constant) and k.value == "filter"):
                    continue
                # If json.dumps(<list>, ...) — inspect list arg
                if isinstance(v, ast.Call):
                    vfunc = v.func
                    if (isinstance(vfunc, ast.Attribute) and vfunc.attr == "dumps") or \
                       (isinstance(vfunc, ast.Name) and vfunc.id == "dumps"):
                        if v.args:
                            scan_filter_list(v.args[0], entity, file_rel)

        # 2. Scan 2nd/3rd arg / json= kwarg for crud_create / crud_update payloads
        if op in {"crud_create", "crud_update", "post", "put"}:
            payload = find_call_payload_dict(node, op)
            if payload is not None:
                scan_payload_dict(payload, entity, file_rel)

        # 3. Scan filters= kwarg if it's a direct List literal
        for kw in node.keywords:
            if kw.arg == "filters" and isinstance(kw.value, ast.List):
                scan_filter_list(kw.value, entity, file_rel)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=str, default="",
                        help="Comma-separated file paths (default: all tools/*.py + prompts.py)")
    args = parser.parse_args()

    if args.files:
        paths = [Path(p.strip()) for p in args.files.split(",") if p.strip()]
    else:
        paths = sorted((REPO_ROOT / "tools").glob("*.py"))
        prompts = REPO_ROOT / "prompts.py"
        if prompts.exists():
            paths.append(prompts)

    for p in paths:
        if p.exists():
            scan_file(p)

    if not _findings:
        return 0

    emit_yaml()
    # Exit 1 if any high/blocker findings
    if any(f["severity"] in {"high", "blocker"} for f in _findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
