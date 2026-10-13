"""Atomic write admission state shared by the signal handler and HTTP requests."""

from threading import Condition, Thread


_condition = Condition()
_draining = False
_in_flight_writes = 0


def begin_draining() -> None:
    global _draining
    with _condition:
        _draining = True
        _condition.notify_all()


def request_drain_from_signal() -> Thread:
    """Apply the fence after any interrupted admission section releases its lock."""
    worker = Thread(target=begin_draining, name="mcp-write-drain", daemon=True)
    worker.start()
    return worker


def is_draining() -> bool:
    with _condition:
        return _draining


def admit_write() -> bool:
    """Fence check and in-flight increment are one indivisible operation."""
    global _in_flight_writes
    with _condition:
        if _draining:
            return False
        _in_flight_writes += 1
        return True


def finish_write() -> None:
    global _in_flight_writes
    with _condition:
        if _in_flight_writes <= 0:
            raise RuntimeError("write admission counter underflow")
        _in_flight_writes -= 1
        _condition.notify_all()


def in_flight_writes() -> int:
    with _condition:
        return _in_flight_writes


def wait_for_writes(timeout: float) -> bool:
    with _condition:
        return _condition.wait_for(lambda: _in_flight_writes == 0, timeout=timeout)


def reset_draining() -> None:
    global _draining, _in_flight_writes
    with _condition:
        _draining = False
        _in_flight_writes = 0
        _condition.notify_all()
