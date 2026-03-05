"""Unit tests for input validation guards (Roadmap Stage 8) and limit schema (Stage 17)."""

import pytest
from validators import (
    LimitParam,
    VETMANAGER_MAX_LIMIT,
    build_list_query_params,
    validate_amount,
    validate_list_params,
)


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


class TestBuildListQueryParams:
    def test_builds_minimal_params(self):
        params = build_list_query_params(limit=20, offset=0)
        assert params == {"limit": 20, "offset": 0}

    def test_serializes_sort_and_filter_to_json(self):
        params = build_list_query_params(
            limit=20,
            offset=0,
            sort=[{"property": "title", "direction": "ASC"}],
            filters=[{"property": "state", "value": ["save", "deleted"], "operator": "in"}],
        )
        assert params["sort"] == '[{"property":"title","direction":"ASC"}]'
        assert params["filter"] == '[{"property":"state","value":["save","deleted"],"operator":"in"}]'

    def test_includes_manual_extra_filters(self):
        params = build_list_query_params(
            limit=10,
            offset=5,
            extra={"name": "Bob", "client_id": 16},
        )
        assert params["name"] == "Bob"
        assert params["client_id"] == 16

    def test_skips_empty_extra_values(self):
        params = build_list_query_params(
            limit=10,
            offset=0,
            extra={"name": "", "client_id": 0, "date": None, "active": False},
        )
        assert "name" not in params
        assert "client_id" not in params
        assert "date" not in params
        assert params["active"] is False


class TestLimitParamSchema:
    """Stage 17: limit parameter must expose minimum/maximum in MCP inputSchema."""

    def test_limit_param_constant(self):
        assert VETMANAGER_MAX_LIMIT == 100

    def test_limit_schema_has_min_max(self):
        """LimitParam used in tool params should produce schema with minimum=1, maximum=100."""
        from pydantic import create_model

        # Model with one field typed as LimitParam — same as tool params
        M = create_model("ToolParams", limit=(LimitParam, 20))
        schema = M.model_json_schema()
        limit_schema = schema["properties"]["limit"]
        assert limit_schema.get("minimum") == 1
        assert limit_schema.get("maximum") == VETMANAGER_MAX_LIMIT
        assert "description" in limit_schema
        assert "1" in str(limit_schema["description"]) and "100" in str(limit_schema["description"])
