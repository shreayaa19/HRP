#!/usr/bin/env python3
"""
OSC Test Script
Sends OSC messages (e.g., BPM values) to a target IP/port.

Ableton Live + Max for Live devices typically listen on:
    IP: 127.0.0.1
    Port: 9000 or 8000

Usage examples:
    python3 code/osc_test.py --addr /bpm --value 72
    python3 code/osc_test.py --addr /hr/color --value 0.45
"""

import argparse
from pythonosc.udp_client import SimpleUDPClient

def main():
    ap = argparse.ArgumentParser(description="Send a single OSC message")
    ap.add_argument("--ip", default="127.0.0.1", help="Receiver IP (default: localhost)")
    ap.add_argument("--port", type=int, default=9000, help="Receiver port")
    ap.add_argument("--addr", required=True, help="OSC address (e.g., /bpm)")
    ap.add_argument("--value", type=float, required=True, help="Value to send")
    args = ap.parse_args()

    client = SimpleUDPClient(args.ip, args.port)
    client.send_message(args.addr, args.value)

    print(f"[osc] Sent {args.addr} = {args.value} to {args.ip}:{args.port}")

if __name__ == "__main__":
    main()
