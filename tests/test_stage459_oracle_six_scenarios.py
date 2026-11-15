"""Deterministic nested pytest proof for object ownership and warnings."""

import os
from pathlib import Path
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
import json
from types import SimpleNamespace

from scripts import run_opt_in_real_test_suite as real_runner


def test_real_runner_passes_tracemalloc_and_warning_errors(monkeypatch):
    monkeypatch.setattr(real_runner.os, 'environ', {})
    seen = []

    def fake_run(command, *, env, check):
        seen.append((command, env.copy()))
        Path(env['PYTEST_REAL_OUTCOME_FILE']).write_text(json.dumps({
            'collected': 1, 'counts': {'passed': 1, 'failed': 0,
                                      'skipped-not-configured': 0, 'skipped-error': 0},
            'not_configured': [], 'skip_errors': [],
        }))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(real_runner.subprocess, 'run', fake_run)
    assert real_runner.main() == 0
    assert len(seen) == 2
    assert all(entry[1].get('PYTHONTRACEMALLOC') == '5' for entry in seen)
    assert all(entry[0][1:3] == ['-W', 'error'] for entry in seen)


def test_six_resource_scenarios_in_one_nested_suite(tmp_path):
    (tmp_path / 'conftest.py').write_text('''
import os
from tests.conftest import (pytest_sessionstart, pytest_runtest_setup,
    pytest_runtest_teardown, pytest_fixture_setup, pytest_sessionfinish,
    pytest_unconfigure)
from tests.transport_diagnostics import transport_diagnostic
''')
    (tmp_path / 'test_six.py').write_text('''
import asyncio
import gc
import socket
import httpx
import pytest
from vm_transport import pool

gc.disable()
RAW = []
LOST = []
LOOPS = []

@pytest.fixture(scope="session")
def held_pool():
    loop = asyncio.new_event_loop()
    LOOPS.append(loop)
    client = httpx.AsyncClient()
    pool._shared_http_clients[loop] = client
    yield client
    loop.run_until_complete(client.aclose())
    pool._shared_http_clients.pop(loop, None)
    loop.close()

@pytest.fixture(scope="session")
def lazy_session_client():
    client = httpx.AsyncClient()
    yield client
    asyncio.run(client.aclose())

def test_01_raw_client_unclosed():
    RAW.append(httpx.AsyncClient())

def test_02_after_raw():
    asyncio.run(RAW.pop().aclose())

def test_03_bare_socket_unclosed():
    sock = socket.socket()
    cycle = [sock]
    cycle.append(cycle)

def test_04_after_socket():
    assert True

def test_05_reset_clears_before_close():
    loop = asyncio.new_event_loop()
    LOOPS.append(loop)
    client = httpx.AsyncClient()
    pool._shared_http_clients[loop] = client
    pool._shared_http_clients.clear()  # deliberate broken reset mutation
    LOST.append((loop, client))

def test_06_after_bad_reset():
    loop, client = LOST.pop()
    loop.run_until_complete(client.aclose())
    loop.close()

def test_07_held_pool(held_pool):
    assert not held_pool.is_closed

def test_08_lazy_session(lazy_session_client):
    assert not lazy_session_client.is_closed

@pytest.mark.parametrize("number", [1, 2])
def test_09_fresh_loop_per_test(number):
    loop = asyncio.new_event_loop()
    async def use_and_close():
        client = await pool.get_shared_http_client()
        await pool.reset_shared_http_client()
        assert client.is_closed
    loop.run_until_complete(use_and_close())
    loop.close()
''')
    junit = tmp_path / 'nested.xml'
    env = os.environ.copy()
    env['REAL_JUNIT_DIR'] = str(tmp_path)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    env['PYTHONTRACEMALLOC'] = '5'
    command = [sys.executable, '-m', 'pytest', '-q']
    if env.get('STAGE459_MUTATE_WARNING_FLAGS') != '1':
        command += ['-W', 'error']
    command += [f'--junitxml={junit}', str(tmp_path / 'test_six.py')]
    result = subprocess.run(command, env=env, text=True, capture_output=True,
                            timeout=180, check=False)
    assert junit.exists(), result.stdout[-800:]
    cases = {case.attrib['name']: case for case in ET.parse(junit).iter('testcase')}
    red = {'test_01_raw_client_unclosed', 'test_03_bare_socket_unclosed',
           'test_05_reset_clears_before_close'}
    assert len(cases) == 10, list(cases)
    actual_red = {name for name, case in cases.items()
                  if case.find('failure') is not None or case.find('error') is not None}
    assert actual_red == red, (actual_red, result.stdout[-800:])
    for name in ('test_01_raw_client_unclosed', 'test_05_reset_clears_before_close'):
        case = cases[name]
        detail = ' '.join((element.text or '') for element in case if element.tag in ('error', 'failure'))
        assert 'open AsyncClient' in detail, (name, detail[-500:])
    socket_case = cases['test_03_bare_socket_unclosed']
    socket_detail = ' '.join((element.text or '') for element in socket_case if element.tag in ('error', 'failure'))
    assert 'ResourceWarning' in socket_detail
    assert result.returncode == 1
    for file in tmp_path.glob('resource-*.json'):
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
        raw = file.read_text()
        assert all(marker not in raw for marker in ('https://', 'Authorization',
                    'CLIENT_RESPONSE_BODY', 'SECRET_TOKEN', 'laddr', 'raddr'))
