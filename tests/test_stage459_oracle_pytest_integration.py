"""The oracle attributes an unraisable finalizer to its creating node."""

import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import json


def test_finalizer_warning_fails_current_node_not_next(tmp_path):
    (tmp_path / 'conftest.py').write_text('''
import os
from tests.conftest import (pytest_runtest_teardown, pytest_sessionstart,
                            _reset_vm_client_state, _reset_billing_resolver_state,
                            pytest_runtest_setup)
from tests.transport_diagnostics import transport_diagnostic
if os.environ.get("STAGE459_MUTATE_ORACLE_GC") == "1":
    from tests.transport_diagnostics import ResourceOracle
    ResourceOracle.finish = lambda self, *args, **kwargs: None
''')
    (tmp_path / 'test_probe.py').write_text('''
import gc
import warnings

gc.disable()
class Leaky:
    def __del__(self):
        warnings.warn("synthetic finalizer", ResourceWarning)

def test_first_node():
    value = Leaky()
    value.cycle = value

def test_second_node():
    assert True
''')
    junit = tmp_path / 'out.xml'
    env = os.environ.copy()
    env['REAL_JUNIT_DIR'] = str(tmp_path)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-W', 'error',
                             f'--junitxml={junit}', str(tmp_path / 'test_probe.py')],
                            env=env, text=True, capture_output=True, timeout=30, check=False)
    assert result.returncode == 1
    cases = {case.attrib['name']: case for case in ET.parse(junit).iter('testcase')}
    states = {name: [tag for tag in ('error', 'failure', 'skipped') if case.find(tag) is not None]
              for name, case in cases.items()}
    assert cases['test_first_node'].find('error') is not None or cases['test_first_node'].find('failure') is not None, states
    assert cases['test_second_node'].find('error') is None
    assert cases['test_second_node'].find('failure') is None


def test_pool_resets_finish_before_oracle(tmp_path):
    (tmp_path / 'conftest.py').write_text('''
import json
import os
import pytest
from tests.conftest import (pytest_runtest_setup, pytest_runtest_teardown,
                            _reset_vm_client_state, _reset_billing_resolver_state)
from tests.transport_diagnostics import ResourceOracle, transport_diagnostic
events = []
original_finish = ResourceOracle.finish
def traced_finish(self, *args, **kwargs):
    events.append("oracle")
    return original_finish(self, *args, **kwargs)
ResourceOracle.finish = traced_finish
def pytest_sessionstart(session):
    from tests.conftest import pytest_sessionstart as start
    start(session)
    import host_resolver, vetmanager_client
    vm_reset, resolver_reset = vetmanager_client.reset_shared_http_client, host_resolver.reset_billing_resolver
    async def vm():
        events.append("vm-reset")
        await vm_reset()
    async def resolver():
        events.append("resolver-reset")
        await resolver_reset()
    vetmanager_client.reset_shared_http_client = vm
    host_resolver.reset_billing_resolver = resolver
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    yield
    if os.environ.get("STAGE459_MUTATE_ORACLE_BEFORE_RESET") == "1":
        item._resource_oracle.finish(getattr(item, "_transport_connections", []))
def pytest_sessionfinish(session):
    with open(os.path.join(os.environ["REAL_JUNIT_DIR"], "order.json"), "w") as out:
        json.dump(events, out)
''')
    (tmp_path / 'test_pool.py').write_text('''
import asyncio
import socket
import pytest
import host_resolver
from vm_transport import pool
LOOPS = []
class Client:
    is_closed = False
    def __init__(self):
        self.left, self.right = socket.socketpair()
    async def aclose(self):
        self.left.close(); self.right.close()
        self.is_closed = True
@pytest.mark.asyncio
async def test_live_pooled_clients():
    loop = asyncio.get_running_loop()
    LOOPS.append(loop)
    pool._shared_http_clients[loop] = Client()
    host_resolver._shared_clients_by_loop[loop] = Client()
''')
    env = os.environ.copy()
    env['REAL_JUNIT_DIR'] = str(tmp_path)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-W', 'error',
                             str(tmp_path / 'test_pool.py')], env=env, text=True,
                            capture_output=True, timeout=30, check=False)
    order = json.loads((tmp_path / 'order.json').read_text())
    assert result.returncode == 0, (order, result.stdout[-1000:])
    assert order[-1] == 'oracle'
    assert order.count('vm-reset') >= 2 and order.count('resolver-reset') >= 2
