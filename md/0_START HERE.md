BEGIN “START HERE” WHITE PAPER

HUMAN RESONANCE PROJECT – START HERE (REENTRY BRIEFING)

This document is your high-level reorientation guide after stepping away from the ANT → HR → CSV → Hue → Ableton → Experience pipeline. It tells you:

What is fully working right now

Where you are in the architecture (with a YOU ARE HERE marker)

What remains to be built

What the next experiments should be

How this connects to the broader HRP experience concepts

Future multimodal possibilities (VDMX, controllers, multi-person zones)

Keep this briefing visible when you return.

SECTION 1 — CURRENT STATUS (WHAT WORKS TODAY)

• ANT+ heart-rate straps are confirmed working with your USB dongle on Windows.
• ant_hr_to_json.py successfully parses openant output and emits clean JSON events.
• JSONL streams from hardware can be recorded to disk manually.
• ant_to_csv.py successfully converts JSONL into auto-numbered hr_log_00X.csv files.
• The whole system works as a two-step pipeline.

This means:

Raw HR → ANT+ dongle → openant → JSON stream → CSV
is solid, validated, and reproducible.

This is the hardest technical part — you already crossed it.

SECTION 2 — FULL PIPELINE ARCHITECTURE (TOP TO BOTTOM)

Here is the conceptual architecture you envisioned:

[1] Sensor Input Layer
• ANT+ heart-rate straps
• Future: up to 3–4 simultaneous straps

[2] Data Acquisition Layer
• ant_hr_to_json.py
• openant scan
• Produces JSONL event stream

      YOU ARE HERE  ←–––––––––––––– Right now your work stops here.


[3] Data Conversion Layer
• ant_to_csv.py
• Converts JSONL → hr_log_00X.csv
• Fully validated

[4] Real-Time Signal Routing Layer
• Future python processes will:
- read the JSON stream live
- broadcast heart-rate values to:
• Philips Hue
• Ableton Live (via OSC or MIDI)
• VDMX (OSC, MIDI, Syphon, etc.)

[5] Multimodal Output Layer
• Real-time light feedback (Hue)
• Real-time audiovisual feedback (Ableton, VDMX)
• VR/AR or projection-mapped surfaces (optional)
• Gallery interaction zones (1–3 person)

[6] Experience Layer (HRP Installation)
• Shared resonance
• Individual breath/HR mirroring
• Collective co-regulation patterns
• Color/sound “conversation” between participants’ bodies

Your current location: fully through steps [1–3].
Your next objectives: begin step [4], then step [5].

SECTION 3 — WHAT REMAINS TO BUILD (ROADMAP A → B → C)

A. Build the “HR Session Runner”
A Python script (hr_session_runner.py) that:
• Starts HR acquisition
• Records JSONL for N seconds
• Automatically converts to CSV
• Eventually routes real-time events to Hue/Ableton/VDMX
• Gives you one-command entry

This makes testing dramatically easier.

B. Add real-time broadcast hooks inside ant_hr_to_json.py
Instead of only printing JSON, we add optional live outputs:
• OSC messages (for Ableton, VDMX)
• HTTP or UDP packets
• Direct Hue API calls (phue library)

This will let HR become a live control signal.

C. Integrate Philips Hue
Easiest real-time branch.
We can test simple mappings like:

One strap:
• bpm → color temperature
• bpm → brightness
• bpm → saturation
• rr_ms (if we ever get it) → flicker or breathing patterns

Two straps:
• Difference in HR → two-light contrasting colors
• Signals converge → lights move toward harmony or shared hue
• HR variability → shimmer or turbulence overlay

Three straps:
• Each participant controls one hue channel: R, G, B
• Collective state produces a “shared mixed color” in the center zone
• A smooth metric (e.g., mean HR, variance) controls movement patterns

D. Integrate Ableton Live
Two easy possibilities:

Option 1 — MIDI (via python-rtmidi)
• HR → MIDI CC controlling filter, resonance, or FX sends
• HR diff → pan left/right
• RR → tempo nudging or tremolo rate

