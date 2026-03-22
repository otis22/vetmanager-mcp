"""Shared test-contour definitions for local runs and CI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TestContour:
    """Named pytest contour with a stable marker expression."""

    name: str
    marker_expression: str
    description: str


FAST_TEST_CONTOUR = TestContour(
    name="fast",
    marker_expression="not browser and not real_api and not real_browser",
    description="Fast inner-loop suite without browser or real contour tests.",
)

DEFAULT_TEST_CONTOUR = TestContour(
    name="default",
    marker_expression="not real_api and not real_browser",
    description="Required suite with unit/mock/live-browser coverage but no real contour.",
)

OPT_IN_REAL_TEST_CONTOUR = TestContour(
    name="opt_in_real",
    marker_expression="real_api or real_browser",
    description="Opt-in contour covering real Vetmanager API and browser flows.",
)

TEST_CONTOURS = {
    FAST_TEST_CONTOUR.name: FAST_TEST_CONTOUR,
    DEFAULT_TEST_CONTOUR.name: DEFAULT_TEST_CONTOUR,
    OPT_IN_REAL_TEST_CONTOUR.name: OPT_IN_REAL_TEST_CONTOUR,
}


def get_test_contour(name: str) -> TestContour:
    """Return one named contour or raise a stable configuration error."""
    try:
        return TEST_CONTOURS[name]
    except KeyError as exc:  # pragma: no cover - defensive programming
        raise ValueError(f"Unknown test contour: {name}") from exc
