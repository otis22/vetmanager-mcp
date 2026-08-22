"""Process-local shutdown state shared by signal and HTTP handlers."""

_draining = False


def begin_draining() -> None:
    global _draining
    _draining = True


def is_draining() -> bool:
    return _draining


def reset_draining() -> None:
    global _draining
    _draining = False
