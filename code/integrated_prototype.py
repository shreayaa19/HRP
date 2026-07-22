#!/usr/bin/env python3
"""Integrated Human Resonance Project prototype.

Reads newline-delimited heart-rate JSON from stdin, maintains a group BPM,
and optionally previews/controls Philips Hue, writes CSV, and sends OSC.

Examples
--------
Simulation and hardware-free Hue preview:
    python3 code/hr_simulator.py | python3 -u code/integrated_prototype.py \
        --group "Office" --dry-run --mapping dramatic

Real ANT+ input, Hue, and CSV:
    python3 -u code/ant_hr_to_json.py | python3 -u code/integrated_prototype.py \
        --group "Office" --ip 192.168.88.118 --hue --csv

Add OSC:
    ... --osc --osc-ip 127.0.0.1 --osc-port 9000 --osc-addr /bpm
"""

from __future__ import annotations

import argparse
import csv
import json
import math
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
        "--mapping", "-mapping", choices=("dramatic", "smooth"),
        default="dramatic", help="BPM-to-light mapping (default: dramatic)",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.interval < 0:
        parser.error("--interval must be zero or greater")
    if args.window < 1:
        parser.error("--window must be at least 1")
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


def create_csv_writer(csv_dir: str | None) -> tuple[TextIO, csv.DictWriter, Path]:
    directory = Path(csv_dir) if csv_dir else Path.cwd() / "outputs" / "hr_logs"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = directory / f"hr_log_{stamp}.csv"
    counter = 2
    while path.exists():
        path = directory / f"hr_log_{stamp}_{counter}.csv"
        counter += 1

    handle = path.open("w", newline="", encoding="utf-8")
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
            str(group_id)
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

        for line_number, line in enumerate(sys.stdin, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                # Upstream scripts may print human-readable startup messages.
                print(f"[input-warning] line={line_number} skipped non-JSON input: {exc.msg}", flush=True)
                continue

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

    print("[prototype] stopped.", flush=True)
    return 0


if __name__ == "__main__":
    # Let Ctrl+C reach the normal KeyboardInterrupt handler on all platforms.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())