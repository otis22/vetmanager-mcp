"""Private test-only milestones around stage385 child startup."""

import json
import os
from pathlib import Path
import socket
import threading
import time


PHASES = {"process_start", "before_import", "after_import", "server_init",
          "redis_start", "redis_done", "redis_error", "db_start", "db_done",
          "db_error", "pre_bind", "post_bind", "server_error"}
LABELS = {"stage385-export", "stage385-metrics"}


def classify_phase(events, *, ready=False):
    phases = set(events)
    if ready and "post_bind" in phases:
        return "ready"
    if "server_error" in phases:
        return "server_error"
    if "post_bind" in phases:
        return "post_bind_not_ready"
    if "pre_bind" in phases and ("db_done" in phases or "redis_done" in phases):
        return "pre_bind"
    if "after_import" in phases:
        return "pre_dependency"
    if "before_import" in phases:
        return "import"
    if "process_start" in phases:
        return "process_start"
    return "unknown"


def record_phase(path, label, slot_index, phase, elapsed):
    if label not in LABELS or type(slot_index) is not int or slot_index not in (0, 1, 2):
        raise ValueError("Invalid phase identity")
    if phase not in PHASES or type(elapsed) not in (float, int) or not 0 <= elapsed <= 3600:
        raise ValueError("Invalid phase event")
    path = Path(path)
    events = json.loads(path.read_text())["events"] if path.exists() else []
    events.append({"phase": phase, "elapsed_ms": round(elapsed * 1000)})
    data = {"schema_version": 1, "label": label, "slot_index": slot_index,
            "events": events}
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, sort_keys=True)
    os.replace(temp, path)


def run():
    if not os.environ.get("REAL_JUNIT_DIR"):
        import server
        server._run_http_server(stateless_http=False, transport="streamable-http",
                                host="127.0.0.1", port=int(os.environ["PORT"]), path="/mcp")
        return
    label = os.environ["STAGE385_PHASE_LABEL"]
    index = int(os.environ["STAGE385_SLOT_INDEX"])
    evidence = Path(os.environ["REAL_JUNIT_DIR"]) / f"phase-{label}-{index}.json"
    started = time.monotonic()
    lock = threading.Lock()

    def mark(phase):
        with lock:
            record_phase(evidence, label, index, phase, time.monotonic() - started)

    mark("process_start")
    mark("before_import")
    import server
    mark("after_import")

    def wrap(owner, name, prefix):
        original = getattr(owner, name)

        async def observed(*args, **kwargs):
            mark(prefix + "_start")
            try:
                result = await original(*args, **kwargs)
            except BaseException:
                mark(prefix + "_error")
                raise
            mark(prefix + "_done")
            return result

        setattr(owner, name, observed)

    wrap(server.shared_metric_counters, "verify_shared_metrics_startup", "redis")
    wrap(server, "initialize_storage", "db")
    wrap(server, "bootstrap_storage_schema", "db")
    wrap(server.REQUEST_CACHE, "refresh_shared_gauge", "redis")
    port = int(os.environ["PORT"])

    def watch_listener():
        for _ in range(100):
            with socket.socket() as sock:
                sock.settimeout(.05)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    mark("post_bind")
                    return
            time.sleep(.1)

    mark("server_init")
    threading.Thread(target=watch_listener, daemon=True).start()
    mark("pre_bind")
    try:
        server._run_http_server(stateless_http=False, transport="streamable-http",
                                host="127.0.0.1", port=port, path="/mcp")
    except BaseException:
        mark("server_error")
        raise
