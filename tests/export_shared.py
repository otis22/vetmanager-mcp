"""One observable StartReport outcome for the isolated export group."""

from dataclasses import dataclass

import pytest


_START_CODES = ("CONSTRUCTOR_BUSY", "RUN_RATE_LIMITED")


@dataclass(frozen=True)
class ExportStartOutcome:
    file_id: int | None
    error_code: str | None = None

    def require_file_id(self) -> int:
        if self.file_id is None:
            raise AssertionError(f"Shared export start failed: {self.error_code or 'OTHER_ERROR'}")
        return self.file_id


def _safe_code(error: object) -> str:
    message = str(error)
    for code in _START_CODES:
        if code in message:
            return code
    if "tenant-wide REST export guard" in message:
        return "TENANT_GUARD"
    return "OTHER_ERROR"


async def start_one_export(call_tool, report_id: int) -> ExportStartOutcome:
    """Never retry StartReport; preserve only the machine class, not the body."""
    try:
        result = await call_tool("start_report_export", {"report_id": report_id})
    except Exception as exc:
        return ExportStartOutcome(None, _safe_code(exc))
    if getattr(result, "is_error", False):
        return ExportStartOutcome(None, _safe_code(result.structured_content))
    content = getattr(result, "structured_content", None)
    report = (content or {}).get("data", {}).get("report", {})
    value = report.get("report_file_id")
    if isinstance(value, bool) or not (isinstance(value, int) or
                                        isinstance(value, str) and value.isdecimal()):
        return ExportStartOutcome(None, "MISSING_FILE_ID")
    file_id = int(value)
    return ExportStartOutcome(file_id) if file_id > 0 else ExportStartOutcome(None, "MISSING_FILE_ID")


class SharedExportRun:
    """Keep one StartReport outcome across the sequential export nodes."""

    def __init__(self) -> None:
        self._outcome: ExportStartOutcome | None = None

    async def start_once(self, call_tool, report_id: int) -> ExportStartOutcome:
        if self._outcome is None:
            self._outcome = await start_one_export(call_tool, report_id)
        return self._outcome

    def require_file_id(self) -> int:
        if self._outcome is None:
            raise AssertionError("Shared export start was not run by the first export node")
        return self._outcome.require_file_id()


@pytest.fixture(scope="session")
def shared_live_export() -> SharedExportRun:
    """One fixture instance per isolated export group process."""
    return SharedExportRun()
