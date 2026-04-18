"""Backward-compat shim — canonical location is `resources._aggregation`.

Stage 106.3 (F5 fix): `gather_sections` moved to the `resources/` layer
to eliminate the `resources → tools` import cycle. New callers should
import from `resources._aggregation`; this shim keeps existing imports
from `tools._aggregation` working.
"""

from resources._aggregation import gather_sections  # noqa: F401
