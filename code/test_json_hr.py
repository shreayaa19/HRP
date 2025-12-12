#!/usr/bin/env python3
"""
Tiny test generator: prints 5 fake hr_single JSON lines to stdout.
Used to test ant_to_csv.py without ANT hardware.
"""

import json
import time

for i in range(5):
    payload = {
        "type": "hr_single",
        "reading": {
            "ts_iso": f"test-{i}",
            "device_id": 12345,
            "bpm": 80 + i,
            "rr_ms": None,
        },
    }
    print(json.dumps(payload), flush=True)
    time.sleep(0.1)
