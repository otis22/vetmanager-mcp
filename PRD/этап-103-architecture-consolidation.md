# Этап 103. Architecture consolidation (low-risk subset)

## Scope (103 — this commit, low-risk parts only)

- 103.5 Inline `_get_request_headers` → `request_auth.py`, удалить `request_credentials.py`
- 103.6 Move `_instrumented_call` → `service_metrics.py::instrument_call` (с backward re-export)
- 103.7 Extract `tools/_aggregation.py::gather_sections` helper (section pattern shared between client_profile/pet_profile)
- 103.2 partial FilterBuilder caller migration: `tools/medical_card.py` + `tools/admission.py` get_admissions — 2 high-value call sites
- 103.8 Move `build_list_query_params` → оставляем в validators (migration cost > benefit сейчас; lazy import ok)

## Вне scope (103a/c)

- 103.1 auth/ package full refactor — high regression risk, нужен focused session
- 103.3 resources/<entity>.py gateway layer — big architectural shift
- 103.4 vetmanager_client.py split (574 LOC) — orthogonal refactor
