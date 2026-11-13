# Pulse Relay Light Show — Setup Guide (Gallery Opening)

There are two versions. They share the same setup, config file and data logs:

- **V1 — `pulse_relay_show_v1.py`:** simple and steady. Described below.
- **V2 — `pulse_relay_show_v2.py`:** the "jellyfish" version from the Oct 27 / Nov 3 meetings, with a 5-colour palette per person, gentle flutter, HRV, pair colour exchange and the group ocean wave. See section 4.

Design beats: `notes/ANIMATION_BEATS.md`. Ideas to test later: `notes/THINGS_TO_TRY.md`.

**V1 — what it does:** 4 heart-rate monitors → 4 Hue light strips (one per visitor) + a shared group colour.

- **Colour:** each visitor has their own colour from the HRP swatch: magenta `#FF2DD1`, violet `#7A00FF`, yellow `#FFDD00`, cyan `#00C8FF`.
- **Brightness:** follows each person's heart rate relative to *their own* resting level. The first ~45 s set the baseline, which gives a dim glow. Up to +20 bpm, the strip gets brighter. It never goes fully dark.
- **Togetherness:** when the wearers' heart rates **rise and fall together**, all strips blend toward the **group colour**, green `#39DF14`. When they drift apart, each strip returns to its own colour. The group colour is based on He et al. (2026): heart-rate synchrony = correlation of heart-rate changes over time, not "same BPM".
- **Pace:** everything fades over about a second, with no flashing. Togetherness builds and fades over tens of seconds.
- **Waiting:** a strip with no wearer rests in a dim glow of its colour. When a monitor is handed to a new person, their baseline is learned again.
- **Logging:** `--csv` writes the beat-to-beat log (`ibi_log_*.csv`) and the show state (`show_log_*.csv`).

## 1. One-time setup (Windows, project folder, `.venv` active)

```powershell
git pull origin main
python code\pulse_relay_show_v1.py --ip <GALLERY_BRIDGE_IP> --list-lights
```

Open `code\pulse_relay_config.json`:

- Set `"bridge_ip"`.
- Replace `"Strip 1"` … `"Strip 4"` with the four strip names (or numbers) from the list.
- Optional: set each `"device_id"` to a monitor's ID, so each monitor always maps to the same strip. If you leave them `null`, monitors are assigned in the order they appear, and the terminal prints `[assign] monitor … -> Visitor …`.
- Swap colours here if needed. Only the hex codes change.

## 2. Run the show

```powershell
cmd /d /c 'python -u code\ant_hr_to_json.py 2>NUL | python -u code\pulse_relay_show_v1.py --config code\pulse_relay_config.json --hue --csv'
```

It runs until you press Ctrl+C. `2>NUL` hides the sensor debug lines, which keeps the terminal readable and lighter on older PCs. Optional: `--duration 720` stops it after 12 minutes.

What you should see in the terminal:

- `[assign]` when each monitor appears
- `[baseline]` after about 45 s per person
- `[sync] wearers=… r=… blend=…` every second. `r` is how much the hearts move together (−1 to 1), and `blend` is how far the strips have moved toward the group colour.

## 3. Rehearse with no hardware (any computer)

```bash
python -u code/fake_openant_hr.py --devices 51861,51950,52001,52002 --scenario show --seconds 600 --speed 6 | python -u code/ant_hr_to_json.py --stdin 2>/dev/null | python -u code/pulse_relay_show_v1.py --preview --time-scale 6
```

`--preview` draws the four strips as coloured bars in the terminal. The simulated visitors spend ~90 s "apart", then ~80 s sharing a rhythm. You'll see the bars blend toward green and back.

## Tuning (in the config, no code changes)

| Setting | Default | Effect |
|---|---|---|
| `full_scale_bpm` | 20 | Smaller = brighter reactions to small changes |
| `min_brightness` / `idle_brightness` | 40 / 25 | Floor brightness for a wearer / an empty strip |
| `sync_window_seconds` | 60 | Longer = steadier but slower togetherness (the paper used 5 min) |
| `sync_low` / `sync_high` | 0.3 / 0.7 | Correlation range that maps to "no blend" → "full blend" |
| `sync_max_blend` | 0.85 | How far strips move toward green (1.0 = all fully green) |
| `update_interval` | 1.0 | Seconds between Hue commands and fades (Hue handles ~10 commands/s in total) |

## Known limits

- Optical arm bands report heart-rate changes 10–20 s late, so the lights follow the body with a delay.
- Togetherness needs at least 2 wearers and about 10 s of data. With strangers, expect less synchrony than with friends; the paper found familiar pairs synchronise more.
- Loud, noisy moments, like the band playing, may show *less* togetherness. The paper found noise reduced synchrony.

## 4. V2 — the "jellyfish" version

Same setup and config. Just change the script name. `--quiet` prints one status line every 10 s instead of every update:

```powershell
cmd /d /c 'python -u code\ant_hr_to_json.py 2>NUL | python -u code\pulse_relay_show_v2.py --config code\pulse_relay_config.json --hue --csv --quiet'
```

Rehearse without hardware:

```bash
python -u code/fake_openant_hr.py --devices 51861,51950,52001,52002 --scenario show --seconds 900 --speed 6 | python -u code/ant_hr_to_json.py --stdin 2>/dev/null | python -u code/pulse_relay_show_v2.py --preview --time-scale 6
```

What V2 adds:

- **Palette per person:** five neighbouring colours (`"palette"` in the config) that the strip drifts through slowly.
- **Flutter:** quicker when heart rate is up, slower when calm, never faster than one drift every ~3.5 s.
- **HRV:** heart-rate variability from the beat-to-beat data. More variability gives a softer, slower shimmer. The preview shows it as `HRV xx ms`.
- **Pairs:** two people in sync take on a tint of each other's colour, plus occasional "particles" of the partner's colour. The preview shows `pair 0.xx`. Each strip keeps its own colour.
- **Group:** when everyone is in sync, a slow ocean wave of deep blue, purple and red rolls across the four strips (`wave` in the status line).
- **Coming to life:** a new wearer's strip fades in over ~20 s.
- **Paper lamp (optional):** set `"group_light"` to its Hue name.

Hardware note: Hue Lightstrip Plus shows one colour per strip at a time, so V2's effects play out over time and across the strips. Hue handles ~10 updates/s in total, so V2 updates every 0.6 s with smooth fades.

V2 settings (add them to the config to change them): `full_scale_bpm` (25), `min_brightness` (70), `max_brightness` (230), `fade_in_seconds` (20), `flutter_period_calm` (9), `flutter_period_excited` (3.5), `shimmer_depth` (0.18), `pair_max_tint` (0.35), `particle_rate` (0.35), `group_threshold` (0.55), `wave_period_seconds` (14), `wave_strength` (0.5), `update_interval` (0.6).

