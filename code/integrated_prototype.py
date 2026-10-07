#!/usr/bin/env python3
"""Integrated Human Resonance Project prototype.

Reads newline-delimited heart-rate JSON from stdin, maintains a group BPM,
and optionally previews/controls Philips Hue, writes CSV, and sends OSC.

Two message types are understood:
- "hr_single" / "hr_batch": BPM readings -> group average -> Hue / OSC / hr_log CSV
- "beat": one per heartbeat with the strap-measured R-R interval (ibi_ms)
  -> ibi_log CSV (one row per beat, for HRV / synchrony analysis).
  Beats are logged only; lights and sound are still driven by BPM.
  Rows without a usable interval show ibi_ms = NA. A missed-beat warning is
  printed only when a strap's recent missed-beat rate exceeds --missed-warn-pct
  (default 5%), and a per-strap data-quality summary is printed at the end.

Stop with Ctrl+C, or pass --duration SECONDS to stop automatically.

Examples
--------
Simulation and hardware-free Hue preview:
    python3 code/hr_simulator.py | python3 -u code/integrated_prototype.py \
        --group "Office" --dry-run --mapping dramatic

Real ANT+ input, Hue, and CSV (Windows PowerShell, Jeremy's setup):
    cmd /d /c 'python -u code\\ant_hr_to_json.py | python -u code\\integrated_prototype.py --group Office --ip 192.168.88.48 --hue --csv --mapping smooth --window 3 --interval 1'

Hardware-free R-R/IBI test:
    python3 -u code/fake_openant_hr.py --fast | python3 -u code/ant_hr_to_json.py --stdin \
        | python3 -u code/integrated_prototype.py --csv --dry-run

Add OSC:
    ... --osc --osc-ip 127.0.0.1 --osc-port 9000 --osc-addr /bpm
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, TextIO


@dataclass(frozen=True)
class Reading:
    timestamp: Any
    device_id: str
    bpm: float
    rr_ms: Any = None


@dataclass(frozen=True)
class Beat:
    """One heartbeat from one strap, with its strap-measured R-R interval."""

    timestamp: Any
    t_mono_ms: Any
    beat_time_ms: Any
    device_id: str
    beat_count: Any
    beat_event_time: Any
    ibi_ms: float | None
    gap_ms: Any
    beats_elapsed: Any
    bpm_reported: Any
    quality: str


IBI_FIELDNAMES = [
    "timestamp", "beat_time_ms", "t_mono_ms", "device_id", "beat_count", "beat_event_time",
    "ibi_ms", "gap_ms", "beats_elapsed", "bpm_reported", "quality",
]


@dataclass(frozen=True)
class HueState:
    color: str
    hue_degrees: float
    hue_native: int
    saturation: int
    brightness: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Route HR JSON from stdin to Hue, CSV, and/or OSC."
    )
    parser.add_argument("--group", "-group", default="Office", help="Hue group/zone name")
    parser.add_argument("--ip", "-ip", help="Hue Bridge IP (otherwise phue discovery is used)")
    parser.add_argument(
        "--interval", "-interval", type=float, default=1.0,
        help="Minimum seconds between Hue updates (default: 1.0)",
    )
    parser.add_argument(
        "--window", "-window", type=int, default=10,
        help="Group-average moving window size (default: 10)",
    )
    parser.add_argument(
        "--device", "-device",
        help="Drive outputs from one device instead of the group average",
    )
    parser.add_argument("--hue", "-hue", action="store_true", help="Enable real Hue updates")
    parser.add_argument("--csv", "-csv", action="store_true", help="Enable CSV logging")
    parser.add_argument(
        "--csv-dir", default=None,
        help="CSV directory (default: outputs/hr_logs under the current directory)",
    )
    parser.add_argument("--osc", "-osc", action="store_true", help="Enable OSC output")
    parser.add_argument("--osc-ip", "-osc-ip", default="127.0.0.1")
    parser.add_argument("--osc-port", "-osc-port", type=int, default=9000)
    parser.add_argument("--osc-addr", "-osc-addr", default="/bpm")
    parser.add_argument(
        "--dry-run", "-dry-run", action="store_true",
        help="Preview network/hardware outputs without sending them",
    )
    parser.add_argument(
        "--duration", "-duration", type=float, default=None,
        help="Stop automatically after this many seconds (default: run until Ctrl+C)",
    )
    parser.add_argument(
        "--missed-warn-pct", type=float, default=5.0,
        help="Warn only if a strap misses more than this %% of its recent beats (default: 5)",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Plain terminal output (no orange warnings)",
    )
    parser.add_argument(
        "--mapping", "-mapping", choices=("dramatic", "smooth"),
        default="dramatic", help="BPM-to-light mapping (default: dramatic)",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.interval < 0:
        parser.error("--interval must be zero or greater")
    if args.window < 1:
        parser.error("--window must be at least 1")
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be greater than zero")
    if not 0 <= args.missed_warn_pct <= 100:
        parser.error("--missed-warn-pct must be between 0 and 100")
    if not 1 <= args.osc_port <= 65535:
        parser.error("--osc-port must be between 1 and 65535")


def _reading_from_dict(value: Any) -> Reading | None:
    if not isinstance(value, dict):
        return None

    # Accept the current project names plus a few common aliases.
    device_id = value.get("device_id", value.get("device", value.get("id")))
    bpm = value.get("bpm", value.get("heart_rate"))
    if device_id is None or bpm is None:
        return None

    try:
        bpm_value = float(bpm)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(bpm_value) or bpm_value <= 0:
        return None

    timestamp = value.get("ts_iso", value.get("timestamp", value.get("ts")))
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    return Reading(
        timestamp=timestamp,
        device_id=str(device_id),
        bpm=bpm_value,
        rr_ms=value.get("rr_ms"),
    )


def extract_readings(message: Any) -> list[Reading]:
    """Extract readings from hr_single, hr_batch, or a bare reading object."""
    if not isinstance(message, dict):
        return []

    message_type = message.get("type")
    candidates: Iterable[Any]

    if message_type == "hr_single":
        candidates = [message.get("reading", message.get("data", message))]
    elif message_type == "hr_batch":
        batch = message.get("readings", message.get("data", message.get("batch", [])))
        if isinstance(batch, dict):
            batch = batch.get("readings", [])
        candidates = batch if isinstance(batch, list) else []
    elif "readings" in message and isinstance(message["readings"], list):
        candidates = message["readings"]
    else:
        candidates = [message]

    return [reading for item in candidates if (reading := _reading_from_dict(item))]


def extract_beat(message: Any) -> Beat | None:
    """Parse a {"type": "beat", "reading": {...}} message from ant_hr_to_json.py."""
    if not isinstance(message, dict) or message.get("type") != "beat":
        return None
    value = message.get("reading", message.get("data"))
    if not isinstance(value, dict) or value.get("device_id") is None:
        return None

    ibi = value.get("ibi_ms")
    try:
        ibi_value = float(ibi) if ibi is not None else None
    except (TypeError, ValueError):
        ibi_value = None
    if ibi_value is not None and not math.isfinite(ibi_value):
        ibi_value = None

    return Beat(
        timestamp=value.get("ts_iso") or datetime.now(timezone.utc).isoformat(),
        t_mono_ms=value.get("t_mono_ms"),
        beat_time_ms=value.get("beat_time_ms"),
        device_id=str(value["device_id"]),
        beat_count=value.get("beat_count"),
        beat_event_time=value.get("beat_event_time"),
        ibi_ms=ibi_value,
        gap_ms=value.get("gap_ms"),
        beats_elapsed=value.get("beats_elapsed"),
        bpm_reported=value.get("bpm_reported"),
        quality=str(value.get("quality", "unknown")),
    )


ORANGE = "\033[38;5;208m"
RESET = "\033[0m"


class MissedBeatMonitor:
    """Tracks, per strap, what share of beats had no usable R-R interval.

    Every beat row is still flagged in the CSV; this only decides when to WARN,
    so occasional radio dropouts don't spam the terminal.
    """

    WINDOW_BEATS = 60  # judge the recent rate over roughly the last minute

    def __init__(self, threshold_pct: float, color: bool) -> None:
        self.threshold = threshold_pct
        self.color = color
        self.recent: dict[str, deque[int]] = {}   # 1 = beat had no interval, 0 = ok
        self.total: dict[str, int] = {}
        self.missed: dict[str, int] = {}
        self.warning_active: dict[str, bool] = {}

    def paint(self, text: str) -> str:
        return f"{ORANGE}{text}{RESET}" if self.color else text

    def add(self, beat: "Beat") -> str | None:
        """Record a beat row; return a warning line only when the threshold is crossed."""
        n = beat.beats_elapsed if isinstance(beat.beats_elapsed, int) and beat.beats_elapsed > 0 else 1
        no_interval = 1 if beat.ibi_ms is None else 0
        dev = beat.device_id
        window = self.recent.setdefault(dev, deque(maxlen=self.WINDOW_BEATS))
        for _ in range(n):
            window.append(no_interval)
        self.total[dev] = self.total.get(dev, 0) + n
        self.missed[dev] = self.missed.get(dev, 0) + n * no_interval

        if len(window) < 20:  # too early to judge
            return None
        pct = 100.0 * sum(window) / len(window)
        active = self.warning_active.get(dev, False)
        if pct > self.threshold and not active:
            self.warning_active[dev] = True
            return self.paint(
                f"[ibi-warning] device={dev}: {pct:.0f}% of the last {len(window)} beats "
                f"had no interval (threshold {self.threshold:g}%). Check strap contact and "
                f"dongle distance/line of sight."
            )
        if pct <= self.threshold / 2 and active:
            self.warning_active[dev] = False
            return f"[ibi] device={dev}: missed-beat rate back to {pct:.0f}%"
        return None

    def summary_lines(self) -> list[str]:
        lines = []
        for dev in sorted(self.total):
            total, missed = self.total[dev], self.missed[dev]
            pct = 100.0 * missed / total if total else 0.0
            status = "OK" if pct <= self.threshold else "CHECK"
            line = (f"[ibi-summary] device={dev} beats={total} without_interval={missed} "
                    f"({pct:.1f}%) -> {status}")
            lines.append(self.paint(line) if status == "CHECK" else line)
        return lines


def enable_windows_ansi() -> None:
    """Let Windows consoles show colors (no-op elsewhere)."""
    if os.name == "nt":
        os.system("")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def degrees_to_native(degrees: float) -> int:
    return round((degrees % 360.0) / 360.0 * 65535)


def dramatic_mapping(bpm: float) -> HueState:
    """High-contrast debug mapping intended to be obvious across a room."""
    if bpm < 80:
        color, degrees, brightness = "blue", 240.0, 90
    elif bpm < 95:
        # Green at 80 BPM, shifting toward yellow by 94 BPM.
        ratio = (bpm - 80.0) / 15.0
        color = "green/yellow"
        degrees = 120.0 - (60.0 * ratio)
        brightness = round(155 + (45 * ratio))
    else:
        color, degrees, brightness = "red", 0.0, 254

    return HueState(
        color=color,
        hue_degrees=degrees,
        hue_native=degrees_to_native(degrees),
        saturation=254,
        brightness=int(clamp(brightness, 1, 254)),
    )


def smooth_mapping(bpm: float) -> HueState:
    """Continuous blue-to-red mapping across 60-120 BPM."""
    ratio = (clamp(bpm, 60.0, 120.0) - 60.0) / 60.0
    degrees = 240.0 * (1.0 - ratio)
    brightness = round(90 + (164 * ratio))
    return HueState(
        color="smooth blue-to-red",
        hue_degrees=degrees,
        hue_native=degrees_to_native(degrees),
        saturation=254,
        brightness=brightness,
    )


def map_bpm(bpm: float, mapping: str) -> HueState:
    return dramatic_mapping(bpm) if mapping == "dramatic" else smooth_mapping(bpm)


def create_csv_writer(
    csv_dir: str | None,
    prefix: str = "hr_log",
    fieldnames: list[str] | None = None,
) -> tuple[TextIO, csv.DictWriter, Path]:
    directory = Path(csv_dir) if csv_dir else Path.cwd() / "outputs" / "hr_logs"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = directory / f"{prefix}_{stamp}.csv"
    counter = 2
    while path.exists():
        path = directory / f"{prefix}_{stamp}_{counter}.csv"
        counter += 1

    handle = path.open("w", newline="", encoding="utf-8")
    if fieldnames is None:
        fieldnames = [
            "timestamp", "device_id", "bpm", "rr_ms",
            "group_average_bpm", "output_bpm",
        ]
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    handle.flush()
    return handle, writer, path


def connect_hue(ip: str | None, group_name: str):
    try:
        from phue import Bridge
    except ImportError as exc:
        raise RuntimeError(
            "Hue support requires phue. Install it with: pip install phue"
        ) from exc

    bridge = Bridge(ip) if ip else Bridge()
    bridge.connect()
    groups = bridge.get_group()
    group_id = next(
        (
            int(group_id)  # int, not str: phue treats a string as a group NAME
            for group_id, details in groups.items()
            if str(details.get("name", "")).casefold() == group_name.casefold()
        ),
        None,
    )
    if group_id is None:
        available = ", ".join(
            sorted(str(details.get("name", group_id)) for group_id, details in groups.items())
        )
        raise RuntimeError(
            f'Hue group "{group_name}" was not found. Available groups: {available or "none"}'
        )
    return bridge, group_id


def apply_hue(bridge: Any, group_id: str, state: HueState, interval: float) -> None:
    # Hue transitiontime uses tenths of a second.
    transition = max(0, round(interval * 10))
    bridge.set_group(
        group_id,
        {
            "on": True,
            "hue": state.hue_native,
            "sat": state.saturation,
            "bri": state.brightness,
            "transitiontime": transition,
        },
    )


def format_bpm(value: float) -> str:
    return f"{value:.1f}"


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(parser, args)

    latest_bpm: dict[str, float] = {}
    group_history: deque[float] = deque(maxlen=args.window)
    last_hue_update = float("-inf")
    csv_handle: TextIO | None = None
    csv_writer: csv.DictWriter | None = None
    ibi_handle: TextIO | None = None
    ibi_writer: csv.DictWriter | None = None
    beats_logged = 0
    beat_quality_counts: dict[str, int] = {}
    color = not args.no_color and sys.stdout.isatty()
    if color:
        enable_windows_ansi()
    missed_monitor = MissedBeatMonitor(args.missed_warn_pct, color)
    started = time.monotonic()
    bridge = group_id = osc_client = None

    print("=" * 46, flush=True)
    print(" Integrated HR-Hue Prototype", flush=True)
    print("=" * 46, flush=True)
    print(
        f"[config] group={args.group!r} mapping={args.mapping} "
        f"window={args.window} interval={args.interval:.1f}s dry_run={args.dry_run}",
        flush=True,
    )

    try:
        if args.csv:
            csv_handle, csv_writer, csv_path = create_csv_writer(args.csv_dir)
            print(f"[csv] logging to {csv_path}", flush=True)
            ibi_handle, ibi_writer, ibi_path = create_csv_writer(
                args.csv_dir, prefix="ibi_log", fieldnames=IBI_FIELDNAMES
            )
            print(f"[ibi-csv] logging beat-to-beat R-R intervals to {ibi_path}", flush=True)

        if args.hue and not args.dry_run:
            print(f"[hue] connecting to bridge at {args.ip or 'auto-discovery'}...", flush=True)
            bridge, group_id = connect_hue(args.ip, args.group)
            print(f"[hue] connected; group={args.group!r} id={group_id}", flush=True)
        elif args.dry_run:
            print("[hue-dry-run] hardware updates will only be previewed", flush=True)

        if args.osc and not args.dry_run:
            try:
                from pythonosc.udp_client import SimpleUDPClient
            except ImportError as exc:
                raise RuntimeError(
                    "OSC support requires python-osc. Install it with: pip install python-osc"
                ) from exc
            osc_client = SimpleUDPClient(args.osc_ip, args.osc_port)
            print(
                f"[osc] enabled -> {args.osc_ip}:{args.osc_port} addr={args.osc_addr}",
                flush=True,
            )
        elif args.osc and args.dry_run:
            print(
                f"[osc-dry-run] previewing {args.osc_addr} -> "
                f"{args.osc_ip}:{args.osc_port}",
                flush=True,
            )

        print("[input] listening for newline-delimited HR JSON on stdin", flush=True)

        if args.duration is not None:
            print(f"[session] will stop automatically after {args.duration:g}s", flush=True)

        for line_number, line in enumerate(sys.stdin, start=1):
            if args.duration is not None and time.monotonic() - started >= args.duration:
                print(f"[session] {args.duration:g}s reached; stopping", flush=True)
                break
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                # Upstream scripts may print human-readable startup messages.
                print(f"[input-warning] line={line_number} skipped non-JSON input: {exc.msg}", flush=True)
                continue

            beat = extract_beat(message)
            if beat is not None:
                beats_logged += 1
                beat_quality_counts[beat.quality] = beat_quality_counts.get(beat.quality, 0) + 1
                ibi_text = f"{beat.ibi_ms:.1f}" if beat.ibi_ms is not None else "NA"
                beat_line = (
                    f"[beat] device={beat.device_id} count={beat.beat_count} "
                    f"ibi_ms={ibi_text} quality={beat.quality}"
                )
                print(missed_monitor.paint(beat_line) if beat.ibi_ms is None else beat_line,
                      flush=True)
                warning = missed_monitor.add(beat)
                if warning:
                    print(warning, flush=True)
                if ibi_writer is not None and ibi_handle is not None:
                    ibi_writer.writerow(
                        {
                            "timestamp": beat.timestamp,
                            "beat_time_ms": beat.beat_time_ms,
                            "t_mono_ms": beat.t_mono_ms,
                            "device_id": beat.device_id,
                            "beat_count": beat.beat_count,
                            "beat_event_time": beat.beat_event_time,
                            "ibi_ms": beat.ibi_ms if beat.ibi_ms is not None else "NA",
                            "gap_ms": beat.gap_ms,
                            "beats_elapsed": beat.beats_elapsed,
                            "bpm_reported": beat.bpm_reported,
                            "quality": beat.quality,
                        }
                    )
                    ibi_handle.flush()
                    print("[ibi-csv] wrote 1 row", flush=True)
                continue  # beats are logged only; BPM messages drive Hue/OSC

            readings = extract_readings(message)
            if not readings:
                print(f"[input-warning] line={line_number} contains no valid HR readings", flush=True)
                continue

            for reading in readings:
                latest_bpm[reading.device_id] = reading.bpm
                raw_group_average = fmean(latest_bpm.values())
                group_history.append(raw_group_average)
                moving_group_average = fmean(group_history)

                if args.device is not None:
                    if args.device not in latest_bpm:
                        print(
                            f"[input] device={reading.device_id} bpm={format_bpm(reading.bpm)} | "
                            f"waiting for selected device={args.device}",
                            flush=True,
                        )
                        continue
                    output_bpm = latest_bpm[args.device]
                    output_source = f"device {args.device}"
                else:
                    output_bpm = moving_group_average
                    output_source = "group moving average"

                print(
                    f"[input] device={reading.device_id} bpm={format_bpm(reading.bpm)} "
                    f"rr_ms={reading.rr_ms}",
                    flush=True,
                )
                print(
                    f"[group] devices={len(latest_bpm)} current={format_bpm(raw_group_average)} "
                    f"moving={format_bpm(moving_group_average)} output={format_bpm(output_bpm)} "
                    f"source={output_source}",
                    flush=True,
                )

                if csv_writer is not None and csv_handle is not None:
                    csv_writer.writerow(
                        {
                            "timestamp": reading.timestamp,
                            "device_id": reading.device_id,
                            "bpm": reading.bpm,
                            "rr_ms": reading.rr_ms,
                            "group_average_bpm": round(moving_group_average, 3),
                            "output_bpm": round(output_bpm, 3),
                        }
                    )
                    csv_handle.flush()
                    print("[csv] wrote 1 row", flush=True)

                if args.osc:
                    if args.dry_run:
                        print(
                            f"[osc-dry-run] would send {args.osc_addr} "
                            f"{format_bpm(output_bpm)} -> {args.osc_ip}:{args.osc_port}",
                            flush=True,
                        )
                    else:
                        osc_client.send_message(args.osc_addr, float(output_bpm))
                        print(
                            f"[osc] sent {args.osc_addr} {format_bpm(output_bpm)} -> "
                            f"{args.osc_ip}:{args.osc_port}",
                            flush=True,
                        )

                now = time.monotonic()
                should_update_hue = (args.hue or args.dry_run) and (
                    now - last_hue_update >= args.interval
                )
                if should_update_hue:
                    state = map_bpm(output_bpm, args.mapping)
                    detail = (
                        f"group={args.group!r} bpm={format_bpm(output_bpm)} "
                        f"color={state.color} hue={state.hue_degrees:.1f}deg/"
                        f"{state.hue_native} bri={state.brightness} sat={state.saturation}"
                    )
                    if args.dry_run:
                        print(f"[hue-dry-run] would set {detail}", flush=True)
                    else:
                        apply_hue(bridge, group_id, state, args.interval)
                        print(f"[hue] updated {detail}", flush=True)
                    last_hue_update = now

    except KeyboardInterrupt:
        print("\n[prototype] stopped by user", flush=True)
    except BrokenPipeError:
        return 0
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        if csv_handle is not None:
            csv_handle.close()
        if ibi_handle is not None:
            ibi_handle.close()
        if beats_logged:
            summary = ", ".join(f"{k}={v}" for k, v in sorted(beat_quality_counts.items()))
            print(f"[ibi] beats logged: {beats_logged} ({summary})", flush=True)
            for line in missed_monitor.summary_lines():
                print(line, flush=True)

    print("[prototype] stopped.", flush=True)
    return 0


if __name__ == "__main__":
    # Let Ctrl+C reach the normal KeyboardInterrupt handler on all platforms.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())