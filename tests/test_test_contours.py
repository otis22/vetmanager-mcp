"""Guardrails for named pytest contours used by local runs and CI."""

from test_contours import (
    DEFAULT_TEST_CONTOUR,
    FAST_TEST_CONTOUR,
    OPT_IN_REAL_TEST_CONTOUR,
    TEST_CONTOURS,
)


def test_test_contour_names_are_stable():
    assert tuple(TEST_CONTOURS) == ("fast", "default", "opt_in_real")


def test_fast_contour_excludes_browser_and_real_markers():
    assert FAST_TEST_CONTOUR.marker_expression == (
        "not browser and not real_api and not real_browser"
    )


def test_default_contour_excludes_only_real_markers():
    assert DEFAULT_TEST_CONTOUR.marker_expression == "not real_api and not real_browser"


def test_opt_in_real_contour_targets_only_real_markers():
    assert OPT_IN_REAL_TEST_CONTOUR.marker_expression == "real_api or real_browser"
