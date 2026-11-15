"""Diagnostic evidence contains technical ownership only."""

import json
import inspect
import stat
import tracemalloc
import gc
import os
import socket
import asyncio
import weakref

import pytest

from tests.transport_diagnostics import safe_pool_snapshot, write_diagnostic


def test_session_probe_starts_before_first_node(monkeypatch, tmp_path):
    from tests.transport_diagnostics import start_session_diagnostics, transport_diagnostic
    monkeypatch.setattr('tests.transport_diagnostics.assert_warning_policy', lambda: None)
    from tests import conftest
    assert '@pytest.fixture(autouse=True)' in inspect.getsource(transport_diagnostic._fixture_function)
    assert conftest.pytest_sessionstart.__code__.co_names.count('start_session_diagnostics') == 1
    monkeypatch.setenv('REAL_JUNIT_DIR', str(tmp_path))
    if tracemalloc.is_tracing():
        tracemalloc.stop()
    start_session_diagnostics()
    assert tracemalloc.is_tracing()
    assert not list(tmp_path.iterdir())


def test_all_real_nodes_get_private_technical_snapshot(monkeypatch, tmp_path, request):
    from tests.transport_diagnostics import transport_diagnostic
    monkeypatch.setattr('tests.transport_diagnostics.assert_warning_policy', lambda: None)
    monkeypatch.setenv('REAL_JUNIT_DIR', str(tmp_path))
    probe = transport_diagnostic.__wrapped__(request)
    next(probe)
    with pytest.raises(StopIteration):
        next(probe)
    files = list(tmp_path.glob('transport-*.json'))
    assert len(files) == 1
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    text = files[0].read_text()
    for forbidden in ('SECRET_TOKEN', 'CLIENT_RESPONSE_BODY', 'Иван', 'https://', 'report-export/'):
        assert forbidden not in text


def test_connection_attribution_distinguishes_two_clients_without_payload():
    from tests.transport_diagnostics import connection_record, _client_pool_name
    import host_resolver
    from vm_transport import pool
    vm, resolver, task = FakeClient(), FakeClient(), object()
    vm_loop, resolver_loop = FakeLoop(), FakeLoop()
    vm_pool, resolver_pool = pool._shared_http_clients.copy(), host_resolver._shared_clients_by_loop.copy()
    try:
        pool._shared_http_clients.clear()
        host_resolver._shared_clients_by_loop.clear()
        pool._shared_http_clients[vm_loop] = vm
        host_resolver._shared_clients_by_loop[resolver_loop] = resolver
        first = connection_record(vm, task, 12, _client_pool_name(vm))
        second = connection_record(resolver, task, 13, _client_pool_name(resolver))
    finally:
        pool._shared_http_clients.clear()
        pool._shared_http_clients.update(vm_pool)
        host_resolver._shared_clients_by_loop.clear()
        host_resolver._shared_clients_by_loop.update(resolver_pool)
    assert first['client_id'] == id(vm) != second['client_id']
    assert first['socket_fd'] == 12 and second['socket_fd'] == 13
    assert first['task_id'] == second['task_id'] == id(task)
    assert first['pool'] == 'vm' and second['pool'] == 'resolver'
    text = json.dumps([first, second], ensure_ascii=False)
    for forbidden in ('SECRET_TOKEN', 'CLIENT_RESPONSE_BODY', 'Иван',
                      'https://', 'report-export/', 'private.example'):
        assert forbidden not in text


def test_oracle_charges_finalizer_to_current_node(monkeypatch):
    from tests.transport_diagnostics import ResourceOracle
    open_fds = {3}
    calls = []
    monkeypatch.setattr(gc, 'collect', lambda: calls.append('gc') or 1)
    oracle = ResourceOracle('node-a', lambda: set(open_fds))
    open_fds.add(7)
    oracle.finish([])
    assert calls == ['gc']


def test_oracle_does_not_charge_previous_node(monkeypatch):
    from tests.transport_diagnostics import ResourceOracle
    open_fds = {3}
    monkeypatch.setattr(gc, 'collect', lambda: 0)
    first = ResourceOracle('node-a', lambda: set(open_fds))
    first.finish([])
    second = ResourceOracle('node-b', lambda: set(open_fds))
    second.finish([])


def test_oracle_records_live_transport_without_fd_release_gate(monkeypatch):
    import weakref
    from tests.transport_diagnostics import ResourceOracle
    monkeypatch.setattr(gc, 'collect', lambda: 0)

    class Transport:
        closing = False

        def is_closing(self):
            return self.closing

    transport = Transport()
    oracle = ResourceOracle('node-a', lambda: {3})
    oracle.finish([], [weakref.ref(transport)])
    transport.closing = True
    oracle.finish([], [weakref.ref(transport)])


