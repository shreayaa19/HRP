#!/usr/bin/env python3
"""
hr_router_live.py

Reads HR JSON events from stdin (one JSON object per line).
Optionally broadcasts BPM over OSC (for Ableton / VDMX / Max).

Expected input schema:
{"type":"hr_single","reading":{"ts_iso":"...","device_id":51861,"bpm":89,"rr_ms":null}}
"""

import sys, json, argparse

def main():
    ap = argparse.ArgumentParser(description="Route HR JSON stream to outputs (print / OSC)")
    ap.add_argument("--osc", action="store_true", help="Enable OSC broadcast")
    ap.add_argument("--osc-ip", default="127.0.0.1", help="OSC receiver IP (default: localhost)")
    ap.add_argument("--osc-port", type=int, default=9000, help="OSC receiver port")
    ap.add_argument("--osc-addr", default="/bpm", help="OSC address for BPM messages")
    args = ap.parse_args()

    client = None
    if args.osc:
        from pythonosc.udp_client import SimpleUDPClient
        client = SimpleUDPClient(args.osc_ip, args.osc_port)
        print(f"[router] OSC enabled → {args.osc_ip}:{args.osc_port} addr={args.osc_addr}", flush=True)

    print("[router] listening for HR JSON on stdin", flush=True)

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            if msg.get("type") != "hr_single":
                continue

            r = msg.get("reading", {})
            ts = r.get("ts_iso")
            device_id = r.get("device_id")
            bpm = r.get("bpm")
            rr = r.get("rr_ms")

            print(f"[router] ts={ts} device={device_id} bpm={bpm} rr_ms={rr}", flush=True)

            if client is not None and isinstance(bpm, (int, float)):
                client.send_message(args.osc_addr, float(bpm))
                print(f"[router] → OSC {args.osc_addr} {float(bpm)}", flush=True)

    except KeyboardInterrupt:
        print("\n[router] stopped by user", flush=True)

if __name__ == "__main__":
    main()
