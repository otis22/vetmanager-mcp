"""Safe technical readiness observations for isolated stage385 test slots."""

import json
import os
from pathlib import Path
import socket
import time
from collections import Counter

import httpx


STATES = {"ready", "child_exited", "port_conflict", "http_timeout", "http_non_200", "unprobed",
          "connect_error", "transport_error", "unknown"}
DEPENDENCIES = {"redis_unavailable", "db_unavailable", "unknown"}
STDERR_CLASSES = {"port_conflict", "redis_unavailable", "db_unavailable", "import_error",
                  "other", "empty"}


def _stderr_class(stderr):
    text = (stderr or "")[-16384:].lower()
    if not text:
        return "empty"
    if "address already in use" in text or "errno 98" in text:
        return "port_conflict"
    if "redis" in text and any(word in text for word in ("refused", "unavailable", "timeout", "error")):
        return "redis_unavailable"
    if any(word in text for word in ("operationalerror", "database is locked", "storage_readiness_failed")):
        return "db_unavailable"
    if "importerror" in text or "modulenotfounderror" in text:
        return "import_error"
    return "other"


def classify_readiness(*, exit_code=None, http_status=None, error=None,
                       listener=None, stderr=None, reason=None):
    """Return fixed classes only; never copy exception, URL, body or stderr."""
    stderr_class = _stderr_class(stderr)
    if exit_code is not None:
        state = "port_conflict" if stderr_class == "port_conflict" else "child_exited"
    elif http_status == 200:
        state = "ready"
    elif http_status is not None:
        state = "http_non_200"
    elif isinstance(error, httpx.TimeoutException):
        state = "http_timeout"
    elif isinstance(error, httpx.ConnectError):
        state = "connect_error"
    elif isinstance(error, httpx.TransportError):
        state = "transport_error"
    else:
        state = "unknown"
    status_class = f"{http_status // 100}xx" if isinstance(http_status, int) and 200 <= http_status < 600 else "none"
    if status_class not in {"2xx", "3xx", "4xx", "5xx", "none"}:
        status_class = "other"
    dependency = ("redis_unavailable" if stderr_class == "redis_unavailable" else
                  "db_unavailable" if stderr_class == "db_unavailable" or reason == "storage_unavailable" else
                  "unknown")
    return {"state": state, "status_class": status_class,
            "dependency_class": dependency,
            "exit_class": "none" if exit_code is None else "zero" if exit_code == 0 else "nonzero",
            "listener": listener if isinstance(listener, bool) else None,
            "stderr_class": stderr_class}


def write_readiness_evidence(path, *, label, observations):
    """Write once with mode 0600 and reject fields that could hold raw data."""
    if label not in {"stage385-export", "stage385-metrics"}:
        raise ValueError("Unknown readiness label")
    allowed = {"state", "status_class", "dependency_class", "exit_class", "listener",
               "stderr_class", "slot_index", "attempts", "class_counts"}
    for item in observations:
        if set(item) - allowed or item.get("state") not in STATES:
            raise ValueError("Unsafe readiness evidence")
        if item.get("dependency_class") not in DEPENDENCIES or item.get("stderr_class") not in STDERR_CLASSES:
            raise ValueError("Unsafe readiness evidence")
        if item.get("status_class") not in {"2xx", "3xx", "4xx", "5xx", "other", "none"}:
            raise ValueError("Unsafe readiness evidence")
        if item.get("exit_class") not in {"none", "zero", "nonzero"}:
            raise ValueError("Unsafe readiness evidence")
        if item.get("listener") not in {None, True, False}:
            raise ValueError("Unsafe readiness evidence")
        if "slot_index" in item and (type(item["slot_index"]) is not int or item["slot_index"] < 0):
            raise ValueError("Unsafe readiness evidence")
        if "attempts" in item and (type(item["attempts"]) is not int or not 0 <= item["attempts"] <= 100):
            raise ValueError("Unsafe readiness evidence")
        if "class_counts" in item and (not isinstance(item["class_counts"], dict) or
                                       any(key not in STATES or type(value) is not int or not 0 <= value <= 100
                                           for key, value in item["class_counts"].items())):
            raise ValueError("Unsafe readiness evidence")
    data = json.dumps({"schema_version": 1, "label": label, "observations": observations}, sort_keys=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(data)


def _listener_open(port):
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _reason_class(response):
    try:
        reason = response.json().get("checks", {}).get("storage", {}).get("reason")
    except (ValueError, AttributeError, TypeError):
        return "unknown"
    return reason if reason in {"ok", "storage_unavailable", "storage_check_timeout", "shutting_down"} else "unknown"


class Stage385ReadinessTrace:
    """Observe the original 100 attempts without extending their budget."""

    def __init__(self, label):
        self.label = label
        self.observations = []

    def wait_for_slot(self, client, process, port, index):
        last = classify_readiness()
        counts = Counter()
        for attempt in range(1, 101):
            code = process.poll()
            if code is not None:
                last = classify_readiness(exit_code=code, listener=_listener_open(port))
                counts[last["state"]] += 1
                self.observations.append({**last, "slot_index": index, "attempts": attempt,
                                          "class_counts": dict(counts)})
                raise AssertionError("MCP slot exited before readiness")
            try:
                response = client.get("/readyz")
                last = classify_readiness(http_status=response.status_code, reason=_reason_class(response),
                                          listener=True)
            except httpx.TransportError as exc:
                last = classify_readiness(error=exc)
            counts[last["state"]] += 1
            if last["state"] == "ready":
                self.observations.append({**last, "slot_index": index, "attempts": attempt,
                                          "class_counts": dict(counts)})
                return
            time.sleep(.1)
        if last["listener"] is None:
            last["listener"] = _listener_open(port)
        self.observations.append({**last, "slot_index": index, "attempts": 100,
                                  "class_counts": dict(counts)})
        raise AssertionError("MCP slot did not become ready")

    def wait_for_slots(self, clients, processes, ports):
        for index, (client, process, port) in enumerate(zip(clients, processes, ports)):
            self.wait_for_slot(client, process, port, index)

    def capture_unprobed(self, processes, ports):
        observed = {record["slot_index"] for record in self.observations}
        for index, (process, port) in enumerate(zip(processes, ports)):
            if index in observed:
                continue
            code = process.poll()
            record = classify_readiness(exit_code=code, listener=_listener_open(port))
            if code is None:
                record["state"] = "unprobed"
            self.observations.append({**record, "slot_index": index, "attempts": 0,
                                      "class_counts": {}})

    def finish(self, stderr_logs):
        for index, record in enumerate(self.observations):
            classified = _stderr_class(stderr_logs[index] if index < len(stderr_logs) else None)
            record["stderr_class"] = classified
            if classified in {"redis_unavailable", "db_unavailable"}:
                record["dependency_class"] = classified
            if classified == "port_conflict":
                record["state"] = "port_conflict"
        evidence_dir = os.environ.get("REAL_JUNIT_DIR")
        if evidence_dir:
            write_readiness_evidence(Path(evidence_dir) / f"readiness-{self.label}.json",
                                     label=self.label, observations=self.observations)
