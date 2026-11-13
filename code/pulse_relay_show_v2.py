#!/usr/bin/env python3
"""
Pulse Relay light show - V2 ("jellyfish" version).

V2 adds the ideas from the Oct 27 and Nov 3 design meetings on top of V1:

  1. Own palette     - each visitor has a family of 5 neighbouring colours (similar
                       brightness/contrast) instead of one flat colour.
  2. Flutter         - the strip drifts slowly through its palette and shimmers like
                       deep-sea jellyfish / a spa bubble wall. Calm = slow, excited =
                       quicker, but NEVER frantic (speed is capped).
  3. Heart rate      - the "ball": higher heart rate (vs. the person's own resting
                       level) = brighter, livelier light. Always on, never dark.
  4. HRV (2nd data channel) - beat-to-beat variability (RMSSD, from the R-R log)
                       sets how deep and smooth the shimmer is: more variability
                       (usually calmer) = slower, softer breathing of the light.
  5. Pairs           - when two people's heart rates move together, each strip pulls
                       in the other's colour: occasional "particles" of the partner's
                       colour drift in, and a gentle tint builds the longer they stay
                       in sync. Each person KEEPS their own colour (identity).
  6. Whole group     - when everyone is in sync, a slow, big "ocean wave" of deep blue,
                       purple and red rolls across all strips, under their own colours.
  7. Coming to life  - a new wearer's strip fades in gently over ~20 s.
  Optional: a 5th light (the paper lamp in the dorm area) that glows with the
  colours of whoever is in sync.

Hardware note: Hue Lightstrip Plus strips show ONE colour along the whole strip at a
time, so these effects play out over time (shimmer, tint, waves rolling ACROSS the four
strips) rather than as shapes moving up and down a strip. Hue also handles only about
10 light updates per second in total, so updates are ~0.6 s apart with smooth fades.

Run - same pipe as V1:
    cmd /d /c 'python -u code\\ant_hr_to_json.py 2>NUL | python -u code\\pulse_relay_show_v2.py --config code\\pulse_relay_config.json --hue --csv --quiet'

Rehearse with no hardware:
    python -u code/fake_openant_hr.py --devices 51861,51950,52001,52002 --scenario show --seconds 900 --speed 6 | python -u code/ant_hr_to_json.py --stdin 2>/dev/null | python -u code/pulse_relay_show_v2.py --preview --time-scale 6
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import integrated_prototype as ip  # noqa: E402  message parsing + CSV helpers
from pulse_relay_show_v1 import (  # noqa: E402
    HueOut, blend, clamp, hex_to_rgb, pearson, rgb_to_xy,
)

V2_DEFAULTS: dict[str, Any] = {
    "bridge_ip": None,
    "visitors": [
        {"name": "Visitor 1", "light": "Strip 1", "device_id": None,
         "palette": ["#D92DFF", "#FF2DFB", "#FF2DD1", "#FF2DA7", "#FF2D7D"]},
        {"name": "Visitor 2", "light": "Strip 2", "device_id": None,
         "palette": ["#1400FF", "#4700FF", "#7A00FF", "#AD00FF", "#E000FF"]},
        {"name": "Visitor 3", "light": "Strip 3", "device_id": None,
         "palette": ["#FF7700", "#FFAA00", "#FFDD00", "#EEFF00", "#BBFF00"]},
        {"name": "Visitor 4", "light": "Strip 4", "device_id": None,
         "palette": ["#00FFD0", "#00FBFF", "#00C8FF", "#0095FF", "#0062FF"]},
    ],
    "group_light": None,              # e.g. "Paper Lamp" (optional 5th light)
    "wave_colors": ["#1B2A8F", "#4B1C7A", "#6E1235"],  # deep blue, purple, red
    "baseline_seconds": 45,
    "full_scale_bpm": 25,             # +25 bpm above own baseline = fully lively
    "min_brightness": 70,
    "max_brightness": 230,
    "idle_brightness": 25,
    "fade_in_seconds": 20,            # "coming to life"
    "flutter_period_calm": 9.0,       # seconds per palette drift cycle when calm
    "flutter_period_excited": 3.5,    # fastest it ever gets (never frantic)
    "shimmer_depth": 0.18,            # +/- brightness shimmer at most
    "hrv_window_seconds": 30,
    "sync_window_seconds": 60,
    "sync_low": 0.3,
    "sync_high": 0.7,
    "pair_max_tint": 0.35,            # how much of a partner's colour a strip takes on
    "particle_rate": 0.35,            # partner-colour "particles" per second at full sync
    "group_threshold": 0.55,          # mean pairwise r for the ocean wave
    "wave_period_seconds": 14,
    "wave_strength": 0.5,
    "stale_seconds": 10,
    "update_interval": 0.6,
}


@dataclass
class Wearer:
    name: str
    palette: list
    light: Any
    device_id: str | None
    index: int
    last_seen: float = -1e9
    first_seen: float | None = None
    smooth_bpm: float | None = None
    baseline: float | None = None
    baseline_samples: list = field(default_factory=list)
    history: deque = field(default_factory=lambda: deque(maxlen=900))   # (t, bpm) 1 Hz
    ibis: deque = field(default_factory=lambda: deque(maxlen=300))      # (t, ibi_ms)
    phase: float = field(default_factory=lambda: random.random() * 10)  # flutter phase
    shimmer_phase: float = field(default_factory=lambda: random.random() * 10)
    particle_until: float = -1.0
    particle_rgb: tuple = (1.0, 1.0, 1.0)

    @property
    def own(self):
        return self.palette[len(self.palette) // 2]

    def active(self, now: float, stale: float) -> bool:
        return self.device_id is not None and now - self.last_seen <= stale

    def reset(self):
        self.baseline, self.baseline_samples, self.smooth_bpm = None, [], None
        self.first_seen = None
        self.history.clear()
        self.ibis.clear()

    def rmssd(self, now: float, window: float) -> float | None:
        vals = [ibi for (t, ibi) in self.ibis if now - t <= window]
        if len(vals) < 8:
            return None
        diffs = [(b - a) ** 2 for a, b in zip(vals, vals[1:])]
        return math.sqrt(fmean(diffs))


def palette_color(palette: list, pos: float):
    """Smoothly interpolate around a looped palette; pos in [0, 1)."""
    n = len(palette)
    x = (pos % 1.0) * n
    i = int(x)
    frac = x - i
    t = 0.5 - 0.5 * math.cos(math.pi * frac)  # ease, no hard steps
    return blend(palette[i % n], palette[(i + 1) % n], t)


def derive_palette(hex_color: str, spread_deg: float = 24.0) -> list:
    """5 neighbouring hues with the same lightness/saturation (similar contrast)."""
    import colorsys
    r, g, b = hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    out = []
    for d in (-spread_deg, -spread_deg / 2, 0, spread_deg / 2, spread_deg):
        rr, gg, bb = colorsys.hls_to_rgb((h + d / 360) % 1, l, s)
        out.append("#%02X%02X%02X" % (round(rr * 255), round(gg * 255), round(bb * 255)))
    return out


def load_config(path: str | None) -> dict:
    cfg = json.loads(json.dumps(V2_DEFAULTS))
    if path:
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
        for k, v in user.items():
            if k.startswith("_"):
                continue
            if k == "visitors":
                merged = []
                for i, uv in enumerate(v):
                    base = dict(cfg["visitors"][i]) if i < len(cfg["visitors"]) else {}
                    base.update(uv)
                    if "palette" not in uv and "color" in uv:
                        base["palette"] = derive_palette(uv["color"])  # V1-style config
                    merged.append(base)
                cfg["visitors"] = merged
            else:
                cfg[k] = v
    return cfg


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Pulse Relay V2: palettes, flutter, HRV, pairs, ocean wave")
    p.add_argument("--config")
    p.add_argument("--ip")
    p.add_argument("--hue", action="store_true", help="Send to the real Hue lights")
    p.add_argument("--preview", action="store_true", help="Coloured bars in the terminal")
    p.add_argument("--quiet", action="store_true",
                   help="Print only a short status line every 10 s (lighter on old PCs)")
    p.add_argument("--csv", action="store_true")
    p.add_argument("--csv-dir", default=None)
    p.add_argument("--duration", type=float, default=None, help="Stop after N seconds")
    p.add_argument("--time-scale", type=float, default=1.0, help="Rehearsal speed-up only")
    return p


def main() -> int:
    args = build_parser().parse_args()
    cfg = load_config(args.config)
    stale = cfg["stale_seconds"]

    wearers = [
        Wearer(name=v["name"], palette=[hex_to_rgb(c) for c in v["palette"]], light=v["light"],
               device_id=str(v["device_id"]) if v.get("device_id") else None, index=i)
        for i, v in enumerate(cfg["visitors"])
    ]
    fixed_ids = {w.device_id for w in wearers if w.device_id}
    wave_cols = [hex_to_rgb(c) for c in cfg["wave_colors"]]

    hue = HueOut(args.ip or cfg.get("bridge_ip")) if args.hue else None
    light_ids = [hue.resolve(w.light) for w in wearers] if hue else [None] * len(wearers)
    lamp_id = hue.resolve(cfg["group_light"]) if (hue and cfg.get("group_light")) else None
    if os.name == "nt":
        os.system("")

    csv_files, state_writer, ibi_writer = [], None, None
    if args.csv:
        h1, state_writer, p1 = ip.create_csv_writer(
            args.csv_dir, prefix="show_v2_log",
            fieldnames=["t_s", "visitor", "device_id", "bpm", "baseline", "rmssd_ms",
                        "liveliness", "brightness", "pair_tint", "group_r", "wave"])
        h2, ibi_writer, p2 = ip.create_csv_writer(args.csv_dir, prefix="ibi_log",
                                                  fieldnames=ip.IBI_FIELDNAMES)
        csv_files = [h1, h2]
        print(f"[csv] show state -> {p1}\n[csv] beats -> {p2}", flush=True)

    print("=" * 56 + "\n Pulse Relay light show - V2\n" + "=" * 56, flush=True)
    for w in wearers:
        print(f"[slot] {w.name} -> light {w.light!r}", flush=True)
    print("[input] waiting for heart-rate data...", flush=True)

    start = time.monotonic()
    clock = lambda: (time.monotonic() - start) * args.time_scale  # noqa: E731
    last_sample = last_update = last_status = -1e9
    pair_level: dict[tuple[int, int], float] = {}
    group_level = 0.0

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
                w = next((x for x in wearers if x.device_id == beat.device_id), None)
                if w is not None and beat.ibi_ms is not None and beat.quality in ("ok", "recovered"):
                    w.ibis.append((now, beat.ibi_ms))
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
                w = next((x for x in wearers if x.device_id == r.device_id), None)
                if w is None and r.device_id not in fixed_ids:
                    w = next((x for x in wearers if x.device_id is None), None)
                    if w is not None:
                        w.device_id = r.device_id
                        print(f"[assign] monitor {r.device_id} -> {w.name}", flush=True)
                if w is None:
                    continue
                if w.first_seen is None:
                    w.first_seen = now
                w.last_seen = now
                w.smooth_bpm = r.bpm if w.smooth_bpm is None else 0.7 * w.smooth_bpm + 0.3 * r.bpm

            # ---- 1 Hz bookkeeping: baselines, history, leaving wearers
            if now - last_sample >= 1.0:
                last_sample = now
                for w in wearers:
                    if w.active(now, stale) and w.smooth_bpm is not None:
                        w.history.append((now, w.smooth_bpm))
                        if w.baseline is None:
                            w.baseline_samples.append(w.smooth_bpm)
                            if len(w.baseline_samples) >= cfg["baseline_seconds"]:
                                w.baseline = sorted(w.baseline_samples)[len(w.baseline_samples) // 3]
                                print(f"[baseline] {w.name}: {w.baseline:.1f} bpm", flush=True)
                    elif not w.active(now, stale) and (w.first_seen is not None):
                        print(f"[leave] {w.name} stopped sending", flush=True)
                        w.reset()

            dt_real = cfg["update_interval"]
            if now - last_update < dt_real * args.time_scale:
                continue
            dt = now - last_update if last_update > 0 else dt_real
            last_update = now

            active = [w for w in wearers if w.active(now, stale)]

            # ---- pairwise synchrony (correlation of HR changes over the window)
            win = cfg["sync_window_seconds"]
            series = {w.index: [b for (t, b) in w.history if now - t <= win] for w in active}
            rs = []
            for a in range(len(active)):
                for b in range(a + 1, len(active)):
                    wa, wb = active[a], active[b]
                    sa, sb = series[wa.index], series[wb.index]
                    n = min(len(sa), len(sb))
                    r = pearson(sa[-n:], sb[-n:]) if n >= 10 else None
                    key = (wa.index, wb.index)
                    target = 0.0 if r is None else clamp(
                        (r - cfg["sync_low"]) / (cfg["sync_high"] - cfg["sync_low"]), 0, 1)
                    # builds slowly (~20 s), fades a little faster
                    rate = 0.05 if target > pair_level.get(key, 0) else 0.08
                    pair_level[key] = pair_level.get(key, 0) + (target - pair_level.get(key, 0)) * rate * dt / dt_real
                    if r is not None:
                        rs.append(r)
            for key in list(pair_level):
                if not any(w.index == key[0] for w in active) or not any(w.index == key[1] for w in active):
                    pair_level[key] *= 0.9
            group_r = fmean(rs) if rs else None
            g_target = 1.0 if (group_r is not None and len(active) >= 2
                               and group_r >= cfg["group_threshold"]
                               and min(rs) >= cfg["sync_low"]) else 0.0
            group_level += (g_target - group_level) * 0.04 * dt / dt_real

            # ---- render each strip
            bars, lamp_mix = [], []
            for w, lid in zip(wearers, light_ids):
                if not w.active(now, stale):
                    rgb, bri, live, tint, rmssd = w.own, cfg["idle_brightness"], 0.0, 0.0, None
                else:
                    ref = w.baseline if w.baseline is not None else (w.smooth_bpm or 0)
                    live = clamp(((w.smooth_bpm or ref) - ref) / cfg["full_scale_bpm"], 0, 1)
                    rmssd = w.rmssd(now, cfg["hrv_window_seconds"])
                    calm = 0.5 if rmssd is None else clamp((rmssd - 15) / 45, 0, 1)

                    # flutter: drift through the palette; quicker when lively, slower when calm
                    period = cfg["flutter_period_calm"] + (cfg["flutter_period_excited"] - cfg["flutter_period_calm"]) * live
                    period *= 1 + 0.3 * calm
                    w.phase += dt / period
                    w.shimmer_phase += dt / (period * 0.6)
                    rgb = palette_color(w.palette, w.phase / len(w.palette))

                    # pairs: pull in partners' colours, keep own identity
                    partners = [(pair_level.get(tuple(sorted((w.index, u.index))), 0.0), u)
                                for u in active if u is not w]
                    tint = max((lvl for lvl, _ in partners), default=0.0)
                    if partners and tint > 0.02:
                        total = sum(l for l, _ in partners) or 1.0
                        mix = [0.0, 0.0, 0.0]
                        for lvl, u in partners:
                            for k in range(3):
                                mix[k] += u.own[k] * lvl / total
                        rgb = blend(rgb, tuple(mix), cfg["pair_max_tint"] * tint)
                        # occasional "particle" of a partner's colour drifting in
                        if now >= w.particle_until and random.random() < cfg["particle_rate"] * tint * dt:
                            lvl, u = max(partners, key=lambda p: p[0] * random.random())
                            w.particle_rgb, w.particle_until = u.own, now + 1.2
                    if now < w.particle_until:
                        rgb = blend(rgb, w.particle_rgb, 0.45)

                    # group: slow ocean wave rolling across the strips
                    wave = 0.0
                    if group_level > 0.02:
                        ph = 2 * math.pi * (now / cfg["wave_period_seconds"] - w.index / max(1, len(wearers)))
                        s = 0.5 + 0.5 * math.sin(ph)
                        wave = group_level * s
                        wave_rgb = palette_color(wave_cols, now / (cfg["wave_period_seconds"] * 3))
                        rgb = blend(rgb, wave_rgb, cfg["wave_strength"] * wave)

                    # brightness: heart rate + shimmer, fading in for new wearers
                    shimmer = cfg["shimmer_depth"] * (1 - 0.4 * calm) * math.sin(2 * math.pi * w.shimmer_phase)
                    level = cfg["min_brightness"] + live * (cfg["max_brightness"] - cfg["min_brightness"])
                    level *= (1 + shimmer) * (1 + 0.15 * (wave - 0.5 * group_level))
                    fade = clamp((now - (w.first_seen or now)) / cfg["fade_in_seconds"], 0, 1)
                    bri = round(clamp(cfg["idle_brightness"] + (level - cfg["idle_brightness"]) * fade, 1, 254))
                    if tint > 0.3:
                        lamp_mix.append(w.own)

                if hue is not None:
                    hue.set(lid, rgb_to_xy(rgb), bri, dt_real)
                if args.preview:
                    r8, g8, b8 = (int(255 * c * (0.35 + 0.65 * bri / 254)) for c in rgb)
                    lbl = f"{w.smooth_bpm:5.1f} bpm" if w.active(now, stale) and w.smooth_bpm else "  waiting"
                    extra = "" if not w.active(now, stale) else (
                        f"  HRV {rmssd:4.0f} ms" if rmssd else "  HRV  ...") + (f"  pair {tint:.2f}" if tint > 0.02 else "")
                    bars.append(f"\033[48;2;{r8};{g8};{b8}m{' ' * 16}\033[0m {w.name[:10]:<10} {lbl}{extra}")
                if state_writer is not None and w.active(now, stale):
                    state_writer.writerow({
                        "t_s": round(now, 1), "visitor": w.name, "device_id": w.device_id,
                        "bpm": round(w.smooth_bpm or 0, 1),
                        "baseline": round(w.baseline, 1) if w.baseline else "",
                        "rmssd_ms": round(rmssd, 1) if rmssd else "",
                        "liveliness": round(live, 3), "brightness": bri,
                        "pair_tint": round(tint, 3),
                        "group_r": "" if group_r is None else round(group_r, 3),
                        "wave": round(group_level, 3)})

            # optional 5th light: the colours of whoever is in sync
            if hue is not None and lamp_id is not None:
                if lamp_mix:
                    mixed = tuple(fmean(c[k] for c in lamp_mix) for k in range(3))
                    hue.set(lamp_id, rgb_to_xy(mixed), round(60 + 150 * min(1, len(lamp_mix) / 4)), dt_real)
                else:
                    hue.set(lamp_id, rgb_to_xy((1.0, 0.75, 0.5)), 30, dt_real)

            for fh in csv_files:
                fh.flush()

            gtxt = "n/a" if group_r is None else f"{group_r:+.2f}"
            status = f"[show] t={now:6.0f}s wearers={len(active)} group_r={gtxt} wave={group_level:.2f}"
            if args.preview:
                print("\n".join(bars) + f"\n{status}\n", flush=True)
            elif not args.quiet or now - last_status >= 10 * args.time_scale:
                last_status = now
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


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())
