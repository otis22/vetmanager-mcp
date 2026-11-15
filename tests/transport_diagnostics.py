"""Test-only, secret-free ownership evidence for intermittent HTTP warnings."""

from __future__ import annotations

import json
import os
import asyncio
import contextvars
import gc
import hashlib
import socket
import stat
import weakref
import warnings
from pathlib import Path
import tracemalloc

import pytest
import anyio
import httpx

import host_resolver
from vm_transport import pool

_active_client = contextvars.ContextVar('diagnostic_client', default=None)
_node_connections = contextvars.ContextVar('diagnostic_connections', default=None)
_node_transports = contextvars.ContextVar('diagnostic_transports', default=None)
_hooks_installed = False
_created_clients = weakref.WeakSet()
_client_meta = weakref.WeakKeyDictionary()
_client_tasks = weakref.WeakKeyDictionary()
_active_node = contextvars.ContextVar('diagnostic_node', default=None)
_fixture_scope = contextvars.ContextVar('diagnostic_fixture_scope', default=None)


def assert_warning_policy():
    """The real contour must keep the existing stronger -W error contract."""
    for category in (ResourceWarning, pytest.PytestUnraisableExceptionWarning):
        try:
            warnings.warn('stage459 warning policy probe', category, stacklevel=1)
        except category:
            continue
        raise AssertionError(f'{category.__name__} must be an error')


def set_active_node(node):
    return _active_node.set(node)


def reset_active_node(token):
    _active_node.reset(token)


def set_fixture_scope(scope):
    return _fixture_scope.set(scope)


def reset_fixture_scope(token):
    _fixture_scope.reset(token)


def _pool_client_ids():
    return {id(client) for client in pool._shared_http_clients.values()} | {
        id(client) for client in host_resolver._shared_clients_by_loop.values()}


def ownership_errors(node=None, final=False):
    registered = _pool_client_ids()
    errors = []
    if final and (pool._shared_http_clients or host_resolver._shared_clients_by_loop):
        errors.append('client registry not empty')
    for client in list(_created_clients):
        created_node, scope = _client_meta.get(client, (None, None))
        if not final and (created_node != node or scope == 'session'):
            continue
        if not client.is_closed and (final or id(client) not in registered):
            errors.append(f'open AsyncClient {id(client)}')
        tasks = _client_tasks.get(client, ())
        if any(not task.done() for task in list(tasks)):
            errors.append(f'live client task {id(client)}')
    return errors


def open_fd_ids():
    """Linux fd numbers only; never readlink targets or socket addresses."""
    return {int(name) for name in os.listdir('/proc/self/fd') if name.isdecimal()}


def describe_fd(fd):
    """Classify an fd without recording a target path or socket address."""
    try:
        info = os.fstat(fd)
    except OSError:
        return {'fd': fd, 'kind': 'unknown', 'identity': None, 'domain': None,
                'socket_type': None, 'owner': 'unknown'}
    kind = 'other'
    domain = socket_type = None
    if stat.S_ISSOCK(info.st_mode):
        kind = 'socket'
        handle = socket.socket(fileno=fd)
        try:
            domain = handle.getsockopt(socket.SOL_SOCKET, socket.SO_DOMAIN)
            socket_type = handle.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        finally:
            handle.detach()
    elif stat.S_ISFIFO(info.st_mode):
        kind = 'pipe'
    else:
        # Inspect only a fixed kernel label; never store the symlink target.
        try:
            target = os.readlink(f'/proc/self/fd/{fd}')
        except OSError:
            target = ''
        if target == 'anon_inode:[eventfd]':
            kind = 'eventfd'
        elif target.startswith('anon_inode:'):
            kind = 'anon_inode'
    return {'fd': fd, 'kind': kind, 'identity': [info.st_dev, info.st_ino],
            'domain': domain, 'socket_type': socket_type, 'owner': 'unknown'}


def snapshot_fds():
    return {fd: row for fd in open_fd_ids()
            if (row := describe_fd(fd))['identity'] is not None}


def _fd_map(snapshot):
    if isinstance(snapshot, dict):
        return snapshot
    return {fd: {'fd': fd, 'kind': 'unknown', 'identity': None,
                 'domain': None, 'socket_type': None, 'owner': 'unknown'}
            for fd in snapshot}


class ResourceOracle:
    def __init__(self, node, fd_reader=snapshot_fds):
        self.node = node
        self.fd_reader = fd_reader
        self.before = _fd_map(fd_reader())

    @property
    def evidence_filename(self):
        return f'resource-{hashlib.sha256(self.node.encode()).hexdigest()[:16]}.json'

    def finish(self, connections, transports=(), evidence_path=None):
        # Force finalizers before pytest advances to the next node. Warnings-as-errors
        # and pytest's unraisable collector remain active; this is detection only.
        gc.collect()
        after = _fd_map(self.fd_reader())
        extra = [dict(row) for fd, row in sorted(after.items())
                 if fd not in self.before or self.before[fd]['identity'] != row['identity']]
        for row in extra:
            for event in connections:
                if (row['kind'] == 'socket' and event['socket_fd'] == row['fd']
                        and event.get('fd_identity') == row['identity']):
                    row['owner'] = {'pool': event['pool'], 'client_id': event['client_id'],
                                    'task_id': event['task_id'],
                                    'client_allocation': event['client_allocation']}
                    break
        live_transports = [id(transport) for ref in transports
                           if (transport := ref()) is not None and not transport.is_closing()]
        if evidence_path is not None:
            report = {'node_hash': hashlib.sha256(self.node.encode()).hexdigest()[:16],
                      'before_count': len(self.before), 'after_count': len(after),
                      'extra': extra, 'live_transport_ids': live_transports}
            write_diagnostic(evidence_path, report)
        # fd/transport inventory is diagnostic: session fixtures and event loops
        # can legitimately outlive a node. Ownership and warnings are the gate.
        errors = ownership_errors(self.node)
        if errors:
            raise AssertionError(f'{self.node}: {errors}')


