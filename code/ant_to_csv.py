#!/usr/bin/env python3
"""
Convert ANT+ heart-rate JSON stream → CSV log.

Canonical usage (real straps, auto-numbered logs):
    python ant_hr_to_json.py | python ant_to_csv.py

Simulator usage (no dongle required):
    python ant_test.py --multi --simulate --devices 6 --hz 1.0 \
        | python ant_to_csv.py

If --out is omitted, this script auto-creates:
    <project_root>/outputs/hr_logs/hr_log_001.csv
    <project_root>/outputs/hr_logs/hr_log_002.csv
    ...

It reads lines like:
  {"type":"hr_single","reading":{...}}
  {"type":"hr_batch","readings":[...]}

And writes rows into a CSV log:
  timestamp,device_id,bpm,rr_ms
"""

import argparse
import sys
import json
import csv
import re
import glob
from pathlib import Path


# ---------- paths & filenames ----------

def get_output_dir() -> Path:
    """
    Determine the root-level outputs/hr_logs directory relative to this file.
    ant_to_csv.py lives in <root>/code/, so root is parent of this file's dir.
    """
    script_dir = Path(__file__).resolve().parent
    root_dir = script_dir.parent
    out_dir = root_dir / "outputs" / "hr_logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def next_log_filename(output_dir: Path, prefix: str = "hr_log") -> Path:
    """
    Find the next available log filename like hr_log_001.csv, hr_log_002.csv, ...
    in the given output_dir.
    """
    pattern = str(output_dir / f"{prefix}_*.csv")
    existing = glob.glob(pattern)
    max_idx = 0

    for path_str in existing:
        base = Path(path_str).name
        m = re.match(rf"{re.escape(prefix)}_(\d+)\.csv$", base)
        if m:
            idx = int(m.group(1))
            if idx > max_idx:
                max_idx = idx

    return output_dir / f"{prefix}_{max_idx + 1:03d}.csv"


# ---------- JSON → rows ----------

def extract_rows(msg):
    """
    Convert JSON heart rate messages into rows for CSV.

    Supported formats:
      - {"type":"hr_single","reading":{...}}
      - {"type":"hr_batch","readings":[...]}
    """
    rows = []

    msg_type = msg.get("type")

    # 1) Single reading
    if msg_type == "hr_single":
        r = msg.get("reading", {})
        rows.append([
            r.get("ts_iso"),
            r.get("device_id"),
            r.get("bpm"),
            r.get("rr_ms"),
        ])
        return rows

    # 2) Batch of readings
    if msg_type == "hr_batch":
        for r in msg.get("readings", []):
            rows.append([
                r.get("ts_iso"),
                r.get("device_id"),
                r.get("bpm"),
                r.get("rr_ms"),
            ])
        return rows

    # Anything else: ignore
    return rows


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="Convert ANT JSON stream → CSV log")
    ap.add_argument(
        "--out",
        help=(
            "CSV log file name (no path). "
            "If omitted, auto-names hr_log_###.csv under outputs/hr_logs."
        ),
    )
    args = ap.parse_args()

    output_dir = get_output_dir()

    if args.out:
        # If user passes --out foo.csv, put it inside outputs/hr_logs
        outfile_path = output_dir / args.out
    else:
        outfile_path = next_log_filename(output_dir)

    # This should always appear as soon as ant_to_csv.py starts
    print(f"[ant->csv] Writing to log file: {outfile_path}", file=sys.stderr)

    with outfile_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "device_id", "bpm", "rr_ms"])  # CSV header

        try:
            for line in sys.stdin:
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                for row in extract_rows(msg):
                    writer.writerow(row)
                    # Debug each row so we *know* it's flowing:
                    print(f"[ant->csv] {row}", file=sys.stderr)

        except KeyboardInterrupt:
            print("\n[ant->csv] stopped by user", file=sys.stderr)

    print(f"[ant->csv] CSV log saved to: {outfile_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
