"""Stage 93 — FilterBuilder for VM REST `filter` query parameter."""

from __future__ import annotations

import json

import pytest

from filters import (
    Filter,
    FilterOp,
    as_dict_list,
    build_list_query_params,
    eq,
    gt,
    gte,
    in_,
    like,
    lt,
    lte,
    ne,
    not_in,
)


# ── Individual helpers ──────────────────────────────────────────────────────


def test_eq_produces_canonical_dict():
    f = eq("status", "ACTIVE")
    assert f.to_dict() == {
        "property": "status", "value": "ACTIVE", "operator": "=",
    }


def test_ne_produces_canonical_dict():
    f = ne("status", "deleted")
    assert f.to_dict() == {
        "property": "status", "value": "deleted", "operator": "!=",
    }


def test_lt_gt_lte_gte_operators():
    assert lt("price", 100).to_dict()["operator"] == "<"
    assert lte("price", 100).to_dict()["operator"] == "<="
    assert gt("price", 100).to_dict()["operator"] == ">"
    assert gte("price", 100).to_dict()["operator"] == ">="


def test_in_preserves_values_as_list():
    f = in_("id", [1, 2, 3])
    d = f.to_dict()
    assert d["property"] == "id"
    assert d["value"] == [1, 2, 3]
    assert d["operator"] == "IN"


def test_in_rejects_non_list_value():
    with pytest.raises(TypeError):
        in_("id", "1,2,3")  # type: ignore[arg-type]


def test_not_in_operator_uppercased():
    f = not_in("status", ["deleted", "not_approved"])
    assert f.to_dict()["operator"] == "NOT IN"


def test_like_operator():
    f = like("alias", "Rex%")
    assert f.to_dict() == {
        "property": "alias", "value": "Rex%", "operator": "LIKE",
    }


# ── as_dict_list ────────────────────────────────────────────────────────────


def test_as_dict_list_handles_filter_objects():
    result = as_dict_list([eq("a", 1), in_("b", [2, 3])])
    assert result == [
        {"property": "a", "value": 1, "operator": "="},
        {"property": "b", "value": [2, 3], "operator": "IN"},
    ]


def test_as_dict_list_passes_through_raw_dicts():
    raw = [{"property": "x", "value": 1, "operator": "="}]
    assert as_dict_list(raw) == raw


def test_as_dict_list_accepts_mixed():
    """Gradual migration: callers can mix Filter and raw dicts in one list."""
    mixed = [
        eq("status", "ACTIVE"),
        {"property": "legacy", "value": "y", "operator": "="},
    ]
    result = as_dict_list(mixed)
    assert result == [
        {"property": "status", "value": "ACTIVE", "operator": "="},
        {"property": "legacy", "value": "y", "operator": "="},
    ]


def test_as_dict_list_returns_none_for_empty():
    assert as_dict_list(None) is None
    assert as_dict_list([]) is None


def test_as_dict_list_rejects_garbage_items():
    with pytest.raises(TypeError):
        as_dict_list(["not a filter"])  # type: ignore[list-item]


# ── Integration with build_list_query_params ────────────────────────────────


def test_build_list_query_params_accepts_filter_objects():
    params = build_list_query_params(
        limit=20, offset=0,
        filters=[eq("status", "ACTIVE"), in_("id", [1, 2])],
    )
    # Filter JSON string — parse and verify structure
    filter_json = params["filter"]
    parsed = json.loads(filter_json)
    assert parsed == [
        {"property": "status", "value": "ACTIVE", "operator": "="},
        {"property": "id", "value": [1, 2], "operator": "IN"},
    ]


def test_build_list_query_params_filter_objects_equivalent_to_raw_dicts():
    """Builder output must be byte-identical to the legacy raw-dict path so
    migrating a caller does not change the wire format."""
    from_builder = build_list_query_params(
        limit=20, offset=0, filters=[eq("status", "ACTIVE")],
    )
    from_raw = build_list_query_params(
        limit=20, offset=0,
        filters=[{"property": "status", "value": "ACTIVE", "operator": "="}],
    )
    assert from_builder["filter"] == from_raw["filter"]


def test_build_list_query_params_empty_filter_list_omits_param():
    params = build_list_query_params(limit=10, offset=0, filters=[])
    assert "filter" not in params


# ── Frozen dataclass invariants ─────────────────────────────────────────────


def test_filter_is_immutable():
    import dataclasses
    f = eq("x", 1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.property = "y"  # type: ignore[misc]


def test_filter_op_values_are_canonical_uppercase_for_set_operators():
    assert FilterOp.IN.value == "IN"
    assert FilterOp.NOT_IN.value == "NOT IN"
    assert FilterOp.LIKE.value == "LIKE"