def test_fd_type_is_technical_and_owner_unknown_without_match(tmp_path):
    from tests.transport_diagnostics import describe_fd
    left, right = socket.socketpair()
    read_fd, write_fd = os.pipe()
    event_fd = os.eventfd(0)
    other_fd = os.open(os.devnull, os.O_RDONLY)
    try:
        rows = [describe_fd(fd) for fd in (left.fileno(), read_fd, event_fd, other_fd)]
        assert [row['kind'] for row in rows] == ['socket', 'pipe', 'eventfd', 'other']
        assert isinstance(rows[0]['domain'], int)
        assert isinstance(rows[0]['socket_type'], int)
        assert all(row['owner'] == 'unknown' for row in rows)
        text = json.dumps(rows, ensure_ascii=False)
        for forbidden in ('/dev/', '/proc/', 'https://', 'SECRET_TOKEN',
                          'CLIENT_RESPONSE_BODY', 'Иван', 'laddr', 'raddr'):
            assert forbidden not in text
    finally:
        left.close(); right.close()
        os.close(read_fd); os.close(write_fd); os.close(event_fd); os.close(other_fd)


def test_oracle_checks_only_after_successful_pool_cleanup(tmp_path):
    from tests.transport_diagnostics import ResourceOracle, snapshot_fds
    oracle = ResourceOracle('node-a', snapshot_fds)
    left, right = socket.socketpair()
    try:
        # The pool is allowed to hold a live connection during the node.
        assert left.fileno() in snapshot_fds()
    finally:
        left.close(); right.close()
    oracle.finish([], evidence_path=tmp_path / 'resource.json')
    path = tmp_path / 'resource.json'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())['extra'] == []


def test_unclosed_socket_is_typed_diagnostic_until_warning(tmp_path):
    from tests.transport_diagnostics import ResourceOracle, snapshot_fds
    oracle = ResourceOracle('node-a', snapshot_fds)
    left, right = socket.socketpair()
    try:
        oracle.finish([], evidence_path=tmp_path / 'resource.json')
        report = json.loads((tmp_path / 'resource.json').read_text())
        assert any(row['kind'] == 'socket' and row['owner'] == 'unknown'
                   for row in report['extra'])
    finally:
        left.close(); right.close()
    ResourceOracle('node-b', snapshot_fds).finish([])


@pytest.mark.asyncio
async def test_live_client_associated_task_is_an_ownership_error():
    import tests.transport_diagnostics as diagnostic
    client = FakeClient()
    client.is_closed = True
    task = asyncio.create_task(asyncio.Event().wait())
    diagnostic._created_clients.add(client)
    diagnostic._client_meta[client] = ('node-a', None)
    diagnostic._client_tasks[client] = weakref.WeakSet([task])
    try:
        assert any('live client task' in error for error in diagnostic.ownership_errors('node-a'))
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        diagnostic._created_clients.discard(client)
        diagnostic._client_meta.pop(client, None)
        diagnostic._client_tasks.pop(client, None)


class FakeLoop:
    def __init__(self):
        self.secret = 'SECRET_TOKEN'

    def is_closed(self):
        return False

    def __repr__(self):
        return 'https://private.example/report-export/locator Иван'


class FakeClient:
    is_closed = False
    response_body = 'CLIENT_RESPONSE_BODY'

    def __repr__(self):
        return 'SECRET_TOKEN CLIENT_RESPONSE_BODY Иван'


def test_snapshot_uses_only_technical_ids_and_states(tmp_path):
    snapshot = safe_pool_snapshot('vm', {FakeLoop(): FakeClient()})
    text = json.dumps(snapshot, ensure_ascii=False)
    assert set(snapshot) == {'pool', 'clients'}
    assert set(snapshot['clients'][0]) == {'loop_id', 'loop_type', 'loop_closed',
                                         'client_id', 'client_closed', 'client_allocation'}
    for forbidden in ('SECRET_TOKEN', 'CLIENT_RESPONSE_BODY', 'Иван',
                      'https://', 'report-export/', 'private.example'):
        assert forbidden not in text


def test_diagnostic_file_is_exclusive_0600_and_contains_no_payload(tmp_path):
    path = tmp_path / 'transport.json'
    write_diagnostic(path, {'before': safe_pool_snapshot('vm', {FakeLoop(): FakeClient()})})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert 'SECRET_TOKEN' not in path.read_text()
    try:
        write_diagnostic(path, {'before': {}})
    except FileExistsError:
        pass
    else:
        raise AssertionError('existing diagnostic file was overwritten')
