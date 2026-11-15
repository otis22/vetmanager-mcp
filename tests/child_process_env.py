"""Environment for test-launched MCP server children."""

import os


def make_test_server_env(source=None):
    env = dict(os.environ if source is None else source)
    env.pop("PYTHONTRACEMALLOC", None)
    return env


def start_test_db_worker(process):
    missing = object()
    original = os.environ.pop("PYTHONTRACEMALLOC", missing)
    try:
        process.start()
    finally:
        if original is missing:
            os.environ.pop("PYTHONTRACEMALLOC", None)
        else:
            os.environ["PYTHONTRACEMALLOC"] = original
