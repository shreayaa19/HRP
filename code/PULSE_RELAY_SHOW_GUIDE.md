# Pulse Relay Light Show — Setup Guide (Gallery Opening)

**What it does:** 4 heart-rate monitors → 4 Hue light strips (one per visitor) + a shared group colour.

- **Colour:** each visitor has their own colour from the HRP swatch: magenta `#FF2DD1`, violet `#7A00FF`, yellow `#FFDD00`, cyan `#00C8FF`.
- **Brightness:** follows each person's heart rate relative to *their own* resting level. The first ~45 s set the baseline, which gives a dim glow. Up to +20 bpm, the strip gets brighter. It never goes fully dark.
- **Togetherness:** when the wearers' heart rates **rise and fall together**, all strips blend toward the **group colour**, green `#39DF14`. When they drift apart, each strip returns to its own colour. The group colour is based on He et al. (2026): heart-rate synchrony = correlation of heart-rate changes over time, not "same BPM".
- **Pace:** everything fades over about a second, with no flashing. Togetherness builds and fades over tens of seconds.
- **Waiting:** a strip with no wearer rests in a dim glow of its colour. When a monitor is handed to a new person, their baseline is learned again.
- **Logging:** `--csv` writes the beat-to-beat log (`ibi_log_*.csv`) and the show state (`show_log_*.csv`).

## 1. One-time setup (Windows, project folder, `.venv` active)

```powershell
git pull origin main
python code\pulse_relay_show.py --ip <GALLERY_BRIDGE_IP> --list-lights
```

Open `code\pulse_relay_config.json`:

- Set `"bridge_ip"`.
- Replace `"Strip 1"` … `"Strip 4"` with the four strip names (or numbers) from the list.
- Optional: set each `"device_id"` to a monitor's ID, so each monitor always maps to the same strip. If you leave them `null`, monitors are assigned in the order they appear, and the terminal prints `[assign] monitor … -> Visitor …`.
- Swap colours here if needed. Only the hex codes change.

## 2. Run the show

```powershell
cmd /d /c 'python -u code\ant_hr_to_json.py | python -u code\pulse_relay_show.py --config code\pulse_relay_config.json --hue --csv'
```

Add `--duration 5400` for a 90-minute session. Stop with Ctrl+C.

What you should see in the terminal:

- `[assign]` when each monitor appears
- `[baseline]` after about 45 s per person
- `[sync] wearers=… r=… blend=…` every second. `r` is how much the hearts move together (−1 to 1), and `blend` is how far the strips have moved toward the group colour.

## 3. Rehearse with no hardware (any computer)

```bash
python -u code/fake_openant_hr.py --devices 51861,51950,52001,52002 --scenario show --seconds 600 --speed 6 | python -u code/ant_hr_to_json.py --stdin | python -u code/pulse_relay_show.py --preview --time-scale 6
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