def connection_record(client, task, socket_fd, name):
    """An identity-only link from a TCP socket to the request's client/task."""
    return {'client_id': id(client), 'task_id': id(task), 'socket_fd': socket_fd,
            'pool': name, 'client_allocation': _allocation_frames(client),
            'fd_identity': describe_fd(socket_fd)['identity'] if socket_fd is not None else None}


def _client_pool_name(client):
    if any(value is client for value in pool._shared_http_clients.values()):
        return 'vm'
    if any(value is client for value in host_resolver._shared_clients_by_loop.values()):
        return 'resolver'
    return 'other'


def install_connection_hooks():
    global _hooks_installed
    if _hooks_installed:
        return
    original_send = httpx.AsyncClient.send
    original_init = httpx.AsyncClient.__init__
    original_connect = anyio.connect_tcp

    def traced_init(client, *args, **kwargs):
        original_init(client, *args, **kwargs)
        _created_clients.add(client)
        _client_meta[client] = (_active_node.get(), _fixture_scope.get())

    httpx.AsyncClient.__init__ = traced_init

    async def traced_send(client, *args, **kwargs):
        token = _active_client.set(client)
        task = asyncio.current_task()
        if task is not None:
            _client_tasks.setdefault(client, weakref.WeakSet()).add(task)
        try:
            return await original_send(client, *args, **kwargs)
        finally:
            _active_client.reset(token)

    async def traced_connect(*args, **kwargs):
        stream = await original_connect(*args, **kwargs)
        client, events = _active_client.get(), _node_connections.get()
        if client is not None and events is not None:
            raw_socket = getattr(stream, '_raw_socket', None)
            fd = raw_socket.fileno() if raw_socket is not None else None
            events.append(connection_record(client, asyncio.current_task(), fd,
                                            _client_pool_name(client)))
            transport = getattr(stream, '_transport', None)
            refs = _node_transports.get()
            if transport is not None and refs is not None:
                refs.append(weakref.ref(transport))
        return stream

    httpx.AsyncClient.send = traced_send
    anyio.connect_tcp = traced_connect
    _hooks_installed = True


def _allocation_frames(obj):
    trace = tracemalloc.get_object_traceback(obj) if tracemalloc.is_tracing() else None
    return ([{"file": Path(frame.filename).name, "line": frame.lineno}
             for frame in trace[-12:]] if trace else [])


def safe_pool_snapshot(name, clients):
    """Record only identities, state and source file/line; never repr or URL."""
    rows = []
    for loop, client in list(clients.items()):
        rows.append({
            "loop_id": id(loop),
            "loop_type": type(loop).__name__,
            "loop_closed": loop.is_closed(),
            "client_id": id(client),
            "client_closed": bool(client.is_closed),
            "client_allocation": _allocation_frames(client),
        })
    return {"pool": name, "clients": rows}


def write_diagnostic(path, evidence):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(evidence, stream, sort_keys=True)
        stream.write("\n")


def _snapshot():
    return [safe_pool_snapshot("vm", pool._shared_http_clients),
            safe_pool_snapshot("resolver", host_resolver._shared_clients_by_loop)]


def start_session_diagnostics():
    """Start before pytest executes the first real node, including its setup."""
    if os.environ.get("REAL_JUNIT_DIR") and not tracemalloc.is_tracing():
        tracemalloc.start(25)
    if os.environ.get("REAL_JUNIT_DIR"):
        assert_warning_policy()
        install_connection_hooks()


@pytest.fixture(autouse=True)
def transport_diagnostic(request):
    """Record technical pool ownership for every real node."""
    if not os.environ.get("REAL_JUNIT_DIR"):
        yield
        return
    start_session_diagnostics()
    connections = []
    transports = []
    request.node._transport_connections = connections
    request.node._transport_refs = transports
    token = _node_connections.set(connections)
    transport_token = _node_transports.set(transports)
    before = _snapshot()
    try:
        yield
    finally:
        _node_connections.reset(token)
        _node_transports.reset(transport_token)
        directory = os.environ.get("REAL_JUNIT_DIR")
        if directory:
            path = Path(directory) / f"transport-{request.node.name}.json"
            write_diagnostic(path, {"schema_version": 1, "node": request.node.nodeid,
                                    "tracing": tracemalloc.is_tracing(),
                                    "before": before, "after": _snapshot(),
                                    "connections": connections})
