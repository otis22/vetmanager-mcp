"""Stage 109.6: BC invariants for module-level state shared via re-exports.

`conftest._reset_vm_client_state` clears `vm_client._shared_http_clients`
and `vm_client._breakers` via `dict.clear()` — this works only if those
names point to the SAME dict objects as the canonical submodule globals.
If someone ever rewrites an import as `x = dict(vm_transport.pool._shared_http_clients)`
(creating a copy) the fixture silently stops working and test isolation
degrades.

Similarly asserts that `VetmanagerAuthContext` and
`resolve_bearer_auth_context` have one canonical class/function identity
across shim + canonical import paths.
"""

from __future__ import annotations


def test_shared_http_clients_dict_identity_preserved():
    """`vetmanager_client._shared_http_clients` must BE the same dict object
    as `vm_transport.pool._shared_http_clients`."""
    import vetmanager_client
    import vm_transport.pool

    assert (
        vetmanager_client._shared_http_clients is vm_transport.pool._shared_http_clients
    ), (
        "re-export broke dict identity — conftest dict.clear() will no longer "
        "reach the canonical pool state"
    )


def test_breakers_registry_identity_preserved():
    """`vetmanager_client._breakers` must BE the same dict as `vm_transport.breaker._breakers`."""
    import vetmanager_client
    import vm_transport.breaker

    assert (
        vetmanager_client._breakers is vm_transport.breaker._breakers
    ), (
        "re-export broke dict identity — conftest dict.clear() will no longer "
        "reach the canonical breaker registry"
    )


def test_vetmanager_auth_context_class_identity():
    """`vetmanager_auth.VetmanagerAuthContext` is literally
    `auth.context.VetmanagerAuthContext` (no duplicate class)."""
    import auth.context
    import vetmanager_auth

    assert vetmanager_auth.VetmanagerAuthContext is auth.context.VetmanagerAuthContext


def test_resolve_bearer_auth_context_function_identity():
    """`bearer_auth.resolve_bearer_auth_context` is same object as
    `auth.bearer.resolve_bearer_auth_context`."""
    import auth.bearer
    import bearer_auth

    assert bearer_auth.resolve_bearer_auth_context is auth.bearer.resolve_bearer_auth_context


def test_get_bearer_token_function_identity():
    """`request_auth.get_bearer_token` is same object as `auth.request.get_bearer_token`."""
    import auth.request
    import request_auth

    assert request_auth.get_bearer_token is auth.request.get_bearer_token


def test_gather_sections_function_identity():
    """`tools._aggregation.gather_sections` (shim) is same object as
    `resources._aggregation.gather_sections` (canonical)."""
    import resources._aggregation
    import tools._aggregation

    assert tools._aggregation.gather_sections is resources._aggregation.gather_sections


def test_active_admission_statuses_identity():
    """`tools.admission.ACTIVE_ADMISSION_STATUSES` is same tuple as
    `resources.admission_status.ACTIVE_ADMISSION_STATUSES`."""
    import resources.admission_status
    import tools.admission

    assert (
        tools.admission.ACTIVE_ADMISSION_STATUSES
        is resources.admission_status.ACTIVE_ADMISSION_STATUSES
    )
