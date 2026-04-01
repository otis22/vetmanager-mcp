"""Unit tests for IP mask validation and matching."""

import pytest

from domain_validation import validate_ip_mask, ip_matches_mask


# ── validate_ip_mask ─────────────────────────────────────────────────────────


def test_validate_accepts_wildcard_all():
    assert validate_ip_mask("*.*.*.*") == "*.*.*.*"


def test_validate_accepts_exact_ip():
    assert validate_ip_mask("192.168.1.100") == "192.168.1.100"


def test_validate_accepts_partial_wildcard():
    assert validate_ip_mask("192.168.1.*") == "192.168.1.*"
    assert validate_ip_mask("10.0.*.*") == "10.0.*.*"
    assert validate_ip_mask("10.*.*.*") == "10.*.*.*"


def test_validate_accepts_zero_octets():
    assert validate_ip_mask("0.0.0.1") == "0.0.0.1"
    assert validate_ip_mask("10.0.0.*") == "10.0.0.*"


def test_validate_strips_whitespace():
    assert validate_ip_mask("  192.168.1.* ") == "192.168.1.*"


def test_validate_rejects_0000():
    with pytest.raises(ValueError, match="0.0.0.0"):
        validate_ip_mask("0.0.0.0")


def test_validate_rejects_invalid_octet():
    with pytest.raises(ValueError):
        validate_ip_mask("256.1.1.1")


def test_validate_rejects_too_few_octets():
    with pytest.raises(ValueError):
        validate_ip_mask("192.168.1")


def test_validate_rejects_too_many_octets():
    with pytest.raises(ValueError):
        validate_ip_mask("192.168.1.1.1")


def test_validate_rejects_empty():
    with pytest.raises(ValueError):
        validate_ip_mask("")


def test_validate_rejects_alpha():
    with pytest.raises(ValueError):
        validate_ip_mask("abc.def.ghi.jkl")


def test_validate_rejects_negative():
    with pytest.raises(ValueError):
        validate_ip_mask("-1.0.0.1")


# ── ip_matches_mask ──────────────────────────────────────────────────────────


def test_matches_wildcard_all():
    assert ip_matches_mask("1.2.3.4", "*.*.*.*") is True
    assert ip_matches_mask("255.255.255.255", "*.*.*.*") is True


def test_matches_exact():
    assert ip_matches_mask("10.0.0.1", "10.0.0.1") is True


def test_no_match_exact():
    assert ip_matches_mask("10.0.0.2", "10.0.0.1") is False


def test_matches_partial_wildcard_last():
    assert ip_matches_mask("192.168.1.55", "192.168.1.*") is True
    assert ip_matches_mask("192.168.1.0", "192.168.1.*") is True


def test_no_match_partial_wildcard():
    assert ip_matches_mask("192.168.2.55", "192.168.1.*") is False


def test_matches_multi_wildcard():
    assert ip_matches_mask("10.0.5.99", "10.0.*.*") is True
    assert ip_matches_mask("10.0.0.0", "10.0.*.*") is True


def test_no_match_multi_wildcard():
    assert ip_matches_mask("10.1.0.0", "10.0.*.*") is False


def test_non_ipv4_returns_false():
    assert ip_matches_mask("not-an-ip", "10.0.0.1") is False
    assert ip_matches_mask("::1", "10.0.0.*") is False


def test_matches_first_octet_wildcard():
    assert ip_matches_mask("1.168.1.1", "*.168.1.1") is True
    assert ip_matches_mask("255.168.1.1", "*.168.1.1") is True
