# R-R / IBI Capture — Test Guide

**What changed:** `ant_hr_to_json.py` now reads the strap's own beat timing (ANT+ *heart beat event time* and *beat count*). For every new heartbeat it computes the R-R interval in milliseconds. It does **not** estimate the interval from BPM. `integrated_prototype.py --csv` now writes a second file, `outputs/hr_logs/ibi_log_<timestamp>.csv`, with **one row per heartbeat**. Hue and OSC are still driven by BPM exactly as before.

The `int(group_id)` fix from the 9/9 session is also included.

## 1. Hardware-free check (any computer)

```bash
python -u code/fake_openant_hr.py --fast | python -u code/ant_hr_to_json.py --stdin | python -u code/integrated_prototype.py --csv --dry-run
```

Expected: `[beat] device=... ibi_ms=... quality=ok` lines, and a final `[ibi] beats logged: N (ok=N)`.

## 2. Real straps (Jeremy's Windows setup, from `HRP_shreayaa` with `.venv` active)

Use the same command as before:

```powershell
cmd /d /c 'python -u code\ant_hr_to_json.py | python -u code\integrated_prototype.py --group Office --ip 192.168.88.48 --hue --csv --mapping smooth --window 3 --interval 1'
```

- Look for `[ibi-csv] logging beat-to-beat R-R intervals to ...` at startup.
- Look for `[beat]` lines, roughly one per heartbeat per strap.
- If you see `[ibi-warning] ... no beat_time/beat_count`, copy a few `[raw]` lines and send them to Shreayaa.
- Run for 5–10 minutes, then press Ctrl+C. The last line summarizes beats by quality.

## 3. What to check in `ibi_log_*.csv`

| Check | Pass if |
|---|---|
| One row per beat | Around 60–100 rows per strap per minute at rest |
| Plausible values | `ibi_ms` mostly 600–1000 at rest; all ok rows are between 300 and 2000 |
| Real beat-to-beat variation | `ibi_ms` changes from row to row; a constant value means something is wrong |
| Agrees with BPM | 60000 ÷ mean(`ibi_ms`) ≈ mean(`bpm_reported`) for that strap |
| Rollover handled | No negative or huge values when `beat_event_time` wraps past 65535 |
| Dropouts visible | Lost radio packets show as `quality = missed_beats`, not as a wrong interval |

## CSV columns

| Column | Meaning |
|---|---|
| `timestamp` | Computer wall-clock time (UTC) when the beat was received |
| `t_mono_ms` | Computer monotonic clock in ms. It is shared by all straps, so use it to align people |
| `device_id` | Strap ID (e.g. 51861) |
| `beat_count` | Strap's beat counter (0–255, wraps) |
| `beat_event_time` | Strap's beat time in 1/1024 s ticks (0–65535, wraps every 64 s) |
| `ibi_ms` | **R-R interval** since the previous beat. Blank if beats were missed |
| `gap_ms` / `beats_elapsed` | Time and number of beats since the last received beat. When 2 or more beats were missed, these cover all of them |
| `bpm_reported` | The strap's own BPM at that beat |
| `quality` | `ok`, `missed_beats`, or `out_of_range` (outside 300–2000 ms; kept but flagged) |

## Known limits

- `timestamp` and `t_mono_ms` record when the computer *received* the beat. Straps broadcast about 4 times a second, so these can lag the true beat by up to about 250 ms. `ibi_ms` comes from the strap's own clock and is precise to about 1 ms. For cross-person synchrony, align people on `t_mono_ms`, allowing for that lag.
- After more than 60 s without a beat from a strap, its stream restarts. The first beat after that has no interval, because the 64 s counter may have wrapped.
