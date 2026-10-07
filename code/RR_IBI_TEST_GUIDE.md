# R-R / IBI Capture — Test Guide

**What it does:** `ant_hr_to_json.py` reads the strap's own beat timing (ANT+ *heart beat event time* and *beat count*) and computes the R-R interval in milliseconds for every heartbeat. It does **not** estimate intervals from BPM. `integrated_prototype.py --csv` writes `outputs/hr_logs/ibi_log_<timestamp>.csv`, with **one row per heartbeat**, next to the usual `hr_log`. Hue and OSC are still driven by BPM.

### Update (Oct 7)

- **`NA` instead of blank:** when a beat has no usable interval, `ibi_ms` now shows `NA` in the CSV and the terminal. In the terminal it is also printed in orange.
- **Fewer missed beats:** most straps also send the *previous* beat's time (ANT+ data page 4). When one radio packet is lost, the program now uses that to rebuild the lost interval. These rows are marked `quality = recovered`. In testing with 30% of packets dropped, this cut beats without an interval from 24 to 2.
- **Warnings only above a threshold:** each beat row is still flagged, but the terminal shows an orange `[ibi-warning]` only when a strap misses more than **5%** of its last ~60 beats. Change it with `--missed-warn-pct 10`.
- **Summary at the end:** each strap gets an `[ibi-summary]` line with beats, % without an interval, and `OK` or `CHECK`.
- **Single-clock beat time:** a new `beat_time_ms` column estimates when each beat *happened* on the computer's clock, which all straps share. Use it to line up different people.
- **Timed sessions:** `--duration 600` stops automatically after 10 minutes. Ctrl+C still works.

## 1. Hardware-free check (any computer)

```bash
python -u code/fake_openant_hr.py --fast | python -u code/ant_hr_to_json.py --stdin | python -u code/integrated_prototype.py --csv --dry-run
```

Expected: `[beat] ... quality=ok` lines, then `[ibi-summary] ... -> OK` for both straps.

To see the dropout handling: add `--drop 0.3` to the fake script, or `--drop 0.3 --no-page4` to see warnings and `NA` rows.

## 2. Real straps (Jeremy's Windows setup, from `HRP_shreayaa` with `.venv` active)

```powershell
cmd /d /c 'python -u code\ant_hr_to_json.py | python -u code\integrated_prototype.py --group Office --ip 192.168.88.48 --hue --csv --mapping smooth --window 3 --interval 1 --duration 600'
```

- At startup, look for `[ibi-csv] logging beat-to-beat R-R intervals to ...`.
- While it runs, expect `[beat]` lines, roughly one per heartbeat per strap.
- At the end, read the `[ibi-summary]` lines. `CHECK` means more than 5% of that strap's beats had no interval: move the dongle closer or into clear line of sight, and check strap contact.
- If there are no `recovered` rows at all while `missed_beats` rows appear, the strap may not send page 4. Send Shreayaa a few `[raw]` lines.

## 3. What to check in `ibi_log_*.csv`

| Check | Pass if |
|---|---|
| One row per beat | About 60–100 rows per strap per minute at rest |
| Plausible values | `ibi_ms` mostly 600–1000 at rest; all ok rows between 300 and 2000 |
| Real variation | `ibi_ms` changes from row to row |
| Agrees with BPM | 60000 ÷ mean(`ibi_ms`) ≈ mean(`bpm_reported`) |
| Rollover handled | No negative or huge values when `beat_event_time` wraps past 65535 |
| Data quality | `[ibi-summary]` says `OK` (5% or less without an interval) |

## CSV columns

| Column | Meaning |
|---|---|
| `timestamp` | Wall-clock time (UTC) the beat message was received |
| `beat_time_ms` | **Estimated time the beat happened**, on the computer's shared monotonic clock (ms). Use this to align people |
| `t_mono_ms` | Time the message was *received* on the same clock (up to about 250 ms after the beat) |
| `device_id` | Strap ID (e.g. 51861) |
| `beat_count` | Strap's beat counter (0–255, wraps) |
| `beat_event_time` | Strap's own beat time in 1/1024 s ticks (0–65535, wraps every 64 s) |
| `ibi_ms` | **R-R interval** since the previous beat, or `NA` if it couldn't be measured |
| `gap_ms` / `beats_elapsed` | Time and number of beats since the previous known beat (more than 1 beat when beats were missed) |
| `bpm_reported` | The strap's own BPM |
| `quality` | `ok`, `recovered` (rebuilt from page 4, exact), `missed_beats` (`ibi_ms = NA`), or `out_of_range` (outside 300–2000 ms, kept but flagged) |

**Orange in a spreadsheet:** a CSV can't store colors. In Excel or Google Sheets, select the `ibi_ms` column and add a conditional-formatting rule: "Text is exactly `NA`" → orange fill.

## Known limits

- `beat_time_ms` settles over the first ~30 s of a session. After that, simulated tests put it within about 10–20 ms of the true beat (vs. up to ~250 ms or more for `t_mono_ms`). Leave out the first 30 s when computing synchrony.
- `ibi_ms` comes from the strap's own clock and is precise to about 1 ms.
- After more than 60 s without a beat from a strap, its stream restarts. The first beat after that has no interval, because the 64 s counter may have wrapped.
