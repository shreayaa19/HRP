# Ableton OSC Integration Guide
**Author:** Shreayaa  
**Date:** 2025-12-11  
**Status:** Feasible (Python OSC tested; Ableton-side pending)

## Executive Summary
Yes, Python can reliably send OSC messages that Ableton Live can receive via Max for Live. 
The OSC sender has been implemented and tested locally. Once Ableton and a Max for Live OSC receiver are available, real-time heart-rate–driven sound control can be validated.

## What is OSC?
OSC (Open Sound Control) is a lightweight network protocol widely used in music, lighting, and interactive installations.

Compared to MIDI:
- Higher resolution (floats, not just integers)
- Network-based (UDP)
- Flexible message structure (custom addresses like `/bpm`, `/hr/group_avg`)

This makes OSC well suited for mapping biometric data to sound parameters.

## Ableton Live + OSC Overview
Ableton Live does not natively receive OSC messages.
However, **Max for Live** devices can listen for OSC and map incoming values to:
- tempo
- filter cutoff
- reverb depth
- volume
- generative parameters

Typical OSC settings:
- **IP:** `127.0.0.1` (localhost)
- **Port:** `9000` (common default)

Example OSC message:
/bpm 78.2

## Python Code Example (OSC Sender)
```python
from pythonosc.udp_client import SimpleUDPClient
client = SimpleUDPClient("127.0.0.1", 9000)
client.send_message("/bpm", 78.2)
```

In this project, the sender is implemented in:
``` bash code/osc_test.py```

Example usage:
``` bash python3 code/osc_test.py --addr /bpm --value 75```