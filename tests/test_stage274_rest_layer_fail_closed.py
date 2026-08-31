"""Stage 274 — the second layer stops waving through what it does not know.

`required_scope_for_request` returning None used to mean "no rights needed", so
the check meant to catch a tool reaching past its own declaration let exactly
that case through. Writing is closed here; reading gets one release of being
watched first, because a wrongly refused read breaks everything at once while a
wrongly refused write breaks one workflow.
"""

import ast
import pathlib

import pytest

from token_scopes import (
    REQUEST_NOT_MAPPED,
    SCOPE_INVENTORY_WRITE,
    required_scope_for_request,
)

SOURCE_DIRECTORIES = ("tools", "resources")

# How a call names the method it will use. `crud_*` wrap the verb, so the verb
# is in the function name rather than next to the path; `_vm_get` wraps a get,
# and `_call_vm` carries the verb as its first argument.
METHOD_IN_FIRST_ARGUMENT = {"_call_vm"}
CALL_METHODS = {
    "_vm_get": "GET",
    "crud_list": "GET",
    "crud_get_by_id": "GET",
    "crud_create": "POST",
    "crud_update": "PUT",
    "crud_delete": "DELETE",
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "delete": "DELETE",
}


def _constant_paths(tree):
    """Module-level string constants, so `_MC_ENDPOINT` resolves to its path."""
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = node.value.value
    return found


