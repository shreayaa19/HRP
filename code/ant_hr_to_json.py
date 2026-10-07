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
- Parses each HeartRateData broadcast line.
- Emits TWO kinds of JSON line on stdout:

  1. "hr_single" - one per ANT+ broadcast (~4 per second per strap), BPM only.
     Unchanged, so the Hue/OSC/BPM-CSV path keeps working.

  2. "beat" - one per heartbeat, with the strap-measured R-R / inter-beat
     interval (IBI) for research analysis:

       {"type": "beat",
        "reading": {"ts_iso": "...", "t_mono_ms": 123456.7, "beat_time_ms": 123301.2,
                    "device_id": 51861, "beat_count": 88, "beat_event_time": 40321,
                    "ibi_ms": 812.5, "gap_ms": 812.5, "beats_elapsed": 1,
                    "bpm_reported": 74, "quality": "ok"}}

How the IBI is computed (ANT+ Heart Rate profile)
------------------------------------------------
- "Heart beat event time" is a 16-bit counter in 1/1024 s ticks that wraps
  every 64 s. OpenANT prints it as beat_time in seconds (ticks / 1024).
- "Heart beat count" is an 8-bit counter (wraps at 256), +1 per beat. The strap
  repeats the same beat in several broadcasts, so a beat is "new" only when the
  count changes.
- IBI (ms) = ((this_event_time - previous_event_time) mod 65536) * 1000 / 1024.
  Measured by the strap; NOT estimated from BPM.

Recovering a missed beat (data page 4)
--------------------------------------
Most straps also send the time of the PREVIOUS beat (page 4). If radio packets
are lost and the count jumps by 2, that field lets us rebuild both intervals
instead of losing them. Rebuilt rows are marked quality = "recovered". The
field is only trusted when it is fresh (it matches the raw page bytes) and
fits exactly between the two known beats.

Single shared clock (beat_time_ms)
----------------------------------
t_mono_ms is when the computer RECEIVED the message (up to ~250 ms after the
beat, because straps broadcast ~4x per second). beat_time_ms estimates when the
beat actually HAPPENED, on the computer's monotonic clock shared by all straps:
the strap's own beat times are mapped onto the computer clock using the
smallest observed receive delay over the last ~60 s. It settles within the first
~30 s of a session; after that it is typically within ~10-20 ms of the true
beat (vs. up to ~250 ms+ for t_mono_ms). Use beat_time_ms to line up different
people's beats.

Quality flags on each beat row
------------------------------
  ok            - one new beat since the last one; ibi_ms is the R-R interval
  recovered     - interval rebuilt from page-4 "previous beat time" after a lost packet
  missed_beats  - the gap spans 2+ beats that couldn't be rebuilt. ibi_ms = NA;
                  gap_ms and beats_elapsed keep the information
  out_of_range  - interval outside 300-2000 ms (implausible); value kept but flagged
Streams reset (no interval) after > 60 s without a new beat, because the 64 s
counter could have wrapped an unknown number of times.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
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

# Window (seconds) of receive-delay observations used to map strap time -> computer time
CLOCK_WINDOW_S = 60.0

DEVICE_RE = re.compile(r"heart_rate_(\d+)", re.IGNORECASE)
FIELD_RES = {
    "heart_rate": re.compile(r"\bheart_rate=(\d+)"),
    "beat_time": re.compile(r"\bbeat_time=(-?[\d.]+)"),
    "beat_count": re.compile(r"\bbeat_count=(\d+)"),
    "page_specific": re.compile(r"\bpage_specific=(\d+)"),
    "previous_heart_beat_time": re.compile(r"\bprevious_heart_beat_time=(-?[\d.]+)"),
}


def parse_openant_line(line: str) -> dict | None:
    """Pull the heart-rate fields out of one OpenANT line (None if not HR data)."""
    device_match = DEVICE_RE.search(line)
    hr_match = FIELD_RES["heart_rate"].search(line)
    if not device_match or not hr_match:
        return None

    def num(key: str, cast):
        m = FIELD_RES[key].search(line)
        return cast(m.group(1)) if m else None

    beat_time = num("beat_time", float)
    prev_time = num("previous_heart_beat_time", float)
    return {
        "device_id": int(device_match.group(1)),
        "heart_rate": int(hr_match.group(1)),
        # OpenANT uses -1.0 as "not received yet"
        "beat_time": beat_time if beat_time is not None and beat_time >= 0 else None,
        "beat_count": num("beat_count", int),
        "page_specific": num("page_specific", int),
        "prev_beat_time": prev_time if prev_time is not None and prev_time >= 0 else None,
    }


def fresh_prev_ticks(parsed: dict) -> int | None:
    """Return page-4 previous-beat time (ticks) only if it came from THIS message.

    OpenANT keeps the last page-4 value around even when other pages arrive, so we
    check it against the raw page bytes: on page 4, page_specific = byte1 | prev<<8.
    """
    prev_s, page_specific = parsed.get("prev_beat_time"), parsed.get("page_specific")
    if prev_s is None or page_specific is None:
        return None
    prev_ticks = round(prev_s * TICKS_PER_SECOND) % EVENT_TIME_ROLLOVER
    return prev_ticks if ((page_specific >> 8) & 0xFFFF) == prev_ticks else None


@dataclass
class DeviceBeatState:
    event_ticks: int            # strap time of latest beat (wrapped, 0-65535)
    beat_count: int
    last_new_beat_mono: float   # computer time we last saw a new beat
    unwrapped_s: float          # strap time of latest beat, unwrapped, in seconds
    delays: deque = field(default_factory=deque)  # (t_recv, t_recv - unwrapped_s)


