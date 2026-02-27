"""Unit tests for input validation guards (Roadmap Stage 8)."""

import pytest
from validators import validate_amount, validate_list_params


class TestValidateListParams:
    def test_default_params_ok(self):
        validate_list_params(20, 0)  # should not raise

    def test_limit_min_ok(self):
        validate_list_params(1, 0)

    def test_limit_max_ok(self):
        validate_list_params(100, 0)

    def test_limit_zero_raises(self):
        with pytest.raises(ValueError, match="limit"):
            validate_list_params(0, 0)

    def test_limit_negative_raises(self):
        with pytest.raises(ValueError, match="limit"):
            validate_list_params(-1, 0)

    def test_limit_over_max_raises(self):
        with pytest.raises(ValueError, match="limit"):
            validate_list_params(101, 0)

    def test_limit_far_over_raises(self):
        with pytest.raises(ValueError, match="limit"):
            validate_list_params(1000, 0)

    def test_offset_zero_ok(self):
        validate_list_params(20, 0)

    def test_offset_max_ok(self):
        validate_list_params(20, 10_000)

    def test_offset_over_max_raises(self):
        with pytest.raises(ValueError, match="offset"):
            validate_list_params(20, 10_001)

    def test_offset_negative_raises(self):
        with pytest.raises(ValueError, match="offset"):
            validate_list_params(20, -1)

    def test_error_message_contains_pagination_hint(self):
        with pytest.raises(ValueError, match="pagination"):
            validate_list_params(200, 0)

    def test_error_message_contains_refine_hint(self):
        with pytest.raises(ValueError, match="refine"):
            validate_list_params(20, 99_999)


class TestValidateAmount:
    def test_small_amount_ok(self):
        validate_amount(0.01)

    def test_large_amount_ok(self):
        validate_amount(1_000_000)

    def test_typical_amount_ok(self):
        validate_amount(1500.0)

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="amount"):
            validate_amount(0)

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="amount"):
            validate_amount(-100)

    def test_over_max_raises(self):
        with pytest.raises(ValueError, match="amount"):
            validate_amount(1_000_001)

    def test_far_over_max_raises(self):
        with pytest.raises(ValueError, match="amount"):
            validate_amount(50_000_000)

    def test_error_message_mentions_kopecks(self):
        with pytest.raises(ValueError, match="kopecks"):
            validate_amount(1_500_000)