Option 2 — OSC into Max for Live
• More flexible
• Allows HR to drive envelopes, LFOs, delays, ambience
• HR sync patterns could create a sonic “pulse forest”

E. Integrate VDMX
Two paths:

OSC mapping
• HR → brightness, opacity, turbulence amount
• HR diff → color shift
• HR sync → strobe or glow pulses

Gamepad controller (DualShock 4)
• You can override, amplify, or shape the HR-driven visuals
• Buttons trigger scene transitions
• Stick directions add curvature or organic distortions
• Pressure triggers fade changes

This gives VDMX both a “data channel” and a “human agency layer.”

SECTION 4 — EXPERIMENTS YOU MUST RUN WHEN YOU RETURN

Experiment 1 — One HR strap → Hue
Goal: prove real-time control works.

Test patterns:
• bpm → hue rotation (sine wave)
• bpm → brightness pulsing
• Smooth breathing-like animation driven by moving averages

Success criteria:
• <150ms perceived latency
• Clear mapping that a participant can feel

Experiment 2 — Two straps → Hue
Goal: visualize co-regulation.

Test patterns:
• HR difference → distance between two colors
• HR convergence → lights merge to a shared white/gold
• HR “conversation” → color oscillation between participants
• HR variability → noise layer modulating saturation

This experiment demonstrates the emotional concept:
“interpersonal resonance.”

Experiment 3 — One strap → Ableton
Goal: create sonic responsiveness.

Test patterns:
• HR → reverb send
• HR → delay time
• HR → low-pass filter cutoff
• HR → drone note selection via MIDI pitch bend

This gives your HRP installation a sonic limbic system.

Experiment 4 — Combine Hue + Ableton
Goal: multimodal alignment.

When HR rises:
• lights brighten
• sound sharpens or accelerates

When HR falls:
• lights warm and dim
• sound becomes airy or slow

This is the most powerful experiential test.

Experiment 5 — Three zones (3 straps)
Goal: simulate the future gallery installation.

Possible rules:
• Each person controls one primary light
• Middle space blends them
• Aligning HR reduces visual noise
• Diverging HR increases turbulence or chaos
• Sonic textures represent the “state” of the group

This is the foundation for your HRP gallery exhibit.

SECTION 5 — VISION FOR FUTURE-INTEGRATED SYSTEM

Eventually you will have:

• Python orchestrating all signals
• HR feeding Hue + Ableton + VDMX
• A game controller for navigation, mode-shifting, or exaggeration
• Possibly a central visual sculpture (projection or LED cluster)
• Data logs for research
• Real-time multimodal feedback for experience design

This is not just a tech pipeline:
It becomes a co-regulatory, emotionally intelligent environment.

SECTION 6 — WHERE TO START WHEN YOU RETURN

The exact action list for future-you:

Re-read your markdown pipeline guide (the one we wrote together).

Implement hr_session_runner.py.

Add a simple callback inside ant_hr_to_json.py that prints JSON to an OSC client.

Write a tiny Hue test script that listens for HR events and changes one bulb.

Make the 1-person Hue test work (Experiment 1).

Extend to 2-person co-regulation colors (Experiment 2).

Begin Ableton mapping tests using OSC → Max for Live (Experiment 3).

Try a combined Hue + Ableton run (Experiment 4).

Prepare the 3-zone prototype with three straps (Experiment 5).

Optional: integrate VDMX using OSC.

Optional: add gamepad control for transitions and overrides.

After these steps, you are ready for HRP gallery prototyping.

SECTION 7 — FINAL REMINDER

You have already completed the hardest work:
hardware validation, JSON parsing, CSV logging, and pipeline stability.

The next phase is creative, architectural, and artistic.

Nothing is blocking you technically — it’s just wiring and mapping now.

Take a breath, you did fantastic groundwork.
When you return, you’ll be ready to build resonance.

END “START HERE” WHITE PAPER

If you want, I can also generate:

• A printable PDF layout of this white paper
• A version formatted for GitHub README
• A simplified “5-minute summary” version
• A folder structure for the next phase (real-time integration)