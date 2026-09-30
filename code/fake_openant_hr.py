#!/usr/bin/env python3
"""
Fake OpenANT heart-rate output for testing R-R/IBI capture without straps.

Prints lines in the same format as `python -m openant scan --device_type HeartRate
--auto_create`, so it can be piped into `ant_hr_to_json.py --stdin`:

    python -u code/fake_openant_hr.py --fast | python -u code/ant_hr_to_json.py --stdin \
        | python -u code/integrated_prototype.py --csv --dry-run

What it simulates (per strap):
- Beat-to-beat intervals that vary naturally (breathing rhythm + noise)
- ~4 broadcasts per second, each repeating the latest beat (like a real strap)
- Beat event time starting near 64 s so the 16-bit counter rolls over early
- Beat count rolling over at 256
- Optional radio dropouts (--drop) so some beats are missed

Use --truth FILE to save the true intervals and compare them with the CSV.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
import time

BROADCAST_PERIOD_S = 8070 / 32768  # ANT+ HR channel period (~0.246 s, ~4.06 Hz)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fake OpenANT HR output with real beat timing")
    p.add_argument("--devices", default="51861,51950", help="Comma-separated device IDs")
    p.add_argument("--seconds", type=float, default=90.0, help="Simulated duration")
    p.add_argument("--fast", action="store_true", help="Don't sleep; print as fast as possible")
    p.add_argument("--drop", type=float, default=0.0,
                   help="Probability each broadcast is lost (e.g. 0.3 to force missed beats)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--truth", help="Write true intervals to this CSV for validation")
    return p


class FakeStrap:
    def __init__(self, device_id: int, base_ibi_ms: float, rng: random.Random) -> None:
        self.device_id = device_id
        self.base = base_ibi_ms
        self.rng = rng
        self.t = 0.0
        # Start close to the 64 s wrap so rollover is exercised in the first minute
        self.event_ticks = 65536 - rng.randint(2000, 6000)
        self.beat_count = rng.randint(240, 255)  # rolls over at 256 soon
        self.next_beat_t = 0.0
        self.last_ibi_ms = base_ibi_ms
        self.bpm = round(60000 / base_ibi_ms)

    def next_ibi_ms(self) -> float:
        # respiratory sinus arrhythmia (~0.25 Hz) + small random variation
        rsa = 40.0 * math.sin(2 * math.pi * 0.25 * self.t)
        return max(350.0, self.base + rsa + self.rng.gauss(0, 15))

    def advance_to(self, t: float, truth_rows: list) -> None:
        while self.next_beat_t <= t:
            ibi = self.next_ibi_ms()
            self.t = self.next_beat_t
            ticks = round(ibi * 1024 / 1000)
            self.event_ticks = (self.event_ticks + ticks) % 65536
            self.beat_count = (self.beat_count + 1) % 256
            self.last_ibi_ms = ticks * 1000 / 1024  # quantised like the real strap
            self.bpm = round(60000 / self.last_ibi_ms)
            truth_rows.append((self.device_id, self.beat_count, self.event_ticks,
                               round(self.last_ibi_ms, 2)))
            self.next_beat_t += ibi / 1000.0

    def line(self) -> str:
        return (
            f"Device heart_rate_{self.device_id:05} broadcast heart_rate data: HeartRateData("
            f"page_specific=16777215, beat_time={self.event_ticks / 1024}, "
            f"beat_count={self.beat_count}, heart_rate={self.bpm}, "
            f"operating_time=16777215, manufacturer_id_lsb=255, serial_number=65535, "
            f"previous_heart_beat_time=-1.0, battery_percentage=255)"
        )


def main() -> None:
    args = build_parser().parse_args()
    rng = random.Random(args.seed)
    ids = [int(x) for x in args.devices.split(",") if x.strip()]
    straps = [FakeStrap(d, base_ibi_ms=780 + 90 * i, rng=rng) for i, d in enumerate(ids)]
    truth: list = []

    print("Starting scanner for #0, type 120, press Ctrl-C to finish", flush=True)
    for s in straps:
        print(f"Found new device #{s.device_id} DeviceType.HeartRate; device_type: 120, "
              f"transmission_type: 1", flush=True)

    t = 0.0
    try:
        while t < args.seconds:
            for s in straps:
                s.advance_to(t, truth)
                if rng.random() >= args.drop:
                    print(s.line(), flush=True)
            t += BROADCAST_PERIOD_S
            if not args.fast:
                time.sleep(BROADCAST_PERIOD_S)
    except (KeyboardInterrupt, BrokenPipeError):
        pass

    if args.truth:
        with open(args.truth, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["device_id", "beat_count", "beat_event_time", "true_ibi_ms"])
            w.writerows(truth)
        print(f"[fake] wrote {len(truth)} true beats to {args.truth}", file=sys.stderr)


if __name__ == "__main__":
    main()
