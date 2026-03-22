"""Source of truth for test warning policy."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SuiteWarningPolicy:
    """Warning contract for one test contour."""

    name: str
    warnings_allowed: int
    ci_blocking: bool
    global_filterwarnings_allowed: bool
    scoped_suppression_only: bool


BLOCKING_WARNING_CATEGORIES = (
    "DeprecationWarning",
    "PendingDeprecationWarning",
    "RuntimeWarning",
    "ResourceWarning",
    "pytest.PytestWarning",
)


DEFAULT_SUITE_WARNING_POLICY = SuiteWarningPolicy(
    name="default",
    warnings_allowed=0,
    ci_blocking=True,
    global_filterwarnings_allowed=False,
    scoped_suppression_only=True,
)


OPT_IN_REAL_SUITE_WARNING_POLICY = SuiteWarningPolicy(
    name="opt_in_real",
    warnings_allowed=0,
    ci_blocking=False,
    global_filterwarnings_allowed=False,
    scoped_suppression_only=True,
)
