# Integrated HR–Hue Prototype: Hardware Test Guide

This guide validates the complete pipeline on the computer connected to the
ANT+ dongle, heart-rate monitors, Philips Hue Bridge, and Hue lights.

## Before starting

Run every command from the repository root. Replace the example Bridge IP and
Hue group name when necessary.

### Activate the virtual environment

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Confirm that the active Python comes from `.venv`:

```powershell
python -c "import sys; print(sys.executable)"
```

Install the required Python packages:

```powershell
python -m pip install openant pyusb python-osc phue
```

Connect the ANT+ dongle, wear/wake the heart-rate straps, power the Hue Bridge,
and make sure the computer and Bridge can communicate on the same network.

## Test 1: ANT+ acquisition by itself

```powershell
python -u .\code\ant_hr_to_json.py
```

Pass criteria:

- OpenANT starts without a traceback.
- Each active monitor produces `[match]` and `[json]` messages.
- Expected device IDs, such as `51861` and `51950`, appear.
- BPM values change plausibly.

Stop with Ctrl+C after confirming the readings.

## Test 2: Hue control by itself

List the Bridge's groups and zones:

```powershell
python .\code\hue_test.py --ip 192.168.88.118 --list-groups
```

If this computer has not been paired with the Bridge:

1. Press the physical link button on the Hue Bridge.
2. Immediately run:

```powershell
python .\code\hue_test.py --ip 192.168.88.118 --pair
```

Use the exact group name returned by `--list-groups` to run a color cycle:

```powershell
python .\code\hue_test.py --ip 192.168.88.118 --group "Office" --demo
```

Pass criteria:

- The correct group is found.
- Its lights visibly cycle through colors.
- No Bridge, authentication, or network error appears.

## Test 3: Real ANT+ input through the integrated prototype

This test uses real sensors while keeping Hue and OSC network output disabled.
It creates a real CSV file.

```powershell
python -u .\code\ant_hr_to_json.py | python -u .\code\integrated_prototype.py --group "Office" --dry-run --csv --mapping dramatic --window 3
```

Pass criteria:

- `[input]` shows each device ID and BPM.
- `[group]` shows the correct number of devices and a plausible average.
- `[hue-dry-run]` moves among blue, green/yellow, and red mappings.
- `[csv] wrote 1 row` continues appearing.
- The generated file under `outputs/hr_logs` contains the same readings.

`--dry-run` intentionally prevents real Hue and OSC network output. CSV logging
remains enabled.

## Test 4: Real HR to real Hue and CSV

```powershell
python -u .\code\ant_hr_to_json.py | python -u .\code\integrated_prototype.py --group "Office" --ip 192.168.88.118 --hue --csv --mapping dramatic --window 3 --interval 1
```

Pass criteria:

- Real HR readings enter the integrated prototype.
- The group-average BPM changes.
- The selected Hue group visibly responds at most once per second.
- CSV logging continues while Hue updates.
- The pipeline runs without crashing.

The dramatic debug mapping is:

- Below 80 BPM: blue, lower brightness
- 80–94 BPM: green through yellow, medium brightness
- 95 BPM and above: red, maximum brightness

## Test 5: OSC receiver by itself

Open a second terminal, activate the same virtual environment, and start this
temporary receiver:

```powershell
python -c "from pythonosc.dispatcher import Dispatcher; from pythonosc.osc_server import BlockingOSCUDPServer; d=Dispatcher(); d.map('/bpm', lambda address, *values: print(address, *values, flush=True)); print('Listening on 127.0.0.1:9000'); BlockingOSCUDPServer(('127.0.0.1', 9000), d).serve_forever()"
```

Leave this terminal open for Test 6.

## Test 6: Complete HR, Hue, CSV, and OSC pipeline

In the first terminal, run:

```powershell
python -u .\code\ant_hr_to_json.py | python -u .\code\integrated_prototype.py --group "Office" --ip 192.168.88.118 --hue --csv --osc --osc-ip 127.0.0.1 --osc-port 9000 --osc-addr /bpm --mapping dramatic --window 3 --interval 1
```

Pass criteria:

- ANT+ readings appear for the active monitors.
- Hue responds to the group average.
- CSV rows continue to be written.
- The receiver terminal prints `/bpm` followed by changing values.
- Ctrl+C shuts the pipeline down cleanly.

## Test 7: Stability test

Run the complete pipeline for at least 5–10 minutes.

Pass criteria:

- No crash or unhandled traceback occurs.
- Sensor readings continue arriving.
- Hue continues updating.
- OSC continues reaching the receiver.
- The CSV grows continuously and opens correctly afterward.
- Ctrl+C produces a clean shutdown.

## Results to record

Please send back:

- The Bridge IP and exact Hue group name
- Detected ANT+ device IDs
- Full terminal output from any failed test
- Whether Hue changes were clearly visible
- The generated CSV file or its first several rows
- Whether the OSC receiver displayed `/bpm` values
- How long the stability test ran

## Quick troubleshooting

### `No module named openant`, `pythonosc`, or `phue`

Make sure `.venv` is active, then install the missing package with:

```powershell
python -m pip install openant python-osc phue
```

### `openant.base.driver.DriverNotFound`

OpenANT cannot detect a compatible ANT+ USB dongle. Reconnect the dongle, avoid
an unreliable USB hub, and confirm that the operating system sees it.

### `usb.core.NoBackendError`

The native USB backend is missing. On macOS, install it with:

```bash
brew install libusb
```

### Hue group not found

Run `hue_test.py --list-groups` and copy the group name exactly into `--group`.

### Hue authentication error

Press the Bridge link button and rerun `hue_test.py --pair` immediately.

### OSC sender prints messages but the receiver shows nothing

Confirm that both use the same IP, port, and address. For the local test these
must be `127.0.0.1`, `9000`, and `/bpm`. Also check firewall or UDP restrictions.

### CSV contains only its header

No valid heart-rate JSON reached the integrated prototype. Fix the ANT+
acquisition error first, then rerun the pipeline.