def _called_name(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _first_path_argument(call, constants):
    for argument in call.args:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            return argument.value
        if isinstance(argument, ast.Name) and argument.id in constants:
            return constants[argument.id]
        if isinstance(argument, ast.JoinedStr):
            rendered = ""
            for part in argument.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    rendered += part.value
                else:
                    rendered += "1"
            return rendered
        return None
    return None


def _rest_calls():
    """Every (method, path) this service asks Vetmanager for, read from source.

    Not a regex over path literals: the verb usually lives in the helper's name,
    so a literal scan would happily call a writing path read-only.
    """
    calls = set()
    for directory in SOURCE_DIRECTORIES:
        for source_file in sorted(pathlib.Path(directory).glob("*.py")):
            tree = ast.parse(source_file.read_text())
            constants = _constant_paths(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _called_name(node.func)
                if name in METHOD_IN_FIRST_ARGUMENT:
                    if not node.args or not isinstance(node.args[0], ast.Constant):
                        continue
                    method = str(node.args[0].value).upper()
                    path = _first_path_argument(
                        ast.Call(func=node.func, args=node.args[1:], keywords=[]), constants
                    )
                else:
                    method = CALL_METHODS.get(name)
                    if method is None:
                        continue
                    path = _first_path_argument(node, constants)
                if not path or not path.startswith("/rest/api/"):
                    continue
                calls.add((method, path, str(source_file)))
    return calls


def test_the_scan_actually_finds_the_calls():
    """A scanner that quietly finds nothing would make every check below pass."""
    calls = _rest_calls()

    assert len(calls) > 40, len(calls)
    assert any(method == "POST" for method, _, _ in calls)
    assert any(method == "PUT" for method, _, _ in calls)
    assert any(path.endswith("MedicalCards") for _, path, _ in calls)
    # Wrapper call sites: the path never appears next to a verb there, and a
    # scanner that only understood direct calls would report them as absent.
    assert any("productsDataForInvoice" in path for _, path, _ in calls)
    assert any(path.startswith("/rest/api/report-ai-job") for _, path, _ in calls)


def test_every_call_the_service_makes_has_a_required_right():
    """The point of closing the layer: after this, an unmapped path is refused,
    so an unmapped path has to be impossible to write by accident."""
    unmapped = sorted(
        f"{method} {path} ({where})"
        for method, path, where in _rest_calls()
        if required_scope_for_request(method, path.replace("{", "1").replace("}", "")) in (None, REQUEST_NOT_MAPPED)
    )

    assert not unmapped, "\n".join(unmapped)


def test_suppliers_writing_needs_the_inventory_right():
    assert required_scope_for_request("POST", "/rest/api/Suppliers") == SCOPE_INVENTORY_WRITE
    assert required_scope_for_request("PUT", "/rest/api/Suppliers/5") == SCOPE_INVENTORY_WRITE


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_an_unknown_writing_path_is_refused(method):
    assert required_scope_for_request(method, "/rest/api/somethingNew") == REQUEST_NOT_MAPPED


@pytest.mark.parametrize("method", ["PATCH", "HEAD", "OPTIONS", "TRACE"])
def test_a_method_the_layer_does_not_know_is_refused(method):
    """`_request` can send any verb. Without this, a future PATCH would walk
    straight past the closed door."""
    assert required_scope_for_request(method, "/rest/api/client/5") == REQUEST_NOT_MAPPED


def test_an_unknown_reading_path_is_still_allowed_for_now():
    """Reading is watched for one release before it is closed: a wrongly
    refused read breaks every listing at once."""
    assert required_scope_for_request("GET", "/rest/api/somethingNew") is None


def _client_with_everything():
    from tests.runtime_factories import make_client_with_resolved_runtime
    from token_scopes import SUPPORTED_TOKEN_SCOPES

    return make_client_with_resolved_runtime(
        "clinic.example", "key", scopes=tuple(SUPPORTED_TOKEN_SCOPES)
    )


@pytest.mark.asyncio
async def test_the_client_refuses_an_unmapped_write_even_with_every_right():
    """Through the client, not the pure function: a rule the request path never
    reaches is green in tests and absent in production."""
    from exceptions import AuthError

    client = _client_with_everything()

    with pytest.raises(AuthError) as refused:
        await client.post("/rest/api/somethingNew", json={})

    assert refused.value.status_code == 403
    # The refusal must not name a scope: none exists to ask for, and inviting
    # the caller to request one would send them to their administrator for
    # nothing.
    assert "scope" not in str(refused.value).lower()


@pytest.mark.asyncio
async def test_an_unmapped_read_passes_and_leaves_a_trace(monkeypatch, caplog):
    """The decision to close reading rests on this counter. If the read went
    through silently, a release of watching would prove nothing."""
    import service_metrics

    seen = []
    monkeypatch.setattr(service_metrics, "record_rest_unmapped_read", lambda: seen.append(1))
    import vetmanager_client

    monkeypatch.setattr(vetmanager_client, "record_rest_unmapped_read", lambda: seen.append(1))

    client = _client_with_everything()
    with caplog.at_level("WARNING"):
        # Reaching the network is not the point; the scope gate runs first.
        with pytest.raises(Exception):
            await client.get("/rest/api/somethingNew")

    assert seen, "an unmapped read was not counted"
    assert "rest_scope_unmapped_read" in caplog.text


@pytest.mark.asyncio
async def test_the_trace_of_an_unmapped_read_carries_no_record_data(monkeypatch, caplog):
    """An unmapped path is one nobody has looked at yet; its tail may hold a
    record id or a phone number, and this warning is written before anyone
    decides the path is safe to quote."""
    client = _client_with_everything()

    with caplog.at_level("WARNING"):
        with pytest.raises(Exception):
            await client.get("/rest/api/somethingNew/79184140259/details")

    written = [
        record for record in caplog.records if record.getMessage() == "rest_scope_unmapped_read"
    ]
    assert written, "the unmapped read left no trace at all"
    entity = getattr(written[0], "entity", "")
    assert entity == "rest/api/somethingNew", entity
    assert all("79184140259" not in str(value) for value in vars(written[0]).values())


def test_the_metric_is_exported_for_reading_on_the_server():
    """A counter that never reaches /metrics cannot be checked on production,
    and 'zero for a release' would mean nothing."""
    from service_metrics import render_prometheus_metrics

    assert "vetmanager_rest_unmapped_read_total" in render_prometheus_metrics()
