"""
Minimal sanity check: can openant open the ANT USB stick?

Run from inside the HRP_shreayaa virtualenv with:
    python ant_open_probe.py
"""

import logging

try:
    # openant's blocking convenience layer
    from openant.easy.node import Node
except ImportError as e:
    print("[FATAL] Could not import openant.easy.node.Node")
    print("Error was:", repr(e))
    raise


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    print("=== openant ANT stick probe ===")

    try:
        print("[STEP] Creating Node() (this is where USB open happens)...")
        node = Node()  # this will try to open the first ANT USB stick it finds

        print("[OK] Node() constructed successfully.")
        print("     This *strongly* suggests openant could talk to the ANT USB stick.")

        # Optional: try a very short start/stop just to exercise the event loop.
        # Node.start() is blocking, so we don't leave it running.
        print("[STEP] Starting node for a brief smoke test...")
        try:
            # Start the node in a tiny time-slice just to make sure it doesn't immediately explode.
            # In openant, Node.start() runs an internal loop until stop() is called from
            # another thread; here we just call stop() right away and rely on logging
            # to show if anything went wrong during start-up.
            #
            # If this hangs or spews USB errors, comment this block out again.
            node.start()
        except Exception as e:
            print("[WARN] node.start() raised an exception:")
            print("       ", repr(e))
        finally:
            print("[STEP] Stopping node (if it started)...")
            try:
                node.stop()
                print("[OK] node.stop() returned cleanly.")
            except Exception as e_stop:
                print("[WARN] node.stop() raised an exception:")
                print("       ", repr(e_stop))

        print("=== Probe complete ===")

    except Exception as e:
        print("[FATAL] Exception while creating or starting Node():")
        print("        ", repr(e))
        print()
        print("Common culprits to check:")
        print("  - libusbK driver is correctly bound to VID 0x0fcf / PID 0x1008")
        print("  - No Garmin Express / other ANT software is currently using the stick")
        print("  - openant and pyusb versions are compatible")
        raise


if __name__ == "__main__":
    main()
