"""Backward-compat shim — canonical location is `resources._aggregation`.

Stage 106.3 (F5 fix): `gather_sections` moved to the `resources/` layer
to eliminate the `resources → tools` import cycle. New callers MUST
import from `resources._aggregation`; this shim keeps legacy imports
from `tools._aggregation` working.

## Policy (stage 114b decision, 2026-04-19)

**KEEP** — explicit owner policy (option "keep all BC shims"):
- `tests/test_stage109_bc_invariants.py::test_tools_aggregation_shim_identity`
  asserts `tools._aggregation.gather_sections is resources._aggregation.gather_sections`
  — deletion requires coordinated test removal.
- Removal ROI is low: 9 LOC shim vs. migration cost. No production callers
  currently import from `tools._aggregation`.
- If re-visited: grep for `from tools._aggregation` / `import tools._aggregation`
  → 0 matches → safe to delete with BC-test update in one commit. Postponed
  until a migration trigger appears (e.g. circular-import emergence).
"""

from resources._aggregation import gather_sections  # noqa: F401
