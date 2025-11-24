# Philips Hue Control Guide
**Author:** Shreayaa  
**Date:** 2025-11-07  
**Status:** In progress (no Bridge detected; simulation complete; real control ready for next meeting)

---

## Readme
```bash
python3 code/ant_test.py --multi --simulate --devices 6 --hz 1.0 | \
  python3 code/hue_sim_from_hr.py --group "Gallery" --interval 2.0
```

This:
- simulates 6 heart-rate monitors  
- computes group BPM  
- maps BPM → Hue color  
- prints the “virtual” Hue command 

## Overview
The Philips Hue system for this project is designed to control ~40 lightstrips using **Hue groups/zones** (not individual bulbs).  
This allows smooth, ambient lighting effects that represent visitors’ heart-rate synchrony.

There are **two modes**:

1. **Real mode** (works when Jeremy has the Hue Bridge)  
2. **Simulation mode** (works now, without hardware)

---

## 1. Installation

```bash
pip install phue
```

---

## 2. Real Hue Control (Bridge required)

Pair:

```bash
python3 code/hue_test.py --pair
# OR if discovery fails
python3 code/hue_test.py --ip <BRIDGE_IP> --pair
```

List groups/zones:

```bash
python3 code/hue_test.py --list-groups
```

Set a group’s color:

```bash
python3 code/hue_test.py --group "Gallery" --hue 210 --deg
```

Run the demo:

```bash
python3 code/hue_test.py --group "Gallery" --demo
```

---

## 3. Hue Simulation (No Bridge Required)

This mode uses **heart-rate JSON from ant_test.py** and maps BPM → color.

Run this full simulation pipeline:

```bash
python3 code/ant_test.py --multi --simulate --devices 6 --hz 1.0 | \
  python3 code/hue_sim_from_hr.py --group "Gallery" --interval 2.0
```

Every interval:
- Computes group average BPM  
- Maps BPM to a hue degree  
- Converts to Philips-native hue (0–65535)  
- Prints the “virtual” color command

Example output:

```
[sim-hue] group='Gallery' avg_bpm=78.5 → hue_deg=145.3°, native=26455
```

---

## 4. Rate Limiting

- Target **0.5–1.0 Hz** update speed  
- Hue Bridges throttle fast requests  
- Group-level changes are smooth and ambient

---

## 5. Troubleshooting

- Must be on the same Wi-Fi as the bridge  
- Press the physical link button before pairing  
- If `--pair` fails, use explicit IP  
- If group names fail, run `--list-groups`

---

## Status (as of Nov 2025)
- Simulation pipeline tested and working  
- Real bridge testing will occur during the next meeting  
