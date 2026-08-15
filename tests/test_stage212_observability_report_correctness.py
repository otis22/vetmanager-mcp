"""Regression coverage for Stage 212 observability/report period semantics."""

from __future__ import annotations

import json
from pathlib import Path


def test_activation_event_panel_filters_only_persisted_event_names() -> None:
    dashboard = json.loads(
        (Path(__file__).resolve().parent.parent / "ops/grafana/dashboards/vetmanager-overview.json").read_text(
            encoding="utf-8"
        )
    )
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    events_expr = panels["Activation events"]["targets"][0]["expr"]
    funnel_expr = panels["Activation funnel"]["targets"][0]["expr"]

    assert 'event=~"integration_failed|integration_saved|token_copied"' in events_expr
    assert "token_issued" not in events_expr
    assert "first_mcp_request" not in events_expr
    assert funnel_expr == "vetmanager_activation_funnel_accounts"
