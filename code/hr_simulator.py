#!/usr/bin/env python3
import time, json, math

BASELINE = 85          # starting BPM
STEP = 2               # gradient step 
INTERVAL = 1.0         # seconds between updates

def main():
    bpm = BASELINE
    direction = 1   

    print("[sim] HR simulator running")

    while True:
        bpm += STEP * direction

        # bounce between limits
        if bpm >= 100:
            direction = -1
        elif bpm <= 70:
            direction = 1

        msg = {
            "type": "hr_single",
            "reading": {
                "ts_iso": time.time(),
                "device_id": 99999,
                "bpm": bpm,
                "rr_ms": None
            }
        }

        print(json.dumps(msg), flush=True)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
