#!/usr/bin/env python3
"""Stage 385 gate: compare three measured MCP RSS peaks plus reserve with Compose cap."""

import argparse
import json
from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[1]
MIB = 1024**2


def mcp_limit_bytes() -> int:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    value = compose["services"]["mcp"]["deploy"]["resources"]["limits"]["memory"]
    suffixes = {"M": MIB, "G": 1024 * MIB}
    return int(value[:-1]) * suffixes[value[-1].upper()]


def fits_three_workers(*, peak_rss_bytes: int, reserve_bytes: int = 512 * MIB,
                       limit_bytes: int | None = None) -> bool:
    if peak_rss_bytes <= 0 or reserve_bytes < 0:
        raise ValueError("peak RSS must be positive and reserve nonnegative")
    return 3 * peak_rss_bytes + reserve_bytes <= (mcp_limit_bytes() if limit_bytes is None else limit_bytes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peak-rss-bytes", type=int, required=True)
    parser.add_argument("--reserve-bytes", type=int, default=512 * MIB)
    args = parser.parse_args()
    limit = mcp_limit_bytes()
    required = 3 * args.peak_rss_bytes + args.reserve_bytes
    passed = fits_three_workers(peak_rss_bytes=args.peak_rss_bytes,
                                reserve_bytes=args.reserve_bytes, limit_bytes=limit)
    print(json.dumps({"peak_rss_bytes": args.peak_rss_bytes, "reserve_bytes": args.reserve_bytes,
                      "three_worker_required_bytes": required, "mcp_limit_bytes": limit, "fits": passed}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
