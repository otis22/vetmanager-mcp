"""Stage 281: what the caller sends about itself does not enter our tracking.

Checked against 80 real production events on 2026-09-02 (newest and oldest of
every issue over two weeks). No email, JWT, bearer token, phone or personal
name was found anywhere — the sanitizer fires 3722 times across 260 places.

Two things did survive, and both survived for the same reason: their field name
happened to contain no familiar word. `X-Openai-Session` and `progressToken`
next to them were cleaned by the accident of the words "session" and "token".
Protection by coincidence is what these tests exist to end.
"""

from __future__ import annotations

import error_tracking


def _sanitize(event: dict) -> dict:
    return error_tracking._sanitize_event(event, None)


def _headers_of(event: dict) -> dict:
    return dict(event["request"]["headers"])


def test_the_caller_identity_header_is_filtered():
    """X-Openai-Subject rode into 4 of 80 production events untouched."""
    event = _sanitize({
        "request": {"headers": {
            "X-Openai-Subject": "v1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "X-Openai-Session": "sess-abcdefghijklmnop",
        }}
    })

    headers = _headers_of(event)
    assert headers["X-Openai-Subject"] == "[Filtered]"
    assert headers["X-Openai-Session"] == "[Filtered]"


def test_observability_headers_are_still_kept():
    """The point is to cut identity, not to blind the tracking."""
    event = _sanitize({
        "request": {"headers": {
            "x-request-id": "req-42",
            "user-agent": "mcp-client/1.0",
            "content-type": "application/json",
        }}
    })

    headers = _headers_of(event)
    assert headers["x-request-id"] == "req-42"
    assert headers["user-agent"] == "mcp-client/1.0"
    assert headers["content-type"] == "application/json"


def _frame_event(frame_vars: dict) -> dict:
    return {
        "exception": {"values": [{
            "value": "boom",
            "stacktrace": {"frames": [{"vars": frame_vars}]},
        }]}
    }


def _frame_vars(event: dict) -> dict:
    return event["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]


def test_caller_request_metadata_does_not_survive_a_stack_frame():
    """Headers are cleaned in request.headers; a copy of them in a local was not.

    The production events carried `x-codex-turn-metadata` — 310 characters
    including the caller's workspace filesystem path — inside `vars.meta_dict`.
    """
    event = _sanitize(_frame_event({
        "meta_dict": "{'x-codex-turn-metadata': {'workspaces': {'/root/x': 1}}, 'threadId': '01'}",
        "_meta": {"claudecode/toolUseId": "toolu_123"},
        "tool": "get_invoice_by_id",
    }))

    frame_vars = _frame_vars(event)
    assert frame_vars["meta_dict"] == "[Filtered]"
    assert frame_vars["_meta"] == "[Filtered]"
    assert frame_vars["tool"] == "get_invoice_by_id", "debugging context must survive"


def test_caller_metadata_is_cut_in_breadcrumbs_and_contexts_too():
    """The leak was found in a frame var; the same blob can ride anywhere."""
    event = _sanitize({
        "breadcrumbs": {"values": [{"data": {"meta_dict": "{'threadId': '01'}"}}]},
        "contexts": {"runtime": {"_meta": {"turn_id": "01"}, "name": "CPython"}},
    })

    assert event["breadcrumbs"]["values"][0]["data"]["meta_dict"] == "[Filtered]"
    assert event["contexts"]["runtime"]["_meta"] == "[Filtered]"


def test_a_bare_meta_key_is_not_swept_along():
    """`meta` alone is too common a word to redact blindly; the list is explicit."""
    event = _sanitize(_frame_event({"meta": "harmless", "metadata": "also harmless"}))

    frame_vars = _frame_vars(event)
    assert frame_vars["meta"] == "harmless"
    assert frame_vars["metadata"] == "also harmless"


def test_a_nested_copy_of_the_headers_is_cleaned_too():
    """Review of d8adec8: the sanitizer looked at the outer name only.

    `headers = dict(request.headers)` is an ordinary line — one exists in
    `auth_audit.py`. Captured in a frame, the whole header map rode through
    under the safe outer key `headers`, carrying exactly the values the header
    scrubber had just cleaned one level up.
    """
    event = _sanitize(_frame_event({
        "headers": {
            "x-openai-subject": "v1/aaaaaaaaaaaaaaaaaaaa",
            "authorization": "Bearer secret-token-value",
            "x-request-id": "req-42",
        },
        "tool": "get_invoice_by_id",
    }))

    headers = _frame_vars(event)["headers"]
    assert headers["x-openai-subject"] == "[Filtered]"
    assert headers["authorization"] == "[Filtered]"
    assert headers["x-request-id"] == "req-42", "observability must survive nesting too"
    assert _frame_vars(event)["tool"] == "get_invoice_by_id"


def test_caller_metadata_is_known_by_its_own_name_not_by_its_wrapper():
    """Review of d8adec8: the leaf names were only safe while wrapped.

    The same fields arriving as headers, in `extra`, or as their own frame var
    were untouched, so protection depended on the shape of the event.
    """
    event = _sanitize({
        "request": {"headers": {"X-Codex-Turn-Metadata": "{'workspaces': {'/root/x': 1}}"}},
        "extra": {"claudecode/toolUseId": "toolu_123", "threadId": "0199"},
    })

    assert event["request"]["headers"]["X-Codex-Turn-Metadata"] == "[Filtered]"
    assert event["extra"]["claudecode/toolUseId"] == "[Filtered]"
    assert event["extra"]["threadId"] == "[Filtered]"


def test_a_list_of_mappings_is_not_a_hiding_place():
    event = _sanitize(_frame_event({
        "batch": [{"authorization": "Bearer x"}, {"x-request-id": "req-7"}],
    }))

    batch = _frame_vars(event)["batch"]
    assert batch[0]["authorization"] == "[Filtered]"
    assert batch[1]["x-request-id"] == "req-7"


def test_recursion_stops_before_a_pathological_structure_costs_the_event():
    """Depth is bounded: a deep blob must not turn sanitizing into the failure."""
    deep: dict = {"authorization": "Bearer x"}
    for _ in range(40):
        deep = {"level": deep}

    event = _sanitize(_frame_event({"deep": deep}))

    assert event is not None
