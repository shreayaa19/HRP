#!/usr/bin/env python3
"""
HRP Session Runner

One-command launcher for HRP prototype workflows.

This script does NOT replace the individual scripts.
It runs them together in reliable combinations so the project is easier to demo.

Examples:
  python3 code/hr_session_runner.py --mode router
  python3 code/hr_session_runner.py --mode osc
  python3 code/hr_session_runner.py --mode hue
"""

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def banner(mode: str):
    print("\n===================================")
    print(" Human Resonance Project Runner")
    print("===================================")
    print(f"Mode: {mode}")
    print("Press Ctrl+C to stop.\n")


def run_pipeline(commands):
    """
    Run scripts connected through pipes.

    Example:
    hr_simulator.py stdout -> hr_router_live.py stdin
    """
    processes = []

    try:
        previous_stdout = None

        for i, cmd in enumerate(commands):
            is_last = i == len(commands) - 1

            print("[runner] launching:", " ".join(cmd))

            p = subprocess.Popen(
                cmd,
                stdin=previous_stdout,
                stdout=None if is_last else subprocess.PIPE,
                stderr=None,
                text=True,
                bufsize=1,
            )

            if previous_stdout is not None:
                previous_stdout.close()

            previous_stdout = p.stdout
            processes.append(p)

        processes[-1].wait()

    except KeyboardInterrupt:
        print("\n[runner] stopping all processes...")

    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()

        for p in processes:
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()

        print("[runner] stopped.")


def main():
    ap = argparse.ArgumentParser(description="Run HRP prototype workflows with one command.")
    ap.add_argument(
        "--mode",
        choices=["sim", "router", "osc", "hue"],
        required=True,
        help="Which workflow to launch.",
    )

    args = ap.parse_args()
    banner(args.mode)

    sim = [PYTHON, str(ROOT / "code" / "hr_simulator.py")]

    if args.mode == "sim":
        run_pipeline([sim])

    elif args.mode == "router":
        router = [PYTHON, "-u", str(ROOT / "code" / "hr_router_live.py")]
        run_pipeline([sim, router])

    elif args.mode == "osc":
        router_osc = [
            PYTHON,
            "-u",
            str(ROOT / "code" / "hr_router_live.py"),
            "--osc",
        ]
        run_pipeline([sim, router_osc])

    elif args.mode == "hue":
        hue_sim = [
            PYTHON,
            "-u",
            str(ROOT / "code" / "legacy" / "hue_sim_from_hr.py"),
            "--group",
            "Office",
            "--interval",
            "2.0",
        ]
        run_pipeline([sim, hue_sim])


if __name__ == "__main__":
    main()