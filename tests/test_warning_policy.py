from configparser import ConfigParser
from pathlib import Path

from warning_policy import (
    BLOCKING_WARNING_CATEGORIES,
    DEFAULT_SUITE_WARNING_POLICY,
    OPT_IN_REAL_SUITE_WARNING_POLICY,
    build_warning_error_flags,
)


def test_default_suite_warning_policy_requires_zero_warnings():
    assert DEFAULT_SUITE_WARNING_POLICY.name == "default"
    assert DEFAULT_SUITE_WARNING_POLICY.warnings_allowed == 0
    assert DEFAULT_SUITE_WARNING_POLICY.ci_blocking is True
    assert DEFAULT_SUITE_WARNING_POLICY.global_filterwarnings_allowed is False
    assert DEFAULT_SUITE_WARNING_POLICY.scoped_suppression_only is True


def test_opt_in_real_suite_policy_is_not_required_for_default_ci():
    assert OPT_IN_REAL_SUITE_WARNING_POLICY.name == "opt_in_real"
    assert OPT_IN_REAL_SUITE_WARNING_POLICY.warnings_allowed == 0
    assert OPT_IN_REAL_SUITE_WARNING_POLICY.ci_blocking is False
    assert OPT_IN_REAL_SUITE_WARNING_POLICY.global_filterwarnings_allowed is False
    assert OPT_IN_REAL_SUITE_WARNING_POLICY.scoped_suppression_only is True


def test_blocking_warning_categories_cover_deprecations_and_runtime_signals():
    assert "DeprecationWarning" in BLOCKING_WARNING_CATEGORIES
    assert "PendingDeprecationWarning" in BLOCKING_WARNING_CATEGORIES
    assert "RuntimeWarning" in BLOCKING_WARNING_CATEGORIES
    assert "ResourceWarning" in BLOCKING_WARNING_CATEGORIES
    assert "pytest.PytestWarning" in BLOCKING_WARNING_CATEGORIES


def test_warning_error_flags_match_blocking_categories():
    assert build_warning_error_flags() == ("error",)


def test_pytest_ini_has_no_global_filterwarnings_policy():
    config = ConfigParser()
    config.read(Path("pytest.ini"), encoding="utf-8")

    assert config.has_section("pytest")
    assert not config.has_option("pytest", "filterwarnings")
