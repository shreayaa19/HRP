# Pulse Relay — Animation Beats (design guidelines)

Taken from the Oct 27 and Nov 3 design meetings (Jeremy and Shreayaa). Each beat is a moment in the visitor's experience, with what the light does and which script handles it today.

**Overall feel:** deep-sea jellyfish and a spa bubble wall. Gentle, iridescent, never frantic, never a disco light. Nobody should look like an outlier, especially a nervous visitor.

| # | Beat | What the visitor experiences | What the light does | Status |
|---|---|---|---|---|
| 0 | **Waiting** | Mat is empty; strips are on the wall | Each strip rests in a dim glow of its colour. Never fully dark | V1, V2 |
| 1 | **Putting on the bands** | Facilitator fits four colour-coded arm bands and starts the session | Nothing sudden. Each strip slowly **comes to life** over ~20 s as its band starts sending | V2 (V1 just starts dim) |
| 2 | **"That's me"** | The facilitator invites people to notice that their heart drives their strip (e.g. a short game like "don't touch the ground") | Own palette (5 related colours) **flutters** slowly. Higher heart rate = brighter, livelier, a bit quicker, but capped so it never gets frantic | V2 (V1: one colour, brightness only) |
| 3 | **Calm vs. stirred** | People settle, talk, or move | Second data channel: **HRV** (beat-to-beat variability). More variability, usually calmer, gives a slower, deeper, softer shimmer. Less variability gives a lighter, quicker shimmer | V2 |
| 4 | **Two hearts align** | Two people's heart rates start rising and falling together | Their strips **pull in each other's colours**: occasional "particles" of the partner's colour drift in, and a gentle tint builds the longer they stay in sync. Each keeps their own colour | V2 (V1: blends toward shared green) |
| 5 | **The group connects** | Everyone is moving together | A slow, big **ocean wave** of deep blue, purple and red rolls across all four strips, under each person's own colour. Rewarding, like a swell, not a champagne pop | V2 (V1: all strips blend green) |
| 6 | **Drifting apart** | People's rhythms separate again | Tints and wave fade back gently over tens of seconds. No "failure" signal | V1, V2 |
| 7 | **Leaving / swapping bands** | Band removed, cleaned, given to the next person | That strip fades to its waiting glow. The next wearer gets a fresh baseline (their own resting level, learned in ~45 s) | V1, V2 |
| 8 | **Closing** *(to try)* | Session ends after ~12 min | A gentle closing animation, then rest. Doubles as the facilitator's timer | Not built (see THINGS_TO_TRY) |
| — | **Paper lamp** *(optional)* | Dorm area | Glows with the colours of whoever is in sync | V2 (`group_light`) |

## Design rules (from the meetings)

- Always on; brightness shifts but never drops to dark.
- Changes flow and fade: no flashing, no abrupt jumps, no "bar graph" feel.
- Palettes per person: neighbouring colours with similar contrast, so no strip overpowers the others from across the room.
- Synchrony means heart rates **moving together over time**, not having the same BPM (He et al., 2026). It shows up between pairs (2, 3 or 4 people), not only for the whole group.
- Never make the odd one out look singled out. A person keeps their own colour and simply gains others.
- Build and refine step by step in sessions ("yes, that's it" / "no, change that"), rather than all at once.

## Hardware note

On Hue Lightstrip Plus V4, each strip is one colour at a time. Beats 2–6 therefore play out **over time** and **across** the four strips, not as shapes moving up a strip. Along-the-strip motion (ball, gravity, lava lamp; controller end = floor) needs Hue Gradient strips or the DMX/LED grid.
