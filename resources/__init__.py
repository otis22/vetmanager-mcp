"""Entity-specific resource layer (stage 103c).

Resources own entity-specific VM field names, filter composition, and
aggregate-profile assembly. `tools/` modules import from here instead of
inlining the details — this keeps tool registration functions thin and
makes entity logic testable in isolation.

Currently implemented (focused subset of the full gateway scope):
- `client_profile.fetch(client_id)` — backs `get_client_profile` tool.
- `pet_profile.fetch(pet_id)` — backs `get_pet_profile` tool.

Extending: add new modules here as aggregator tools grow; keep simple
CRUD in `tools/crud_helpers` to avoid unnecessary layering.
"""
