#!/usr/bin/env python3
"""
Pulse Relay light show: 4 visitors, 4 Philips Hue light strips, 1 group-synchrony colour.

Reads the same newline-delimited JSON as integrated_prototype.py (from ant_hr_to_json.py)
and drives one Hue light (strip) per visitor:

  * Colour     - each visitor has their own colour from the HRP visual identity swatch.
  * Brightness - follows that visitor's heart rate relative to THEIR OWN resting level
                 (the "mountain": baseline = dim glow, +20 bpm = full brightness).
  * Synchrony  - when the wearers' heart rates rise and fall TOGETHER, every strip blends
                 toward the shared synchrony colour. Apart again -> back to own colours.
  * All changes fade slowly (no flashing), and strips with no wearer rest in a dim
    "waiting" glow of their colour.

Synchrony follows He et al. (2026, PNAS Nexus): heart-rate synchrony = correlation of
z-scored heart-rate time series between people (not "having the same BPM"). They used
5-minute windows for research; for a live installation we use a shorter sliding
window (default 60 s) so the room can respond within a minute.

Run (Windows / PowerShell, real straps, from the project folder with .venv active):

    cmd /d /c 'python -u code\\ant_hr_to_json.py | python -u code\\pulse_relay_show_v1.py --config code\\pulse_relay_config.json --hue --csv'

Find the light names first:

    python code\\pulse_relay_show_v1.py --config code\\pulse_relay_config.json --list-lights

Rehearse without any hardware (coloured preview bars in the terminal, 6x speed):

    python -u code/fake_openant_hr.py --devices 51861,51950,52001,52002 --scenario show --seconds 600 --speed 6 | python -u code/ant_hr_to_json.py --stdin | python -u code/pulse_relay_show_v1.py --preview --time-scale 6
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import integrated_prototype as ip  # reuse message parsing + CSV helpers  # noqa: E402

DEFAULT_CONFIG: dict[str, Any] = {
    "bridge_ip": None,
    # One entry per visitor slot. "light" = Hue light name or number (see --list-lights).
    # "device_id" = heart-rate monitor ID; leave null to assign monitors in the order they appear.
    "visitors": [
        {"name": "Visitor 1", "color": "#FF2DD1", "light": "Strip 1", "device_id": None},
        {"name": "Visitor 2", "color": "#7A00FF", "light": "Strip 2", "device_id": None},
        {"name": "Visitor 3", "color": "#FFDD00", "light": "Strip 3", "device_id": None},
        {"name": "Visitor 4", "color": "#00C8FF", "light": "Strip 4", "device_id": None},
    ],
    "sync_color": "#39DF14",
    "baseline_seconds": 45,      # learn each person's resting level over this long
    "full_scale_bpm": 20,        # +20 bpm above baseline = full brightness
    "min_brightness": 40,        # never fully dark (0-254); dark strips look broken
    "max_brightness": 254,
    "idle_brightness": 25,       # strip with no wearer
    "sync_window_seconds": 60,   # sliding window for the synchrony correlation
    "sync_low": 0.3,             # correlation where blending starts
    "sync_high": 0.7,            # correlation where blending is strongest
    "sync_max_blend": 0.85,      # how far strips move toward the sync colour (0-1)
    "stale_seconds": 10,         # no data for this long -> wearer counts as gone
    "update_interval": 1.0,      # seconds between Hue updates (and fade time)
}


# ---------------------------------------------------------------- colour helpers
def hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _to_linear(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def rgb_to_xy(rgb: tuple[float, float, float]) -> tuple[float, float]:
    """sRGB -> CIE xy using Philips' published wide-gamut conversion."""
    r, g, b = (_to_linear(c) for c in rgb)
    x_ = r * 0.664511 + g * 0.154324 + b * 0.162028
    y_ = r * 0.283881 + g * 0.668433 + b * 0.047685
    z_ = r * 0.000088 + g * 0.072310 + b * 0.986039
    total = x_ + y_ + z_
    if total <= 0:
        return (0.3227, 0.3290)
    return (round(x_ / total, 4), round(y_ / total, 4))


