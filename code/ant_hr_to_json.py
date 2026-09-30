#!/usr/bin/env python3
"""
Bridge: ANT+ heart-rate -> newline-delimited JSON (BPM + beat-to-beat R-R/IBI).

Run from the project root with the venv active.

Windows (PowerShell) - real straps into the integrated prototype:

    cmd /d /c 'python -u code\\ant_hr_to_json.py | python -u code\\integrated_prototype.py --group Office --ip 192.168.88.48 --hue --csv --mapping smooth --window 3 --interval 1'

Hardware-free test (fake OpenANT output, any OS):

    python -u code/fake_openant_hr.py --fast | python -u code/ant_hr_to_json.py --stdin | python -u code/integrated_prototype.py --csv --dry-run

What this script does
---------------------
- Runs `python -m openant scan --device_type HeartRate --auto_create`
  (or, with --stdin, reads the same text output from stdin).
- Parses each HeartRateData broadcast line for device_id, heart_rate,
  beat_time (heart-beat event time) and beat_count.
- Emits TWO kinds of JSON line on stdout:

  1. "hr_single" - one per ANT+ broadcast (~4 per second per strap), BPM only.
     Unchanged from before, so the Hue/OSC/BPM-CSV path keeps working:

       {"type": "hr_single",
        "reading": {"ts_iso": "...", "device_id": 51861, "bpm": 88, "rr_ms": null}}

  2. "beat" - one per NEW heartbeat (only when beat_count changes). This is the
     R-R / inter-beat-interval (IBI) record for research analysis:

       {"type": "beat",
        "reading": {"ts_iso": "...", "t_mono_ms": 123456.7, "device_id": 51861,
                    "beat_count": 88, "beat_event_time": 40321,
                    "ibi_ms": 812.5, "bpm_reported": 74,
                    "beats_elapsed": 1, "quality": "ok"}}

How the IBI is computed (ANT+ Heart Rate profile)
------------------------------------------------
- "Heart beat event time" is a 16-bit counter in 1/1024 s ticks that wraps
  every 64 s (65536 ticks). OpenANT prints it as beat_time in seconds
  (ticks / 1024), so we convert back to integer ticks.
- "Heart beat count" is an 8-bit counter (wraps at 256) that goes up by one
  per detected beat. The strap repeats the same beat in several broadcasts,
  so a beat is only "new" when the count changes.
- IBI (ms) = ((this_event_time - previous_event_time) mod 65536) * 1000 / 1024.
  The modulo handles counter rollover. This is measured by the strap - it is
  NOT estimated from BPM.

Quality flags on each beat row
------------------------------
  ok            - exactly one new beat since the last one; ibi_ms is the R-R interval
  missed_beats  - the count jumped by more than 1 (radio dropout). ibi_ms is null
                  because the gap spans several beats; gap_ms and beats_elapsed
                  keep the information for later handling
  out_of_range  - interval outside 300-2000 ms (physiologically implausible);
                  value kept but flagged
Streams are reset (no interval computed) after more than 60 s without a new beat,
because the 64 s counter could have wrapped an unknown number of times.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

# ANT+ counter sizes
EVENT_TIME_ROLLOVER = 65536  # 16-bit, 1/1024 s ticks -> wraps every 64 s
BEAT_COUNT_ROLLOVER = 256    # 8-bit
TICKS_PER_SECOND = 1024

# Plausibility window for a single R-R interval (ms)
IBI_MIN_MS = 300.0   # ~200 BPM
IBI_MAX_MS = 2000.0  # ~30 BPM

# If no new beat arrives for this long, don't trust the wrapped event-time counter
STALE_RESET_S = 60.0

# Device id: OpenANT prints the device as e.g. "heart_rate_51861"
DEVICE_RE = re.compile(r"heart_rate_(\d+)", re.IGNORECASE)
# Fields inside the printed HeartRateData(...) dataclass
FIELD_RES = {
    "heart_rate": re.compile(r"\bheart_rate=(\d+)"),
    "beat_time": re.compile(r"\bbeat_time=(-?[\d.]+)"),
    "beat_count": re.compile(r"\bbeat_count=(\d+)"),
}


@dataclass
class DeviceBeatState:
    """Last beat seen for one strap."""

    event_ticks: int
    beat_count: int
    t_mono: float


def parse_openant_line(line: str) -> dict | None:
    """Pull device_id, heart_rate, beat_time, beat_count out of one OpenANT line.

    Returns None for lines that aren't heart-rate data broadcasts.
    beat_time / beat_count are None if this OpenANT version doesn't print them.
    """
    device_match = DEVICE_RE.search(line)
    hr_match = FIELD_RES["heart_rate"].search(line)
    if not device_match or not hr_match:
        return None

    parsed = {
        "device_id": int(device_match.group(1)),
        "heart_rate": int(hr_match.group(1)),
        "beat_time": None,
        "beat_count": None,
    }
    bt = FIELD_RES["beat_time"].search(line)
    bc = FIELD_RES["beat_count"].search(line)
    if bt:
        beat_time_s = float(bt.group(1))
        if beat_time_s >= 0:  # OpenANT uses -1.0 as "not received yet"
            parsed["beat_time"] = beat_time_s
    if bc:
        parsed["beat_count"] = int(bc.group(1))
    return parsed


class IbiTracker:
    """Turns repeated ANT+ broadcasts into one record per new heartbeat, per device."""

    def __init__(self) -> None:
        self.state: dict[int, DeviceBeatState] = {}

    def update(
        self, device_id: int, beat_time_s: float, beat_count: int, bpm: int, t_mono: float
    ) -> dict | None:
        event_ticks = round(beat_time_s * TICKS_PER_SECOND) % EVENT_TIME_ROLLOVER
        prev = self.state.get(device_id)

        # First sighting of this strap, or it has been silent too long: start fresh.
        if prev is None or (t_mono - prev.t_mono) > STALE_RESET_S:
            self.state[device_id] = DeviceBeatState(event_ticks, beat_count, t_mono)
            return None

        beats_elapsed = (beat_count - prev.beat_count) % BEAT_COUNT_ROLLOVER
        if beats_elapsed == 0:
            return None  # same beat re-broadcast; nothing new

        gap_ticks = (event_ticks - prev.event_ticks) % EVENT_TIME_ROLLOVER
        gap_ms = gap_ticks * 1000.0 / TICKS_PER_SECOND

        if beats_elapsed == 1:
            ibi_ms: float | None = round(gap_ms, 2)
            quality = "ok" if IBI_MIN_MS <= gap_ms <= IBI_MAX_MS else "out_of_range"
        else:
            ibi_ms = None
            quality = "missed_beats"

        self.state[device_id] = DeviceBeatState(event_ticks, beat_count, t_mono)

        return {
            "ts_iso": datetime.now(timezone.utc).isoformat(),
            "t_mono_ms": round(t_mono * 1000.0, 1),
            "device_id": device_id,
            "beat_count": beat_count,
            "beat_event_time": event_ticks,
            "ibi_ms": ibi_ms,
            "gap_ms": round(gap_ms, 2),
            "beats_elapsed": beats_elapsed,
            "bpm_reported": bpm,
            "quality": quality,
        }


def emit(payload: dict, label: str) -> None:
    json_line = json.dumps(payload)
    print(f"[{label}] {json_line}", file=sys.stderr)
    print(json_line, flush=True)  # stdout = the pipe


def process_lines(lines: Iterable[str]) -> None:
    tracker = IbiTracker()
    warned_no_beat_fields = False

    for line in lines:
        line = line.rstrip("\r\n")
        print(f"[raw] {line}", file=sys.stderr)

        parsed = parse_openant_line(line)
        if parsed is None:
            continue

        device_id = parsed["device_id"]
        heart_rate = parsed["heart_rate"]
        t_mono = time.monotonic()
        print(f"[match] device={device_id} hr={heart_rate}", file=sys.stderr)

        # 1) BPM message - same shape as before
        emit(
            {
                "type": "hr_single",
                "reading": {
                    "ts_iso": datetime.now(timezone.utc).isoformat(),
                    "device_id": device_id,
                    "bpm": heart_rate,
                    "rr_ms": None,  # per-beat intervals are sent as "beat" messages
                },
            },
            "json",
        )

        # 2) Beat message - only when a new heartbeat is detected
        if parsed["beat_time"] is None or parsed["beat_count"] is None:
            if not warned_no_beat_fields:
                print(
                    "[ibi-warning] this OpenANT output has no beat_time/beat_count; "
                    "R-R intervals cannot be computed",
                    file=sys.stderr,
                )
                warned_no_beat_fields = True
            continue

        beat = tracker.update(
            device_id, parsed["beat_time"], parsed["beat_count"], heart_rate, t_mono
        )
        if beat is not None:
            emit({"type": "beat", "reading": beat}, "beat")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ANT+ heart rate -> JSON (BPM + R-R/IBI)")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read OpenANT scan text from stdin instead of launching OpenANT "
        "(for testing with fake_openant_hr.py or a saved log)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.stdin:
        print("=== hr_to_json: reading OpenANT text from stdin ===", file=sys.stderr)
        try:
            process_lines(sys.stdin)
        except KeyboardInterrupt:
            print("\n=== hr_to_json: received Ctrl+C, stopping ===", file=sys.stderr)
        return

    cmd = [
        sys.executable, "-u", "-m", "openant", "scan",
        "--device_type", "HeartRate", "--auto_create",
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
        process_lines(proc.stdout)
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
