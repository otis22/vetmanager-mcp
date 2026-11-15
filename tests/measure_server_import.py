"""Local-only, bounded import timing; never persist raw child stderr."""

import argparse
import json
import os
import re
import subprocess
import sys


IMPORT_LINE = re.compile(r"^import time:\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([A-Za-z_][A-Za-z_0-9.]*)\s*$")


def measure(count, *, profile):
    children = []
    code = "import time; started=time.monotonic(); import server; print('IMPORT_ELAPSED_MS=%d' % round((time.monotonic()-started)*1000))"
    for _ in range(count):
        command = [sys.executable, "-X", "importtime", "-c", code] if profile else [sys.executable, "-c", code]
        process = subprocess.Popen(command,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        children.append(process)
    results = []
    for process in children:
        try:
            stdout, stderr = process.communicate(timeout=60)
            exit_class = "zero" if process.returncode == 0 else "nonzero"
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            exit_class = "timeout"
        elapsed = next((int(line.split("=", 1)[1]) for line in stdout.splitlines()
                        if re.fullmatch(r"IMPORT_ELAPSED_MS=\d+", line)), None)
        durations = [(module, int(self_us), int(total_us))
                     for line in stderr.splitlines()
                     if (match := IMPORT_LINE.fullmatch(line))
                     for self_us, total_us, module in [match.groups()]]
        results.append({"elapsed_ms": elapsed,
                        "exit_class": exit_class,
                        "top_modules": [{"module": module, "self_ms": round(self_us / 1000, 2),
                                         "cumulative_ms": round(total_us / 1000, 2)}
                                        for module, self_us, total_us in
                                        sorted(durations, key=lambda item: item[1], reverse=True)[:12]]})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--counts", default="1,3,6")
    parser.add_argument("--no-profile", action="store_true")
    args = parser.parse_args()
    output = {"schema_version": 1, "container_process_cache": "first_import_in_fresh_container",
              "filesystem_cache": "uncontrolled", "series": []}
    for count in (int(part) for part in args.counts.split(",")):
        if count not in (1, 3, 6):
            parser.error("counts must use 1, 3 or 6")
        results = measure(count, profile=not args.no_profile)
        output["series"].append({"concurrency": count, "results": results})
        if any(result["exit_class"] != "zero" for result in results):
            break
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(output, stream, sort_keys=True)


if __name__ == "__main__":
    main()