def blend(a: tuple[float, float, float], b: tuple[float, float, float], t: float):
    """Blend two colours in linear light (looks more natural than raw RGB)."""
    la, lb = [_to_linear(c) for c in a], [_to_linear(c) for c in b]
    mixed = [x + (y - x) * t for x, y in zip(la, lb)]
    return tuple(
        (1.055 * m ** (1 / 2.4) - 0.055) if m > 0.0031308 else 12.92 * m for m in mixed
    )


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- state
@dataclass
class Visitor:
    name: str
    color: tuple[float, float, float]
    light: Any
    device_id: str | None
    baseline_samples: list = field(default_factory=list)
    baseline: float | None = None
    latest_bpm: float | None = None
    last_seen: float = -1e9
    history: deque = field(default_factory=lambda: deque(maxlen=900))  # (t, bpm) at 1 Hz
    smooth_bpm: float | None = None

    def active(self, now: float, stale: float) -> bool:
        return self.device_id is not None and now - self.last_seen <= stale


def pearson(a: list[float], b: list[float]) -> float | None:
    if len(a) < 10 or len(a) != len(b):
        return None
    sa, sb = pstdev(a), pstdev(b)
    if sa < 0.5 or sb < 0.5:  # flat signal: correlation is meaningless
        return None
    ma, mb = fmean(a), fmean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) * sa * sb)


def group_sync(visitors: list[Visitor], now: float, window: float, stale: float):
    """Mean pairwise correlation of heart-rate series over the last `window` seconds."""
    series = []
    for v in visitors:
        if not v.active(now, stale):
            continue
        pts = [bpm for (t, bpm) in v.history if now - t <= window]
        series.append(pts)
    if len(series) < 2:
        return None, 0
    n = min(len(s) for s in series)
    if n < 10:
        return None, len(series)
    series = [s[-n:] for s in series]
    rs = [r for i in range(len(series)) for j in range(i + 1, len(series))
          if (r := pearson(series[i], series[j])) is not None]
    return (fmean(rs) if rs else None), len(series)


# ---------------------------------------------------------------- outputs
class HueOut:
    def __init__(self, ip_addr: str | None):
        try:
            from phue import Bridge
        except ImportError as exc:
            raise RuntimeError("Hue support requires phue: pip install phue") from exc
        self.bridge = Bridge(ip_addr) if ip_addr else Bridge()
        self.bridge.connect()
        self.lights = self.bridge.get_light_objects("name")

    def resolve(self, light: Any):
        if isinstance(light, int) or (isinstance(light, str) and light.isdigit()):
            return int(light)
        if light not in self.lights:
            names = ", ".join(sorted(self.lights)) or "none"
            raise RuntimeError(f'Hue light "{light}" not found. Available lights: {names}')
        return self.lights[light].light_id

    def set(self, light_id: int, xy, bri: int, fade_s: float):
        self.bridge.set_light(light_id, {"on": True, "xy": list(xy), "bri": int(bri),
                                         "transitiontime": max(0, round(fade_s * 10))})


def preview_bar(v: Visitor, rgb, bri: int, active: bool, bpm: float | None) -> str:
    scale = 0.35 + 0.65 * bri / 254  # preview only: keep dim strips visible on screen
    r, g, b = (int(255 * c * scale) for c in rgb)
    label = f"{v.name[:10]:<10} {('%5.1f bpm' % bpm) if (active and bpm) else '  waiting'}"
    return f"\033[48;2;{r};{g};{b}m{' ' * 14}\033[0m {label}"


# ---------------------------------------------------------------- main
def load_config(path: str | None) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path:
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
        cfg.update({k: v for k, v in user.items() if not k.startswith("_")})
    return cfg


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pulse Relay: per-visitor Hue colours + group synchrony")
    p.add_argument("--config", help="JSON config (lights, colours, device IDs, thresholds)")
    p.add_argument("--ip", help="Hue Bridge IP (overrides the config)")
    p.add_argument("--hue", action="store_true", help="Send to the real Hue lights")
    p.add_argument("--preview", action="store_true", help="Show coloured bars in the terminal")
    p.add_argument("--list-lights", action="store_true", help="Print Hue light names and exit")
    p.add_argument("--csv", action="store_true", help="Also log beats (ibi_log) and show state")
    p.add_argument("--csv-dir", default=None)
    p.add_argument("--duration", type=float, default=None, help="Stop after N seconds")
    p.add_argument("--time-scale", type=float, default=1.0,
                   help="For sped-up rehearsals only: 1 real second counts as N seconds")
    return p


