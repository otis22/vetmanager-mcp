"""Classify bounded historical downtime without inferring through missing samples."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import argparse
import csv
import json
from pathlib import Path


@dataclass(frozen=True)
class Sample:
    timestamp: datetime
    signal: str
    slot: str
    state: str  # ok, fail, missing


@dataclass(frozen=True)
class Incident:
    signal: str
    slot: str
    first_failure: datetime
    last_failure: datetime
    first_recovery: datetime | None
    observed_failure_span_seconds: float
    outer_window_seconds: float | None
    start_confirmed: bool
    recovery_confirmed: bool
    verdict: str  # observed_over_30m, within_30m, uncertain


def classify_incidents(samples: list[Sample], *, cadence_seconds: int) -> list[Incident]:
    if cadence_seconds <= 0:
        raise ValueError("cadence must be positive")
    if any(s.state not in {"ok", "fail", "missing"} or s.timestamp.tzinfo is None for s in samples):
        raise ValueError("invalid sample")
    groups: dict[tuple[str, str], list[Sample]] = {}
    for sample in samples:
        groups.setdefault((sample.signal, sample.slot), []).append(sample)
    events = []
    for (signal, slot), rows in groups.items():
        rows.sort(key=lambda item: item.timestamp)
        if len({row.timestamp for row in rows}) != len(rows):
            raise ValueError("duplicate timestamp")
        first = last = prior_ok = previous = None
        for row in [*rows, None]:
            connected = (row is not None and last is not None
                         and (row.timestamp - last).total_seconds() <= cadence_seconds * 1.5)
            if first is not None and (row is None or row.state != "fail" or not connected):
                recovery = row if row is not None and row.state == "ok" and connected else None
                observed_span = (last - first).total_seconds()
                outer_window = (recovery.timestamp - prior_ok).total_seconds() if recovery and prior_ok else None
                verdict = ("observed_over_30m" if observed_span > 1800 else
                           "within_30m" if outer_window is not None and outer_window <= 1800 else "uncertain")
                events.append(Incident(signal, slot, first, last,
                                       recovery.timestamp if recovery else None, observed_span, outer_window,
                                       prior_ok is not None, recovery is not None, verdict))
                first = prior_ok = None
            if row is None:
                break
            if row.state == "fail":
                if first is None:
                    first = row.timestamp
                    prior_ok = previous.timestamp if previous and previous.state == "ok" and (
                        row.timestamp - previous.timestamp).total_seconds() <= cadence_seconds * 1.5 else None
                last = row.timestamp
            previous = row
    return events


def load_snapshot(path: Path) -> list[Sample]:
    """Read only a deliberately tiny allowlist; reject accidental raw exports."""
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["timestamp", "signal", "slot", "state"]:
            raise ValueError("snapshot columns must be timestamp,signal,slot,state")
        for row in reader:
            if None in row or not row["timestamp"].endswith("Z"):
                raise ValueError("invalid UTC timestamp or extra column")
            signal, slot, state = row["signal"], row["slot"], row["state"]
            if ((signal == "worker" and slot not in {"slot1", "slot2", "slot3"})
                    or (signal in {"service", "monitor"} and slot != "service")
                    or signal not in {"worker", "service", "monitor"}
                    or state not in {"ok", "fail", "missing"}):
                raise ValueError("invalid signal, slot or state")
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            rows.append(Sample(timestamp, signal, slot, state))
    if not rows:
        raise ValueError("snapshot is empty")
    monitor_rows = sorted((s for s in rows if s.signal == "monitor"), key=lambda s: s.timestamp)
    outages = []
    for i, monitor in enumerate(monitor_rows):
        if monitor.state != "ok":
            end = monitor_rows[i + 1].timestamp if i + 1 < len(monitor_rows) else None
            outages.append((monitor.timestamp, end))
    if any(s.signal != "monitor" and s.state != "missing" and
           any(start <= s.timestamp and (end is None or s.timestamp < end)
               for start, end in outages) for s in rows):
        raise ValueError("monitor outage conflicts with observed target state")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--source", choices=("curator-prometheus", "curator-docker-health"), required=True)
    parser.add_argument("--cadence-seconds", type=int, required=True)
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--period-end", required=True)
    args = parser.parse_args()
    if not args.period_start.endswith("Z") or not args.period_end.endswith("Z"):
        parser.error("period must be UTC with Z suffix")
    start = datetime.fromisoformat(args.period_start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(args.period_end.replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        parser.error("period must be ordered UTC timestamps")
    samples = load_snapshot(args.snapshot)
    if any(not start <= sample.timestamp <= end for sample in samples):
        parser.error("sample outside declared period")
    target_samples = [sample for sample in samples if sample.signal != "monitor"]
    target_keys = {(sample.signal, sample.slot) for sample in target_samples}
    known = {(sample.timestamp, sample.signal, sample.slot) for sample in target_samples}
    for monitor in samples:
        if monitor.signal == "monitor" and monitor.state != "ok":
            for signal, slot in target_keys:
                if (monitor.timestamp, signal, slot) not in known:
                    target_samples.append(Sample(monitor.timestamp, signal, slot, "missing"))
    incidents = classify_incidents(target_samples, cadence_seconds=args.cadence_seconds)
    output = {"source": args.source, "period_start": start.isoformat(), "period_end": end.isoformat(),
              "cadence_seconds": args.cadence_seconds, "sample_count": len(samples),
              "target_sample_count": len(target_samples),
              "coverage_status": ("unknown_no_target_samples" if not target_samples else "sampled_only"),
              "monitor_missing_count": (sum(s.state != "ok" for s in samples if s.signal == "monitor")
                                        if any(s.signal == "monitor" for s in samples) else None),
              "incidents": [{"signal": e.signal, "slot": e.slot,
                             "first_failure": e.first_failure.isoformat(),
                             "first_recovery": e.first_recovery.isoformat() if e.first_recovery else None,
                             "observed_failure_span_seconds": e.observed_failure_span_seconds,
                             "outer_window_seconds": e.outer_window_seconds,
                             "start_confirmed": e.start_confirmed,
                             "recovery_confirmed": e.recovery_confirmed, "verdict": e.verdict}
                            for e in incidents]}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
