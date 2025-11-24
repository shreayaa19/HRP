#!/usr/bin/env python3
"""
Hue Simulation from Heart Rate

Reads heart-rate JSON lines (from ant_test.py) on stdin and prints
what Hue group color we *would* set based on group average BPM.

Usage (simulation end-to-end):

  # simulate 6 devices at 1 Hz, pipe into Hue simulator
  python3 code/ant_test.py --multi --simulate --devices 6 --hz 1.0 \
    | python3 code/hue_sim_from_hr.py --group "Gallery" --interval 2.0

Every --interval seconds, this script:
  - computes group average BPM from recent readings
  - maps BPM → hue (blue at low HR, red at high HR)
  - prints a line describing the "virtual" Hue command.
"""

import argparse, sys, json, time
from collections import deque

def map_bpm_to_hue_deg(bpm: float, lo: float = 60.0, hi: float = 120.0) -> float:
    """
    Map BPM in [lo, hi] to a hue angle in degrees.
    Example: 60 bpm → 210° (blue), 120 bpm → 0° (red).
    Values outside the range are clamped.
    """
    if bpm <= lo:
        return 210.0       # calm → blue
    if bpm >= hi:
        return 0.0         # intense → red
    # linear interpolation between 210 and 0
    t = (bpm - lo) / (hi - lo)
    return 210.0 * (1.0 - t)

def main():
    ap = argparse.ArgumentParser(description="Simulate Hue group color from HR JSON (no bridge)")
    ap.add_argument("--group", default="Gallery", help="virtual group name")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between color updates")
    ap.add_argument("--window", type=int, default=50, help="how many recent readings to average")
    args = ap.parse_args()

    # store recent BPM readings
    window = deque(maxlen=args.window)
    last_update = time.time()

    print(f"[sim-hue] listening for HR JSON on stdin; group='{args.group}'", file=sys.stderr)
    print(f"[sim-hue] update interval={args.interval}s, window={args.window} readings", file=sys.stderr)

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # ignore non-JSON lines like "[sim] ..."
                continue

            # accept both hr_single and hr_batch from ant_test.py
            if msg.get("type") == "hr_single":
                reading = msg.get("reading", {})
                bpm = reading.get("bpm")
                if isinstance(bpm, (int, float)):
                    window.append(float(bpm))
            elif msg.get("type") == "hr_batch":
                for r in msg.get("readings", []):
                    bpm = r.get("bpm")
                    if isinstance(bpm, (int, float)):
                        window.append(float(bpm))

            now = time.time()
            if now - last_update >= args.interval and window:
                avg_bpm = sum(window) / len(window)
                hue_deg = map_bpm_to_hue_deg(avg_bpm)
                hue_native = int(round(hue_deg * 65535/360))

                print(
                    f"[sim-hue] group='{args.group}' "
                    f"avg_bpm={avg_bpm:.1f} → hue_deg={hue_deg:.1f}°, native={hue_native}"
                )
                last_update = now

    except KeyboardInterrupt:
        print("\n[sim-hue] stopped by user", file=sys.stderr)

if __name__ == "__main__":
    main()
