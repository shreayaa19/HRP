#!/usr/bin/env python3
"""
Bridge: ANT+ heart-rate → JSON (for piping into ant_to_csv.py)

Run from HRP_shreayaa/code with venv active:

    python ant_hr_to_json.py | python ant_to_csv.py

This script:

- Runs `python -m openant scan --device_type HeartRate --auto_create`
- Parses its text output to extract device_id + heart_rate
- Prints one JSON object per HR sample to stdout (newline-delimited)

JSON format emitted (matches simulator):

  {
    "type": "hr_single",
    "reading": {
      "ts_iso": "...",
      "device_id": 51861,
      "bpm": 88,
      "rr_ms": null
    }
  }
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone

# Be forgiving: just look for "heart_rate_<digits>" and "heart_rate=<digits>"
HR_LINE_RE = re.compile(
    r"heart_rate_(\d+).*heart_rate=(\d+)",
    re.IGNORECASE,
)


def main() -> None:
    cmd = [
        sys.executable,
        "-u",
        "-m",
        "openant",
        "scan",
        "--device_type",
        "HeartRate",
        "--auto_create",
    ]

    print("=== hr_to_json: starting ANT+ heart-rate scan ===", file=sys.stderr)
    print("Subprocess command:", " ".join(cmd), file=sys.stderr)
    print("Make sure at least one strap is on & awake.\n", file=sys.stderr)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # line-buffered
    )

    assert proc.stdout is not None

    try:
        for line in proc.stdout:
            line = line.rstrip("\r\n")

            # Debug: show every line we get from openant
            print(f"[raw] {line}", file=sys.stderr)

            # Try to extract device id + heart rate from any line
            m = HR_LINE_RE.search(line)
            if not m:
                continue

            device_id_str, hr_str = m.groups()
            device_id = int(device_id_str)
            heart_rate = int(hr_str)

            # ISO timestamp in UTC
            ts_iso = datetime.now(timezone.utc).isoformat()

            payload = {
                "type": "hr_single",
                "reading": {
                    "ts_iso": ts_iso,
                    "device_id": device_id,
                    "bpm": heart_rate,
                    "rr_ms": None,  # we don't have RR interval yet
                },
            }

            # For debugging, show what we matched on stderr
            print(f"[match] device={device_id} hr={heart_rate}", file=sys.stderr)

            # NEW: also show the JSON we’re about to emit
            json_line = json.dumps(payload)
            print(f"[json] {json_line}", file=sys.stderr)

            # JSON line to stdout (this is what we’ll pipe)
            print(json_line, flush=True)

    except KeyboardInterrupt:
        print("\n=== hr_to_json: received Ctrl+C, stopping ===", file=sys.stderr)
    finally:
        try:
            proc.terminate()
        except Exception:
            pass

        try:
            proc.wait(timeout=2)
        except Exception:
            pass


if __name__ == "__main__":
    main()
