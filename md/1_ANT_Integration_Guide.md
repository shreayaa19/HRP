# ANT+ Integration Guide
**Author:** [Shreayaa]
**Date:** [2025-11-05]
**Status:** [Feasible - verified with simulation]

## Executive Summary

Yes, this is feasible. We can take in simultaneous heart-rate streams from multiple Polar H10 / CYCPLUS H1 straps over ANT+ and expose them to the lighting (Hue) and audio (OSC) pipelines while logging to CSV. I have validated the full downstream flow using a simulator.

## Recommended Solution

Library: openant (with a simulation fallback)
Why: It’s a Python library targeting ANT+ profiles (including HRM), fits the project’s Python/macOS hub, and keeps the pipeline in one language.
MacOS Compatible: Likely. But for alternative if macOS USB/driver friction occurs, running the ANT+ receiver on Linux/RPi and stream JSON to the Mac seems to be the best option.

## Installation
# Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Core libs (only needed if testing Hue/OSC too)
pip install phue python-osc

# ANT+ library for real dongle tests
pip install openant

## Device Compatibility
- Polar H10 / CYCPLUS H1: Target devices (ANT+ HR profile).
- ANT+ USB Dongle (FitCent ANT310): Required for real tests; validate macOS recognition.
- macOS Drivers: May require permissions; if blocked, use Linux/RPi as an ANT+ bridge.
- Maximum Devices: 4-5 people in the experince at a time like we discussed.

## Code Example 1: Connect to Single Polar H10
This script prefers real ANT+ via openant and falls back to simulation if openant or the dongle isn’t available. 

# code/ant_test.py (single)
```
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
```

# Run: 
python3 code/ant_test.py --single --simulate --hz 1.0

# Expected Output (example):
{"type": "hr_single", "reading": {"ts_iso": "2025-11-10T00:35:21.663689Z", "device_id": 10001, "bpm": 79.6, "rr_ms": 754}}

## Code Example 2: Connect to Multiple Devices
Emits a batch with multiple readings, one per device ID.

# code/ant_test.py (multi)
```
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
```

# Run:
python3 code/ant_test.py --multi --simulate --devices 6 --hz 1.0

# Expected Output (example):
{"type": "hr_batch", "readings": 
[{"ts_iso": "2025-11-10T00:36:26.022402Z", "device_id": 10000, "bpm": 72.1, "rr_ms": 832}, 
{"ts_iso": "2025-11-10T00:36:26.022848Z", "device_id": 10001, "bpm": 72.5, "rr_ms": 828}, 
{"ts_iso": "2025-11-10T00:36:26.022853Z", "device_id": 10002, "bpm": 83.6, "rr_ms": 717}, 
{"ts_iso": "2025-11-10T00:36:26.022856Z", "device_id": 10003, "bpm": 79.8, "rr_ms": 752}, 
{"ts_iso": "2025-11-10T00:36:26.022859Z", "device_id": 10004, "bpm": 83.7, "rr_ms": 716}, 
{"ts_iso": "2025-11-10T00:36:26.022864Z", "device_id": 10005, "bpm": 85.0, "rr_ms": 705}]}

## Data Format 
{
  "device_id": 10003,                
  "bpm": 79.8,                        
  "rr_ms": 752   
}

## Known Issues / Things to Keep in mind
- macOS USB/driver setup for ANT+ dongles can be finicky
- Multi-device channel handling in openant needs validation on the target Mac.
- RR availability depends on device/profile details; simulator computes RR from BPM.

## Latency Analysis
- Transmission latency: ~1 Hz updates typical
- Processing latency: negligible per packet
- Acceptable? I think yes because lights are intentionally slow/ambient anyway.

## Resources
- openant (Python ANT+ library) installation & HRM examples
- ANT+ Heart Rate Monitor (HRM) device profile documentation