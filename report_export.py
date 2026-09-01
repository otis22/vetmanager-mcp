"""Report export files: the link, the cleaning, the disk, the retention.

Stage 276. A live probe on 01.09.2026 showed what the Vetmanager export
locator actually is: an absolute address on a public CDN that serves the file
to anyone, with no authorization header at all. So the server downloads the
export itself, cleans it with the same layers report rows get, and hands out a
link of its own.

The link is the key to the file. It is unguessable only because it is an HMAC
on a server secret: a plain hash of the clinic domain and a small integer token
id would be brute-forced in seconds.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
import unicodedata

from depersonalization import sanitize_report_cell
from web_auth import get_web_session_secret


REPORT_EXPORT_ROUTE_PREFIX = "/report-export"
REPORT_EXPORT_TTL_SECONDS = 3 * 24 * 60 * 60
REPORT_EXPORT_MAX_BYTES = 25 * 1024 * 1024
REPORT_EXPORT_CONTENT_TYPE = "text/csv; charset=utf-8"
# What the CDN is allowed to answer with. An HTML error page parsed as CSV
# would be stored and served as if it were a report — and a body with no type
# at all is exactly that case with the label torn off, so it is refused too.
REPORT_EXPORT_ALLOWED_CONTENT_TYPES = frozenset({
    "text/csv",
    "text/plain",
    "application/csv",
    "application/octet-stream",
})

_SEGMENT_RE = re.compile(r"^[0-9a-f]{32}$")
# Excel executes a cell that starts with one of these. A number is the one
# exception: without it every negative sum in the report would grow a quote.
_FORMULA_LEAD = ("=", "+", "@", "-")
_SAFE_NUMBER_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")

_LINK_KEY: bytes | None = None


class ReportExportError(Exception):
    """A failure whose message is safe to show the agent."""


@dataclass(frozen=True)
class StoredExport:
    path: Path
    subject_type: str
    subject_id: int
    download_name: str
    created_at: float

    @property
    def expires_at(self) -> float:
        return self.created_at + REPORT_EXPORT_TTL_SECONDS


# ── The link ─────────────────────────────────────────────────────────────────


def reset_link_key_cache() -> None:
    """Drop the derived link key; tests and secret rotation need this."""
    global _LINK_KEY
    _LINK_KEY = None


def _link_key() -> bytes:
    global _LINK_KEY
    if _LINK_KEY is None:
        try:
            secret = get_web_session_secret()
        except RuntimeError as exc:
            raise ReportExportError(
                "Report export links are not configured on this server."
            ) from exc
        _LINK_KEY = hmac.new(
            secret.encode("utf-8"), b"report-export-link-v1", hashlib.sha256
        ).digest()
    return _LINK_KEY


def _canonical(*parts: str) -> bytes:
    """Length-prefixed join, so no two different inputs share a preimage.

    `"a:b" + "c"` and `"a" + "b:c"` are the same string after a naive join with
    a separator, and would sign the same bytes.
    """
    encoded = [part.encode("utf-8") for part in parts]
    return b"v1" + b"".join(b"|%d|" % len(item) + item for item in encoded)


def _segment(*parts: str) -> str:
    return hmac.new(_link_key(), _canonical(*parts), hashlib.sha256).hexdigest()[:32]


def owner_segment(*, domain: str, subject_type: str, subject_id: int | str) -> str:
    """Directory segment for one access of one clinic."""
    return _segment("owner", domain, subject_type, str(subject_id))


def file_segment(owner: str, filename: str) -> str:
    """File segment; this is also the name on disk."""
    return _segment("file", owner, filename)


def new_export_filename(*, report_file_id: int) -> str:
    """A fresh name per export, so a repeat does not overwrite a live link."""
    return f"{report_file_id}-{secrets.token_hex(16)}"


# ── The file ─────────────────────────────────────────────────────────────────


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ReportExportError("The export file is in an encoding MCP cannot read.")


def _leading_noise(cell: str) -> int:
    """How many leading characters Excel will look past before the formula.

    Whitespace is the obvious case, but any control or format character does
    the same job of hiding the `=` from a naive check while Excel still
    executes what follows.
    """
    index = 0
    for index, char in enumerate(cell):
        if not (char.isspace() or unicodedata.category(char) in {"Cc", "Cf"}):
            return index
    return index + 1


def _escape_formula(cell: str) -> str:
    stripped = cell[_leading_noise(cell):]
    if not stripped:
        return cell
    if _SAFE_NUMBER_RE.match(cell.strip()):
        return cell
    if stripped[0] in _FORMULA_LEAD:
        return "'" + cell
    return cell


def build_export_csv(
    raw: bytes, *, delimiter: str, depersonalize: bool
) -> tuple[str, int, int]:
    """Return cleaned CSV text plus its row and column counts.

    Cleaning is the same two layers report rows get: the column name decides
    first, and whatever the column is called, the value is cleaned too.
    """
    rows = list(csv.reader(io.StringIO(_decode(raw), newline=""), delimiter=delimiter))
    rows = [row for row in rows if row != []]
    if not rows:
        raise ReportExportError("The export file is empty.")

    header = rows[0]
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([_escape_formula(cell) for cell in header])
    for row in rows[1:]:
        cleaned = []
        for index, cell in enumerate(row):
            column = header[index] if index < len(header) else ""
            value = sanitize_report_cell(column, cell) if depersonalize else cell
            cleaned.append(_escape_formula(value))
        writer.writerow(cleaned)

    return "﻿" + buffer.getvalue(), len(rows) - 1, len(header)


# ── The disk ─────────────────────────────────────────────────────────────────


def get_export_root() -> Path:
    configured = (os.environ.get("REPORT_EXPORT_DIR") or "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "data" / "report-exports"


def _write_private(path: Path, data: bytes) -> None:
    """Write through a temporary name so a reader never sees a half file."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        # The sweep removes a directory once it is empty, so a parallel export
        # can find its own directory gone between mkdir and the first write.
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def store_export(
    *,
    csv_text: str,
    owner: str,
    filename: str,
    subject_type: str,
    subject_id: int,
    download_name: str,
) -> str:
    """Store one cleaned export and return the path its link points at."""
    name = file_segment(owner, filename)
    directory = get_export_root() / owner
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)

    csv_path = directory / f"{name}.csv"
    meta_path = directory / f"{name}.json"
    meta = {
        "v": 1,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "owner": owner,
        "download_name": download_name,
    }
    # The companion goes first: a finished CSV without one does not exist.
    _write_private(meta_path, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    try:
        _write_private(csv_path, csv_text.encode("utf-8"))
    except Exception:
        meta_path.unlink(missing_ok=True)
        raise
    return f"{REPORT_EXPORT_ROUTE_PREFIX}/{owner}/{name}.csv"


def _safe_download_name(value: object) -> str:
    """A file name fit for a header, whatever the companion happens to hold."""
    text = value if isinstance(value, str) else ""
    cleaned = "".join(char for char in text if char.isalnum() or char in "._-")
    return cleaned[:64] or "report.csv"


def _delete_pair(directory: Path, name: str) -> None:
    (directory / f"{name}.csv").unlink(missing_ok=True)
    (directory / f"{name}.json").unlink(missing_ok=True)


def resolve_export(owner: str, name: str) -> StoredExport | None:
    """Return the stored export for a path, or nothing at all.

    Nothing at all covers every refusal on purpose: a wrong path, an expired
    file and a broken companion must be indistinguishable from outside.
    """
    if not _SEGMENT_RE.match(owner or "") or not _SEGMENT_RE.match(name or ""):
        return None
    directory = get_export_root() / owner
    csv_path = directory / f"{name}.csv"
    if not csv_path.is_file():
        return None

    created_at = csv_path.stat().st_mtime
    if time.time() - created_at > REPORT_EXPORT_TTL_SECONDS:
        _delete_pair(directory, name)
        return None

    try:
        meta = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        subject_type = str(meta["subject_type"])
        subject_id = int(meta["subject_id"])
        stored_owner = str(meta["owner"])
        download_name = _safe_download_name(meta.get("download_name"))
    except (OSError, ValueError, KeyError, TypeError):
        _delete_pair(directory, name)
        return None
    if not hmac.compare_digest(stored_owner, owner):
        _delete_pair(directory, name)
        return None

    return StoredExport(
        path=csv_path,
        subject_type=subject_type,
        subject_id=subject_id,
        download_name=download_name,
        created_at=created_at,
    )


def sweep_expired(*, now: float | None = None) -> int:
    """Delete what outlived its three days. Disk hygiene, not the rule itself.

    The rule is enforced on the way out, in `resolve_export`; this only keeps
    the disk from holding files nobody will ever be given again.
    """
    root = get_export_root()
    if not root.is_dir():
        return 0
    current = now if now is not None else time.time()
    removed = 0
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        for csv_path in directory.glob("*.csv"):
            try:
                if current - csv_path.stat().st_mtime <= REPORT_EXPORT_TTL_SECONDS:
                    continue
            except OSError:
                continue
            _delete_pair(directory, csv_path.stem)
            removed += 1
        try:
            next(directory.iterdir())
        except StopIteration:
            directory.rmdir()
        except OSError:
            pass
    return removed
