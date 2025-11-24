#!/usr/bin/env python3
"""
ANT+ Test Script
- Code Example 1: --single
- Code Example 2: --multi

This file uses a SIMULATOR by default so you can run without hardware.
When you pass --ant (and have `openant` + a USB ANT+ dongle installed),
the 'real_*' functions are where you'll integrate true ANT+ reads.

Run examples (simulation):
  python code/ant_test.py --single --simulate --hz 1.0
  python code/ant_test.py --multi --simulate --devices 6 --hz 1.0

Try real ANT later (requires: pip install openant + FitCent ANT310 plugged in):
  python code/ant_test.py --single --ant
  python code/ant_test.py --multi --ant
"""

import argparse, time, json, sys, random, math, datetime as dt, importlib

def now_iso(): 
    return dt.datetime.utcnow().isoformat() + "Z"

#Simulation
def sim_single(hz=1.0, base=78.0, spread=4.0, dev=10001): #Emit ONE device's heart-rate reading at ~hz samples/sec.
    print("[sim] single-device stream starting...", file=sys.stderr)
    period = 1.0 / max(hz, 1e-6) # Sample period derived from requested Hz
    phase = random.random() * 2 * math.pi # Each simulated device gets its own sine phase so BPM changes look organic
    while True:
        wobble = math.sin(time.time()*0.3 + phase) * 2.0 # A light, smooth wobble + noise to look like a real heart rate trace
        bpm = max(40, min(180, base + random.uniform(-spread, spread) + wobble))
        rr  = int(60000.0 / max(bpm, 1e-3))
        print(json.dumps({"type":"hr_single",
                          "reading":{"ts_iso":now_iso(),"device_id":dev,
                                     "bpm":round(bpm,1),"rr_ms":rr}}), flush=True)
        time.sleep(period)

def sim_multi(n=6, hz=1.0, base=78.0, spread=8.0): #Emit MANY devices at once; one JSON batch per tick.
    print(f"[sim] multi-device stream starting with {n} devices...", file=sys.stderr)
    period = 1.0 / max(hz, 1e-6)
    phases = [random.random()*2*math.pi for _ in range(n)] # Give each device its own phase so their BPMs don't all move in lockstep
    while True:
        readings = []
        for i in range(n):
            wobble = math.sin(time.time()*0.3 + phases[i]) * 2.0 # Organic wobble + noise per device
            bpm = max(40, min(180, base + random.uniform(-spread, spread) + wobble))
            rr  = int(60000.0 / max(bpm, 1e-3))
            readings.append({"ts_iso":now_iso(),"device_id":10000+i,
                             "bpm":round(bpm,1),"rr_ms":rr})
        print(json.dumps({"type":"hr_batch","readings":readings}), flush=True)
        time.sleep(period)

#Placeholder for REAL single-device ANT+ capture using `openant`. If `openant` is missing (or not yet configured), we fall back to simulation.
def real_single(hz=1.0):
    if importlib.util.find_spec("openant") is None:
        print("[ant] openant not installed → sim", file=sys.stderr)
        return sim_single(hz=hz)
    print("[ant] openant detected (stub) → sim until hardware wired", file=sys.stderr)
    return sim_single(hz=hz)

def real_multi(hz=1.0):
    if importlib.util.find_spec("openant") is None:
        print("[ant] openant not installed → sim", file=sys.stderr)
        return sim_multi(n=6, hz=hz)
    print("[ant] openant detected (stub) → sim until hardware wired", file=sys.stderr)
    return sim_multi(n=6, hz=hz)

#CLI (Command Line Interface)
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--single", action="store_true", help="Code Example 1")
    mode.add_argument("--multi",  action="store_true", help="Code Example 2")
    src  = ap.add_mutually_exclusive_group()
    src.add_argument("--ant", action="store_true", help="try real ANT+ (requires openant + dongle)")
    src.add_argument("--simulate", action="store_true", help="force simulator")

    ap.add_argument("--devices", type=int, default=6, help="simulation device count (multi)")
    ap.add_argument("--hz", type=float, default=1.0, help="samples/sec")
    args = ap.parse_args()

    if args.single:
        (real_single if args.ant else sim_single)(hz=args.hz)
    else:
        (real_multi  if args.ant else sim_multi)(n=args.devices, hz=args.hz)
