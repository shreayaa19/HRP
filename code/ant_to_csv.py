#!/usr/bin/env python3
"""
Convert ANT+ heart-rate JSON stream → CSV

Usage (simulation):
    python3 code/ant_test.py --multi --simulate --devices 6 --hz 1.0 \
        | python3 code/ant_to_csv.py --out hr_log.csv

This script reads lines like:
  {"type":"hr_batch","readings":[...]}

And writes rows into a CSV that Excel can read:
  timestamp,device_id,bpm,rr_ms
"""

import argparse, sys, json, csv

def extract_rows(msg):
    """Convert hr_single or hr_batch JSON into a list of rows."""
    rows = []
    
    if msg.get("type") == "hr_single":
        r = msg.get("reading", {})
        rows.append([
            r.get("ts_iso"),
            r.get("device_id"),
            r.get("bpm"),
            r.get("rr_ms"),
        ])
    elif msg.get("type") == "hr_batch":
        for r in msg.get("readings", []):
            rows.append([
                r.get("ts_iso"),
                r.get("device_id"),
                r.get("bpm"),
                r.get("rr_ms"),
            ])
    return rows

def main():
    ap = argparse.ArgumentParser(description="Convert ANT JSON stream → CSV")
    ap.add_argument("--out", default="hr_output.csv", help="CSV file to write")
    args = ap.parse_args()

    outfile = args.out

    with open(outfile, "w", newline="") as f:
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

        except KeyboardInterrupt:
            print("\n[ant->csv] stopped by user", file=sys.stderr)

    print(f"[ant->csv] CSV saved to: {outfile}")

if __name__ == "__main__":
    main()