class IbiTracker:
    """Turns repeated ANT+ broadcasts into one record per heartbeat, per device."""

    def __init__(self) -> None:
        self.state: dict[int, DeviceBeatState] = {}

    @staticmethod
    def _offset(st: DeviceBeatState, t_recv: float) -> float:
        """Strap->computer clock offset: smallest receive delay in the recent window."""
        st.delays.append((t_recv, t_recv - st.unwrapped_s))
        while st.delays and t_recv - st.delays[0][0] > CLOCK_WINDOW_S:
            st.delays.popleft()
        return min(d for _, d in st.delays)

    def update(self, parsed: dict, t_recv: float) -> list[dict]:
        device_id = parsed["device_id"]
        bpm = parsed["heart_rate"]
        beat_count = parsed["beat_count"]
        event_ticks = round(parsed["beat_time"] * TICKS_PER_SECOND) % EVENT_TIME_ROLLOVER
        st = self.state.get(device_id)

        # First sighting, or silent too long: start fresh (no interval yet).
        if st is None or (t_recv - st.last_new_beat_mono) > STALE_RESET_S:
            st = DeviceBeatState(event_ticks, beat_count, t_recv, event_ticks / TICKS_PER_SECOND)
            self.state[device_id] = st
            self._offset(st, t_recv)
            return []

        beats_elapsed = (beat_count - st.beat_count) % BEAT_COUNT_ROLLOVER
        if beats_elapsed == 0:
            self._offset(st, t_recv)  # repeated beat still improves the clock estimate
            return []

        gap_ticks = (event_ticks - st.event_ticks) % EVENT_TIME_ROLLOVER
        start_unwrapped = st.unwrapped_s

        # Segments between known beat times: (ticks, beats_in_segment, recovered?)
        segments: list[tuple[int, int, bool]] = [(gap_ticks, beats_elapsed, False)]
        prev_ticks = fresh_prev_ticks(parsed)
        if beats_elapsed >= 2 and prev_ticks is not None:
            d1 = (prev_ticks - st.event_ticks) % EVENT_TIME_ROLLOVER
            d2 = (event_ticks - prev_ticks) % EVENT_TIME_ROLLOVER
            if 0 < d1 < gap_ticks and d1 + d2 == gap_ticks:
                segments = [(d1, beats_elapsed - 1, True), (d2, 1, True)]

        st.event_ticks = event_ticks
        st.beat_count = beat_count
        st.last_new_beat_mono = t_recv
        st.unwrapped_s = start_unwrapped + gap_ticks / TICKS_PER_SECOND
        offset = self._offset(st, t_recv)

        rows = []
        ts_iso = datetime.now(timezone.utc).isoformat()
        elapsed_ticks = 0
        counted = 0
        for ticks, n_beats, recovered in segments:
            elapsed_ticks += ticks
            counted += n_beats
            gap_ms = ticks * 1000.0 / TICKS_PER_SECOND
            if n_beats == 1:
                ibi_ms: float | None = round(gap_ms, 2)
                if not IBI_MIN_MS <= gap_ms <= IBI_MAX_MS:
                    quality = "out_of_range"
                else:
                    quality = "recovered" if recovered else "ok"
            else:
                ibi_ms, quality = None, "missed_beats"

            beat_unwrapped = start_unwrapped + elapsed_ticks / TICKS_PER_SECOND
            rows.append({
                "ts_iso": ts_iso,
                "t_mono_ms": round(t_recv * 1000.0, 1),
                "beat_time_ms": round((beat_unwrapped + offset) * 1000.0, 1),
                "device_id": device_id,
                "beat_count": (beat_count - beats_elapsed + counted) % BEAT_COUNT_ROLLOVER,
                "beat_event_time": (st.event_ticks - gap_ticks + elapsed_ticks) % EVENT_TIME_ROLLOVER,
                "ibi_ms": ibi_ms,
                "gap_ms": round(gap_ms, 2),
                "beats_elapsed": n_beats,
                "bpm_reported": bpm,
                "quality": quality,
            })
        return rows


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

        t_recv = time.monotonic()
        device_id, heart_rate = parsed["device_id"], parsed["heart_rate"]
        print(f"[match] device={device_id} hr={heart_rate}", file=sys.stderr)

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

        if parsed["beat_time"] is None or parsed["beat_count"] is None:
            if not warned_no_beat_fields:
                print(
                    "[ibi-warning] this OpenANT output has no beat_time/beat_count; "
                    "R-R intervals cannot be computed",
                    file=sys.stderr,
                )
                warned_no_beat_fields = True
            continue

        for beat in tracker.update(parsed, t_recv):
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


def _quiet_exit_on_closed_pipe() -> None:
    """The downstream script stopped (e.g. --duration ended): exit without a traceback."""
    print("\n=== hr_to_json: downstream closed, stopping ===", file=sys.stderr)
    try:
        sys.stdout = open(os.devnull, "w")
    except Exception:
        pass


def main() -> None:
    args = build_parser().parse_args()

    if args.stdin:
        print("=== hr_to_json: reading OpenANT text from stdin ===", file=sys.stderr)
        try:
            process_lines(sys.stdin)
        except KeyboardInterrupt:
            print("\n=== hr_to_json: received Ctrl+C, stopping ===", file=sys.stderr)
        except (BrokenPipeError, OSError):
            _quiet_exit_on_closed_pipe()
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
    except (BrokenPipeError, OSError):
        _quiet_exit_on_closed_pipe()
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
