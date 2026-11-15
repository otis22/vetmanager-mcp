"""Every test-launched MCP server must strip pytest-only allocation tracing."""

import ast
from pathlib import Path

from tests.child_process_env import make_test_server_env


ROOT = Path(__file__).parent
SERVER_MARKERS = ("_run_http_server", "tests.stage385_child_phase",
                  "tests.stage385_pg_hook_server")


def _call_name(node):
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _contains_server_marker(node):
    return any(isinstance(item, ast.Constant) and isinstance(item.value, str)
               and any(marker in item.value for marker in SERVER_MARKERS)
               for item in ast.walk(node))


def _server_calls(tree):
    file_has_server_entry = _contains_server_marker(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name == "Popen" and file_has_server_entry:
            yield node
        elif name in {"run", "create_subprocess_exec", "create_subprocess_shell"}:
            if _contains_server_marker(node):
                yield node
        elif name == "Process" and any(
            _contains_server_marker(item) or isinstance(item, ast.Name) and item.id == "_run_http_server"
            for item in [*node.args, *(item.value for item in node.keywords if item.arg == "target")]
        ):
            yield node


def _safe_names(tree):
    safe = set()
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
    for _ in range(len(assignments) + 1):
        old = safe.copy()
        for node in assignments:
            value = node.value
            direct = isinstance(value, ast.Call) and _call_name(value.func) == "make_test_server_env"
            merged = isinstance(value, ast.Dict) and None in value.keys and all(
                key is not None or isinstance(item, ast.Name) and item.id in safe
                for key, item in zip(value.keys, value.values))
            for target in node.targets:
                if isinstance(target, ast.Name) and (direct or merged):
                    same_name = [other for other in assignments
                                 if any(isinstance(item, ast.Name) and item.id == target.id
                                        for item in other.targets)]
                    if len(same_name) == 1:
                        safe.add(target.id)
        if safe == old:
            break
    return safe


def _safe_env(value, names):
    if isinstance(value, ast.Name):
        return value.id in names
    if isinstance(value, ast.Call):
        if _call_name(value.func) == "make_test_server_env":
            return True
        return (isinstance(value.func, ast.Attribute) and value.func.attr == "copy"
                and isinstance(value.func.value, ast.Name) and value.func.value.id in names)
    return False


def unprotected_server_children(source):
    tree = ast.parse(source)
    names = _safe_names(tree)
    failures = []
    for call in _server_calls(tree):
        env = next((item.value for item in call.keywords if item.arg == "env"), None)
        containing = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and node.lineno <= call.lineno <= node.end_lineno]
        function = max(containing, key=lambda node: node.lineno) if containing else None
        parameters = {arg.arg for arg in function.args.args} if function else set()
        if env is None or (isinstance(env, ast.Name) and env.id in parameters) or not _safe_env(env, names):
            failures.append(call.lineno)
    return failures


def test_server_child_inventory_is_complete():
    files = {}
    for path in ROOT.glob("test_*.py"):
        source = path.read_text()
        tree = ast.parse(source)
        if list(_server_calls(tree)):
            files[path.name] = unprotected_server_children(source)
    assert len(files) >= 12
    assert not {name: lines for name, lines in files.items() if lines}


def test_new_unsanitized_server_child_is_rejected():
    source = "import subprocess\nsubprocess.Popen(['python', '-c', 'from server import _run_http_server'], env={})\n"
    assert unprotected_server_children(source) == [2]


def test_second_unsanitized_child_in_existing_server_file_is_rejected():
    source = ("import os, subprocess\n"
              "env = make_test_server_env()\n"
              "subprocess.Popen(['python', '-c', '_run_http_server'], env=env)\n"
              "other = os.environ.copy()\n"
              "subprocess.Popen(['python', '-c', '_run_http_server'], env=other)\n")
    assert unprotected_server_children(source) == [5]


def test_async_and_multiprocessing_server_launchers_are_rejected():
    source = ("import asyncio, multiprocessing\n"
              "asyncio.create_subprocess_exec('python', '-c', '_run_http_server')\n"
              "multiprocessing.Process(target=_run_http_server)\n")
    assert unprotected_server_children(source) == [2, 3]


def test_parent_and_child_warning_contract_remains():
    parent = (ROOT.parent / "scripts/run_opt_in_real_test_suite.py").read_text()
    assert 'env.setdefault("PYTHONTRACEMALLOC", "5")' in parent
    assert 'for item in ("-W", flag)' in parent
    source = {"PYTHONTRACEMALLOC": "5", "PYTHONWARNINGS": "error", "OTHER": "same"}
    assert make_test_server_env(source) == {"PYTHONWARNINGS": "error", "OTHER": "same"}
    assert source["PYTHONTRACEMALLOC"] == "5"


def test_production_files_do_not_use_test_env_helper():
    for name in ("Dockerfile", "docker-compose.yml", "docker-compose.test.yml", "server.py"):
        assert "make_test_server_env" not in (ROOT.parent / name).read_text()
