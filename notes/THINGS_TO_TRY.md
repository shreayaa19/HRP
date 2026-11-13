# Pulse Relay — Things to Try

A running list so we don't forget ideas, without building lots of script versions. Run V1 or V2 as they are; move an item to "Done" once we've tried it in the gallery and written down what we saw.

## To try

1. **Timed sessions (12 min).** One command starts a 12-minute session for a rotation. At the end, a gentle closing animation plays, the strips settle to a dim glow, and the script stops. That way the facilitator can see from across the room that it's time to swap bands. Partly there already: `--duration 720` stops it, but there's no closing animation yet.
2. **Different colours.** Swap palettes in `code/pulse_relay_config.json`, e.g. Jeremy's "reddish-pink" for one visitor, or include red-orange. Check that all four strips look equally bright from across the room.
3. **Sensitivity / "canvas" range.** `full_scale_bpm` is 25 in V2 (20 in V1). Try 20–30 with real people on the mat. If nothing changes, lower it; if it's always maxed, raise it. Then replace the guess with real data from the session logs (mean, median and spread of heart rate during the mat games).
4. **Synchrony window.** `sync_window_seconds` is 60 (the paper used 5 minutes). Try 45 and 90 and see which feels responsive without flickering between "together" and "apart".
5. **Particle frequency.** `particle_rate` (V2) controls how often a partner's colour "drifts in". Find the level that feels like a little reward and not a distraction.
6. **Ocean wave.** Try `wave_period_seconds` between 10 and 20, and `wave_strength` between 0.3 and 0.7. Jeremy's image: a big, slow ocean swell, not a ripple.
7. **Paper lamp (5th light).** Set `"group_light"` to the lamp's name. It glows with the colours of whoever is in sync. Try it in the dorm area.
8. **Long runs.** Run 10 minutes with the terminal quiet (`--quiet`), check the CSV file size, then estimate for 90 minutes to 3 hours.
9. **Band colour → strip.** Write each monitor's ID next to its band colour (e.g. yellow band = monitor 46835x) and put it in `device_id`, so each band always drives the same strip.
10. **Along-the-strip animation** (ball floating up and down, gravity with the controller end on the floor, lava lamp). Hue Lightstrip Plus shows one colour per strip, so this needs Hue Gradient strips (several zones) or the DMX/LED-grid setup. Worth testing once the longer strips are connected.
11. **Two "balls" (heart rate + HRV).** In V2, HRV currently shapes the shimmer. With segment control, it could become its own floating shape.

## Done

- *(add date, what we tried, what we saw)*