def main() -> int:
    args = build_parser().parse_args()
    cfg = load_config(args.config)
    bridge_ip = args.ip or cfg.get("bridge_ip")

    if args.list_lights:
        hue = HueOut(bridge_ip)
        for name, light in sorted(hue.lights.items(), key=lambda kv: kv[1].light_id):
            print(f"{light.light_id:>3}  {name}")
        return 0

    visitors = [Visitor(name=v["name"], color=hex_to_rgb(v["color"]), light=v["light"],
                        device_id=str(v["device_id"]) if v.get("device_id") else None)
                for v in cfg["visitors"]]
    sync_rgb = hex_to_rgb(cfg["sync_color"])
    fixed_ids = {v.device_id for v in visitors if v.device_id}

    hue = HueOut(bridge_ip) if args.hue else None
    light_ids = [hue.resolve(v.light) for v in visitors] if hue else [None] * len(visitors)
    if os.name == "nt":
        os.system("")  # enable colours in Windows terminals

    csv_files = []
    state_writer = ibi_writer = None
    if args.csv:
        h1, state_writer, p1 = ip.create_csv_writer(
            args.csv_dir, prefix="show_log",
            fieldnames=["t_s", "visitor", "device_id", "bpm", "baseline", "brightness",
                        "group_sync_r", "sync_blend", "active_wearers"])
        h2, ibi_writer, p2 = ip.create_csv_writer(args.csv_dir, prefix="ibi_log",
                                                  fieldnames=ip.IBI_FIELDNAMES)
        csv_files = [h1, h2]
        print(f"[csv] show state -> {p1}\n[csv] beats -> {p2}", flush=True)

    print("=" * 56 + "\n Pulse Relay light show\n" + "=" * 56, flush=True)
    for v in visitors:
        print(f"[slot] {v.name}: colour {cfg_hex(v.color)} -> light {v.light!r}"
              f"{'' if not v.device_id else f' (monitor {v.device_id})'}", flush=True)
    print(f"[slot] group synchrony colour {cfg['sync_color']}", flush=True)
    print("[input] waiting for heart-rate data...", flush=True)

    start = time.monotonic()
    clock = lambda: (time.monotonic() - start) * args.time_scale  # noqa: E731
    last_sample = last_update = -1e9
    sync_blend = 0.0
    stale = cfg["stale_seconds"]

    try:
        for line in sys.stdin:
            now = clock()
            if args.duration and now >= args.duration:
                print(f"[session] {args.duration:g}s reached; stopping", flush=True)
                break
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            beat = ip.extract_beat(msg)
            if beat is not None:
                if ibi_writer is not None:
                    ibi_writer.writerow({
                        "timestamp": beat.timestamp, "beat_time_ms": beat.beat_time_ms,
                        "t_mono_ms": beat.t_mono_ms, "device_id": beat.device_id,
                        "beat_count": beat.beat_count, "beat_event_time": beat.beat_event_time,
                        "ibi_ms": beat.ibi_ms if beat.ibi_ms is not None else "NA",
                        "gap_ms": beat.gap_ms, "beats_elapsed": beat.beats_elapsed,
                        "bpm_reported": beat.bpm_reported, "quality": beat.quality})
                continue

            for r in ip.extract_readings(msg):
                v = next((x for x in visitors if x.device_id == r.device_id), None)
                if v is None and r.device_id not in fixed_ids:
                    v = next((x for x in visitors if x.device_id is None), None)
                    if v is not None:
                        v.device_id = r.device_id
                        print(f"[assign] monitor {r.device_id} -> {v.name} "
                              f"({cfg_hex(v.color)})", flush=True)
                if v is None:
                    continue
                v.latest_bpm = r.bpm
                v.last_seen = now
                v.smooth_bpm = r.bpm if v.smooth_bpm is None else 0.7 * v.smooth_bpm + 0.3 * r.bpm

            # 1 Hz samples for baselines and synchrony
            if now - last_sample >= 1.0:
                last_sample = now
                for v in visitors:
                    if v.active(now, stale) and v.smooth_bpm is not None:
                        v.history.append((now, v.smooth_bpm))
                        if v.baseline is None:
                            v.baseline_samples.append(v.smooth_bpm)
                            if len(v.baseline_samples) >= cfg["baseline_seconds"]:
                                v.baseline = sorted(v.baseline_samples)[len(v.baseline_samples) // 3]
                                print(f"[baseline] {v.name}: {v.baseline:.1f} bpm", flush=True)
                    elif not v.active(now, stale) and (v.baseline is not None or v.baseline_samples):
                        # wearer left: forget them so the next person gets a fresh baseline
                        print(f"[leave] {v.name} (monitor {v.device_id}) stopped sending", flush=True)
                        v.baseline, v.baseline_samples, v.smooth_bpm = None, [], None
                        v.history.clear()

            if now - last_update < cfg["update_interval"] * args.time_scale:
                continue
            last_update = now

            r_sync, n_active = group_sync(visitors, now, cfg["sync_window_seconds"], stale)
            target = 0.0 if r_sync is None else clamp(
                (r_sync - cfg["sync_low"]) / (cfg["sync_high"] - cfg["sync_low"]), 0, 1)
            sync_blend += (target - sync_blend) * 0.2  # slow, never jumpy
            blend_amt = sync_blend * cfg["sync_max_blend"]

            bars = []
            for v, lid in zip(visitors, light_ids):
                active = v.active(now, stale)
                if not active:
                    rgb, bri = v.color, cfg["idle_brightness"]
                else:
                    ref = v.baseline if v.baseline is not None else (v.smooth_bpm or 0)
                    lift = clamp(((v.smooth_bpm or ref) - ref) / cfg["full_scale_bpm"], 0, 1)
                    bri = round(cfg["min_brightness"]
                                + lift * (cfg["max_brightness"] - cfg["min_brightness"]))
                    rgb = blend(v.color, sync_rgb, blend_amt)
                if hue is not None:
                    hue.set(lid, rgb_to_xy(rgb), bri, cfg["update_interval"])
                if args.preview:
                    bars.append(preview_bar(v, rgb, bri, active, v.smooth_bpm))
                if state_writer is not None and active:
                    state_writer.writerow({
                        "t_s": round(now, 1), "visitor": v.name, "device_id": v.device_id,
                        "bpm": round(v.smooth_bpm or 0, 1),
                        "baseline": round(v.baseline, 1) if v.baseline else "",
                        "brightness": bri,
                        "group_sync_r": "" if r_sync is None else round(r_sync, 3),
                        "sync_blend": round(blend_amt, 3), "active_wearers": n_active})
            for fh in csv_files:
                fh.flush()

            sync_txt = "n/a" if r_sync is None else f"{r_sync:+.2f}"
            status = (f"[sync] t={now:6.0f}s wearers={n_active} r={sync_txt} "
                      f"blend={blend_amt:.2f}")
            if args.preview:
                sr, sg, sb = (int(c * 255) for c in sync_rgb)
                sync_bar = f"\033[48;2;{sr};{sg};{sb}m{' ' * int(round(blend_amt * 14))}\033[0m"
                print("\n".join(bars) + f"\n{status}  together: [{sync_bar:<14}]\n", flush=True)
            else:
                print(status, flush=True)

    except KeyboardInterrupt:
        print("\n[show] stopped by user", flush=True)
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        for fh in csv_files:
            fh.close()
    print("[show] stopped.", flush=True)
    return 0


def cfg_hex(rgb) -> str:
    return "#" + "".join(f"{int(round(c * 255)):02X}" for c in rgb)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())
