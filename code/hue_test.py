#/usr/bin/env python3
# Hue Test Script

import argparse, sys, time
from typing import Optional

try:
    from phue import Bridge
except Exception as e:
    print(f"[hue] Import error: {e}. Did you run 'pip install phue'?", file=sys.stderr)
    sys.exit(1)

# ---------- JD's bridge IP helper ----------

def discover_bridge_ip(fallback_ip: str = "192.168.88.118") -> str:
    """
    Use a known Hue Bridge IP.
    (Auto-discovery disabled to avoid noisy warnings.)
    """
    print(f"[hue] Using configured Hue Bridge IP: {fallback_ip}")
    return fallback_ip

# ---------- Core bridge connector ----------

def connect_bridge(ip: Optional[str] = None) -> Bridge:
    """
    Create a Bridge object.
    - If ip is provided (via --ip), use that.
    - Otherwise, try auto-discovery and fall back to JD's known IP.
    """
    if ip is None:
        ip = discover_bridge_ip()
    else:
        print(f"[hue] Using provided IP: {ip}")

    b = Bridge(ip)
    return b

# ---------- Commands ----------

def cmd_pair(ip: Optional[str]) -> None:
    """
    Register this script with the bridge.
    Press the physical link button, then run:
      python hue_test.py --pair
    """
    try:
        b = connect_bridge(ip)
        print("[hue] Attempting to register... Press the bridge link button now.", file=sys.stderr)
        b.connect()  # on first run after button press, this creates/stores a username in ~/.python_hue
        print("[hue] Paired successfully.")
    except Exception as e:
        print(f"[hue] Pairing failed: {e}\nTip: ensure you're on the same Wi-Fi and the link button was pressed.", file=sys.stderr)

def cmd_list_groups(ip: Optional[str]) -> None:
    """Print available groups/zones so you can use the correct names with --group."""
    try:
        b = connect_bridge(ip); b.connect()
        groups = b.get_group()
        if not groups:
            print("[hue] No groups/zones found.")
            return
        print("ID | Name              | Lights")
        print("---+-------------------+---------------------------")
        for gid, meta in groups.items():
            print(f"{gid:>2} | {meta.get('name'):<17} | {meta.get('lights')}")
    except Exception as e:
        print(f"[hue] Could not list groups: {e}", file=sys.stderr)

def cmd_set_group_hue(ip: Optional[str], name: str, hue_value: int, use_degrees: bool) -> None:
    """Set a group's color using Hue 'hue' attribute."""
    try:
        b = connect_bridge(ip); b.connect()
        groups = b.get_group()
        target_id = None
        for gid, meta in groups.items():
            if meta.get('name') == name:
                target_id = int(gid)
                break
        if target_id is None:
            print(f"[hue] Group '{name}' not found. Use --list-groups to see valid names.", file=sys.stderr)
            return

        hue_native = int(round(hue_value * 65535/360)) if use_degrees else hue_value
        hue_native = max(0, min(65535, hue_native))

        # Turn on + set hue and moderate brightness/saturation
        b.set_group(target_id, 'on', True)
        b.set_group(target_id, 'bri', 200)
        b.set_group(target_id, 'sat', 200)
        b.set_group(target_id, 'hue', hue_native)
        print(f"[hue] Set group '{name}' hue={hue_value}{'°' if use_degrees else ''} (native {hue_native}).")
    except Exception as e:
        print(f"[hue] Failed to set group '{name}': {e}", file=sys.stderr)

def cmd_demo(ip: Optional[str], name: str) -> None:
    """Quick loop that cycles a few hues (blue→cyan→green→yellow→red)."""
    palette_deg = [210, 180, 120, 60, 0]
    try:
        for h in palette_deg:
            cmd_set_group_hue(ip, name, h, use_degrees=True)
            time.sleep(0.7)  # ~1.4 Hz update cadence (safe)
        print("[hue] Demo complete.")
    except KeyboardInterrupt:
        print("\n[hue] Demo interrupted by user.")

# ---------- CLI entry point ----------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Philips Hue group control demo")
    ap.add_argument("--ip", help="Bridge IP (optional; auto-discovery + JD fallback if omitted)")
    ap.add_argument("--pair", action="store_true", help="Register this device with the Hue Bridge (press link button first)")
    ap.add_argument("--list-groups", action="store_true", help="List Hue groups/zones")
    ap.add_argument("--group", help="Target group/zone name (e.g., 'Gallery')")
    ap.add_argument("--hue", type=int, help="Target hue value (0..65535); use --deg to interpret as 0..360 degrees")
    ap.add_argument("--deg", action="store_true", help="Interpret --hue as degrees (0..360) instead of native 0..65535")
    ap.add_argument("--demo", action="store_true", help="Run a short color cycle on the target group")
    args = ap.parse_args()

    if args.pair:
        cmd_pair(args.ip)
    elif args.list_groups:
        cmd_list_groups(args.ip)
    elif args.group and args.demo:
        cmd_demo(args.ip, args.group)
    elif args.group and args.hue is not None:
        cmd_set_group_hue(args.ip, args.group, args.hue, use_degrees=args.deg)
    else:
        ap.print_help()
